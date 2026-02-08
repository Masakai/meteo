"""HTTP route handlers for the dashboard."""

from datetime import datetime
from time import time
import json
import os
from pathlib import Path
from threading import Event, Lock, Thread
import threading
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from dashboard_config import CAMERAS, DETECTIONS_DIR, VERSION, get_detection_window
from dashboard_templates import render_dashboard_html


_IN_DOCKER = os.path.exists("/.dockerenv")
_SERVER_START_TIME = time()
_LABELS_FILENAME = "detection_labels.json"
_DETECTION_MONITOR_INTERVAL = float(os.environ.get("DETECTION_MONITOR_INTERVAL", "2.0"))
_detection_cache_lock = Lock()
_detection_cache = {
    "detections_dir": "",
    "mtime": 0.0,
    "total": 0,
    "recent": [],
}
_detection_monitor_stop = Event()
_detection_monitor_thread = None
_CAMERA_STREAM_TIMEOUT = 300
_CAMERA_STREAM_CHUNK_SIZE = 1024 * 64
_dashboard_cpu_lock = Lock()
_dashboard_cpu = {
    "cpu_percent": 0.0,
    "last_wall": time(),
    "last_cpu": 0.0,
}


def _process_cpu_time():
    process_times = os.times()
    return process_times.user + process_times.system


def _sample_dashboard_cpu():
    now_wall = time()
    now_cpu = _process_cpu_time()
    with _dashboard_cpu_lock:
        prev_wall = _dashboard_cpu["last_wall"]
        prev_cpu = _dashboard_cpu["last_cpu"]
        if prev_wall is not None:
            elapsed = now_wall - prev_wall
            cpu_delta = now_cpu - prev_cpu
            if elapsed > 0 and cpu_delta >= 0:
                _dashboard_cpu["cpu_percent"] = max(0.0, (cpu_delta / elapsed) * 100.0)
        _dashboard_cpu["last_wall"] = now_wall
        _dashboard_cpu["last_cpu"] = now_cpu


def get_dashboard_cpu_snapshot(refresh=True):
    if refresh:
        _sample_dashboard_cpu()
    with _dashboard_cpu_lock:
        return {
            "cpu_percent": round(float(_dashboard_cpu["cpu_percent"]), 1),
        }


def _parse_camera_index(path):
    parsed_path = urlparse(path).path
    camera_index = int(parsed_path.rstrip("/").split("/")[-1])
    if camera_index < 0 or camera_index >= len(CAMERAS):
        raise ValueError(f"camera index out of range: {camera_index}")
    return camera_index


def _camera_url_for_proxy(raw_url, camera_index=None):
    parsed = urlparse(raw_url)
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1"):
        if _IN_DOCKER and camera_index is not None:
            return f"{parsed.scheme}://camera{camera_index + 1}:8080"
        netloc = "host.docker.internal"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return raw_url


def _labels_path():
    return Path(DETECTIONS_DIR) / _LABELS_FILENAME


def _load_detection_labels():
    path = _labels_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_detection_labels(labels):
    path = _labels_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(labels, f, ensure_ascii=False, sort_keys=True)
    tmp_path.replace(path)


def _detection_label_key(camera_name, detection_time):
    return f"{camera_name}|{detection_time}"


def _normalize_detection_label(label):
    value = str(label or "").strip()
    if value == "post_detected":
        return "post_detected"
    return "detected"


def _compute_latest_mtime():
    latest_mtime = 0.0
    detections_root = Path(DETECTIONS_DIR)
    try:
        for cam_dir in detections_root.iterdir():
            if cam_dir.is_dir():
                jsonl_file = cam_dir / "detections.jsonl"
                if jsonl_file.exists():
                    mtime = jsonl_file.stat().st_mtime
                    if mtime > latest_mtime:
                        latest_mtime = mtime
    except Exception:
        pass

    try:
        labels_mtime = _labels_path().stat().st_mtime
        if labels_mtime > latest_mtime:
            latest_mtime = labels_mtime
    except Exception:
        pass
    return latest_mtime


def _build_detections_payload():
    detections = []
    total = 0
    labels = _load_detection_labels()

    try:
        for cam_dir in Path(DETECTIONS_DIR).iterdir():
            if cam_dir.is_dir():
                jsonl_file = cam_dir / "detections.jsonl"
                if jsonl_file.exists():
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                d = json.loads(line)
                                timestamp_str = d.get("timestamp", "")
                                if timestamp_str:
                                    dt = datetime.fromisoformat(timestamp_str)
                                    base_filename = f"meteor_{dt.strftime('%Y%m%d_%H%M%S')}"
                                    clip_ext = None
                                    if (cam_dir / f"{base_filename}.mov").exists():
                                        clip_ext = ".mov"
                                    elif (cam_dir / f"{base_filename}.mp4").exists():
                                        clip_ext = ".mp4"

                                    mp4_path = (
                                        f"{cam_dir.name}/{base_filename}{clip_ext}"
                                        if clip_ext
                                        else ""
                                    )
                                    composite_path = f"{cam_dir.name}/{base_filename}_composite.jpg"
                                    composite_orig_path = f"{cam_dir.name}/{base_filename}_composite_original.jpg"
                                else:
                                    mp4_path = ""
                                    composite_path = ""
                                    composite_orig_path = ""

                                total += 1
                                display_time = timestamp_str[:19].replace("T", " ")
                                label_key = _detection_label_key(cam_dir.name, display_time)
                                detections.append(
                                    {
                                        "time": display_time,
                                        "camera": cam_dir.name,
                                        "confidence": f"{d.get('confidence', 0):.0%}",
                                        "image": composite_path,
                                        "mp4": mp4_path,
                                        "composite_original": composite_orig_path,
                                        "label": _normalize_detection_label(labels.get(label_key, "")),
                                    }
                                )
                            except Exception:
                                pass
    except Exception:
        pass

    detections.sort(key=lambda x: x["time"], reverse=True)
    return {"total": total, "recent": detections}


def _refresh_detection_cache(force=False):
    latest_mtime = _compute_latest_mtime()
    with _detection_cache_lock:
        cache_dir = _detection_cache["detections_dir"]
        cache_mtime = _detection_cache["mtime"]
    current_dir = str(Path(DETECTIONS_DIR).resolve())

    should_rebuild = force or cache_dir != current_dir or latest_mtime != cache_mtime
    if not should_rebuild:
        return

    payload = _build_detections_payload()
    with _detection_cache_lock:
        _detection_cache["detections_dir"] = current_dir
        _detection_cache["mtime"] = latest_mtime
        _detection_cache["total"] = payload["total"]
        _detection_cache["recent"] = payload["recent"]


def get_detection_cache_snapshot():
    _refresh_detection_cache(force=False)
    with _detection_cache_lock:
        return {
            "mtime": _detection_cache["mtime"],
            "total": _detection_cache["total"],
            "recent": list(_detection_cache["recent"]),
        }


def _detection_monitor_loop():
    while not _detection_monitor_stop.wait(_DETECTION_MONITOR_INTERVAL):
        try:
            _refresh_detection_cache(force=False)
            _sample_dashboard_cpu()
        except Exception:
            pass


def start_detection_monitor():
    global _detection_monitor_thread
    with _detection_cache_lock:
        if _detection_monitor_thread and _detection_monitor_thread.is_alive():
            return
    _refresh_detection_cache(force=True)
    with _dashboard_cpu_lock:
        _dashboard_cpu["last_wall"] = time()
        _dashboard_cpu["last_cpu"] = _process_cpu_time()
        _dashboard_cpu["cpu_percent"] = 0.0
    _detection_monitor_stop.clear()
    thread = Thread(target=_detection_monitor_loop, name="detections-monitor", daemon=True)
    thread.start()
    with _detection_cache_lock:
        _detection_monitor_thread = thread


def stop_detection_monitor():
    global _detection_monitor_thread
    _detection_monitor_stop.set()
    with _detection_cache_lock:
        thread = _detection_monitor_thread
        _detection_monitor_thread = None
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=1.0)


def handle_index(handler):
    handler.send_response(200)
    handler.send_header("Content-type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.end_headers()

    html = render_dashboard_html(CAMERAS, VERSION, _SERVER_START_TIME)
    handler.wfile.write(html.encode())


def handle_detection_window(handler):
    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.end_headers()

    query = parse_qs(urlparse(handler.path).query)

    # ブラウザから送信された座標、なければ環境変数、なければデフォルト（富士山頂）
    latitude = float(query.get("lat", [os.environ.get("LATITUDE", "35.3606")])[0])
    longitude = float(query.get("lon", [os.environ.get("LONGITUDE", "138.7274")])[0])
    timezone = os.environ.get("TIMEZONE", "Asia/Tokyo")

    try:
        if get_detection_window:
            start, end = get_detection_window(latitude, longitude, timezone)
            result = {
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "enabled": os.environ.get("ENABLE_TIME_WINDOW", "false").lower() == "true",
                "latitude": latitude,
                "longitude": longitude,
            }
        else:
            result = {
                "start": "",
                "end": "",
                "enabled": False,
                "error": "meteor_detector module not available",
            }
    except Exception as e:
        result = {
            "start": "",
            "end": "",
            "enabled": False,
            "error": str(e),
        }

    handler.wfile.write(json.dumps(result).encode("utf-8"))


def handle_changelog(handler):
    handler.send_response(200)
    handler.send_header("Content-type", "text/plain; charset=utf-8")
    handler.end_headers()

    try:
        changelog_path = Path(__file__).parent / "CHANGELOG.md"
        if changelog_path.exists():
            with open(changelog_path, "r", encoding="utf-8") as f:
                handler.wfile.write(f.read().encode("utf-8"))
        else:
            handler.wfile.write(b"CHANGELOG.md not found")
    except Exception as e:
        handler.wfile.write(f"Error: {str(e)}".encode("utf-8"))


def handle_detections(handler):
    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()
    snapshot = get_detection_cache_snapshot()
    handler.wfile.write(
        json.dumps({"total": snapshot["total"], "recent": snapshot["recent"]}).encode("utf-8")
    )


def handle_detections_mtime(handler):
    if handler.path != "/detections_mtime":
        return False

    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()

    snapshot = get_detection_cache_snapshot()
    handler.wfile.write(json.dumps({"mtime": snapshot["mtime"]}).encode("utf-8"))
    return True


def handle_dashboard_stats(handler):
    if handler.path != "/dashboard_stats":
        return False

    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()

    snapshot = get_dashboard_cpu_snapshot(refresh=True)
    handler.wfile.write(json.dumps(snapshot).encode("utf-8"))
    return True


def handle_image(handler):
    try:
        parts = handler.path[7:].split("/", 1)
        if len(parts) == 2:
            camera_name, filename = parts
            image_path = Path(DETECTIONS_DIR) / camera_name / filename

            if image_path.exists() and image_path.is_file():
                file_size = image_path.stat().st_size

                if filename.endswith(".mov") or filename.endswith(".mp4"):
                    range_header = handler.headers.get("Range")

                    if range_header:
                        try:
                            byte_range = range_header.replace("bytes=", "").split("-")
                            start = int(byte_range[0]) if byte_range[0] else 0
                            end = (
                                int(byte_range[1])
                                if len(byte_range) > 1 and byte_range[1]
                                else file_size - 1
                            )

                            if start >= file_size:
                                start = 0
                            if end >= file_size:
                                end = file_size - 1

                            length = end - start + 1

                            handler.send_response(206)
                            content_type = (
                                "video/quicktime"
                                if filename.endswith(".mov")
                                else "video/mp4"
                            )
                            handler.send_header("Content-Type", content_type)
                            handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                            handler.send_header("Content-Length", str(length))
                            handler.send_header("Accept-Ranges", "bytes")
                            handler.send_header("Cache-Control", "no-cache")
                            handler.end_headers()

                            with open(image_path, "rb") as f:
                                f.seek(start)
                                chunk = f.read(length)
                                handler.wfile.write(chunk)
                        except Exception as e:
                            print(f"Range request error: {e}")
                            handler.send_response(200)
                            content_type = (
                                "video/quicktime"
                                if filename.endswith(".mov")
                                else "video/mp4"
                            )
                            handler.send_header("Content-Type", content_type)
                            handler.send_header("Content-Length", str(file_size))
                            handler.send_header("Accept-Ranges", "bytes")
                            handler.end_headers()
                            with open(image_path, "rb") as f:
                                handler.wfile.write(f.read())
                    else:
                        handler.send_response(200)
                        content_type = (
                            "video/quicktime"
                            if filename.endswith(".mov")
                            else "video/mp4"
                        )
                        handler.send_header("Content-Type", content_type)
                        handler.send_header("Content-Length", str(file_size))
                        handler.send_header("Accept-Ranges", "bytes")
                        handler.send_header("Cache-Control", "no-cache")
                        handler.end_headers()

                        with open(image_path, "rb") as f:
                            handler.wfile.write(f.read())
                else:
                    handler.send_response(200)
                    if filename.endswith(".jpg") or filename.endswith(".jpeg"):
                        handler.send_header("Content-type", "image/jpeg")
                    elif filename.endswith(".png"):
                        handler.send_header("Content-type", "image/png")
                    handler.send_header("Content-Length", str(file_size))
                    handler.end_headers()

                    with open(image_path, "rb") as f:
                        handler.wfile.write(f.read())
                return True
    except Exception as e:
        print(f"Error serving file: {e}")

    handler.send_response(404)
    handler.end_headers()
    return True


def handle_camera_stats(handler):
    if not handler.path.startswith("/camera_stats/"):
        return False

    try:
        camera_index = _parse_camera_index(handler.path)
        cam = CAMERAS[camera_index]
        target_url = _camera_url_for_proxy(cam["url"], camera_index) + "/stats"
        req = Request(target_url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=2) as response:
            payload = response.read()

        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError):
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        return True
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        return True


def handle_delete_detection(handler):
    if not handler.path.startswith("/detection/"):
        return False

    try:
        parts = handler.path[11:].split("/", 1)
        if len(parts) == 2:
            camera_name, timestamp_str = parts
            timestamp_str = unquote(timestamp_str)

            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            base_filename = f"meteor_{dt.strftime('%Y%m%d_%H%M%S')}"

            cam_dir = Path(DETECTIONS_DIR) / camera_name

            files_to_delete = [
                cam_dir / f"{base_filename}.mov",
                cam_dir / f"{base_filename}.mp4",
                cam_dir / f"{base_filename}_composite.jpg",
                cam_dir / f"{base_filename}_composite_original.jpg",
            ]

            deleted_files = []
            for file_path in files_to_delete:
                if file_path.exists():
                    file_path.unlink()
                    deleted_files.append(file_path.name)

            jsonl_file = cam_dir / "detections.jsonl"
            if jsonl_file.exists():
                target_timestamp = dt.isoformat()
                temp_file = cam_dir / "detections.jsonl.tmp"
                removed_count = 0

                with open(jsonl_file, "r", encoding="utf-8") as f_in, open(
                    temp_file, "w", encoding="utf-8"
                ) as f_out:
                    for line in f_in:
                        try:
                            d = json.loads(line)
                            if not d.get("timestamp", "").startswith(target_timestamp):
                                f_out.write(line)
                            else:
                                removed_count += 1
                        except Exception:
                            f_out.write(line)

                temp_file.replace(jsonl_file)

            labels = _load_detection_labels()
            label_key = _detection_label_key(camera_name, timestamp_str)
            if label_key in labels:
                del labels[label_key]
                _save_detection_labels(labels)
            _refresh_detection_cache(force=True)

            handler.send_response(200)
            handler.send_header("Content-type", "application/json")
            handler.end_headers()

            response = {
                "success": True,
                "deleted_files": deleted_files,
                "message": f"{len(deleted_files)}個のファイルを削除しました",
            }
            handler.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
            return True

    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        response = {
            "success": False,
            "error": str(e),
        }
        handler.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
        return True

    handler.send_response(404)
    handler.end_headers()
    return True


def handle_set_detection_label(handler):
    if handler.path != "/detection_label":
        return False

    try:
        length = int(handler.headers.get("Content-Length", "0"))
        raw_body = handler.rfile.read(length)
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}

        camera = str(payload.get("camera", "")).strip()
        detection_time = str(payload.get("time", "")).strip()
        label = str(payload.get("label", "")).strip()

        allowed_labels = {"detected", "post_detected"}
        if label not in allowed_labels:
            raise ValueError("invalid label")
        if not camera or not detection_time:
            raise ValueError("camera and time are required")

        labels = _load_detection_labels()
        key = _detection_label_key(camera, detection_time)
        if label:
            labels[key] = label
        else:
            labels.pop(key, None)
        _save_detection_labels(labels)
        _refresh_detection_cache(force=True)

        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(
            json.dumps({"success": True, "camera": camera, "time": detection_time, "label": label}).encode("utf-8")
        )
        return True
    except Exception as e:
        handler.send_response(400)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def handle_camera_stream(handler):
    if not handler.path.startswith("/camera_stream/"):
        return False

    try:
        camera_index = _parse_camera_index(handler.path)
        cam = CAMERAS[camera_index]
        target_url = _camera_url_for_proxy(cam["url"], camera_index) + "/stream"
        req = Request(target_url)
        # MJPEG は長時間接続のため、読み取りタイムアウトは長めに設定する
        with urlopen(req, timeout=_CAMERA_STREAM_TIMEOUT) as response:
            content_type = response.headers.get("Content-Type", "multipart/x-mixed-replace")
            handler.send_response(200)
            handler.send_header("Content-type", content_type)
            handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            handler.end_headers()

            while True:
                chunk = response.read(_CAMERA_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                try:
                    handler.wfile.write(chunk)
                    handler.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    # クライアント切断時は正常系として終了する
                    return True
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.end_headers()
        return True
    except (BrokenPipeError, ConnectionResetError):
        return True
    except Exception:
        handler.send_response(500)
        handler.end_headers()
        return True


def handle_camera_snapshot(handler):
    if not handler.path.startswith("/camera_snapshot/"):
        return False

    parsed = urlparse(handler.path)
    try:
        camera_index = _parse_camera_index(parsed.path)
        cam = CAMERAS[camera_index]
        target_url = _camera_url_for_proxy(cam["url"], camera_index) + "/snapshot"
        req = Request(target_url)
        with urlopen(req, timeout=5) as response:
            payload = response.read()

        query = parse_qs(parsed.query)
        should_download = query.get("download", ["0"])[0] in ("1", "true", "yes")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() else "_" for c in cam["name"]).strip("_") or f"camera{camera_index+1}"
        filename = f"snapshot_{safe_name}_{timestamp}.jpg"

        handler.send_response(200)
        handler.send_header("Content-type", "image/jpeg")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        if should_download:
            handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError):
        handler.send_response(503)
        handler.end_headers()
        return True
    except Exception:
        handler.send_response(500)
        handler.end_headers()
        return True


def handle_camera_mask(handler):
    if not handler.path.startswith("/camera_mask/"):
        return False

    try:
        camera_index = _parse_camera_index(handler.path)
        cam = CAMERAS[camera_index]
        target_url = _camera_url_for_proxy(cam["url"], camera_index) + "/update_mask"
        req = Request(target_url, method="POST")
        with urlopen(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def handle_camera_restart(handler):
    if not handler.path.startswith("/camera_restart/"):
        return False

    try:
        camera_index = _parse_camera_index(handler.path)
        cam = CAMERAS[camera_index]
        target_url = _camera_url_for_proxy(cam["url"], camera_index) + "/restart"
        req = Request(target_url, method="POST")
        with urlopen(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(202)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def handle_camera_mask_image(handler):
    if not handler.path.startswith("/camera_mask_image/"):
        return False

    parsed = urlparse(handler.path)
    try:
        camera_index = _parse_camera_index(parsed.path)
        cam = CAMERAS[camera_index]
        target_url = _camera_url_for_proxy(cam["url"], camera_index) + "/mask"
        if parsed.query:
            target_url += "?" + parsed.query
        req = Request(target_url)
        with urlopen(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(200)
        handler.send_header("Content-type", "image/png")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except HTTPError as e:
        handler.send_response(404 if e.code == 404 else 503)
        handler.end_headers()
        return True
    except (ValueError, URLError, TimeoutError):
        handler.send_response(503)
        handler.end_headers()
        return True
    except Exception:
        handler.send_response(500)
        handler.end_headers()
        return True
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
