"""HTTP route handlers for the dashboard."""

from datetime import datetime
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import URLError

from dashboard_config import CAMERAS, DETECTIONS_DIR, VERSION, get_detection_window
from dashboard_templates import render_dashboard_html


_IN_DOCKER = os.path.exists("/.dockerenv")


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


def handle_index(handler):
    handler.send_response(200)
    handler.send_header("Content-type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.end_headers()

    html = render_dashboard_html(CAMERAS, VERSION)
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

    detections = []
    total = 0

    try:
        for cam_dir in Path(DETECTIONS_DIR).iterdir():
            if cam_dir.is_dir():
                jsonl_file = cam_dir / "detections.jsonl"
                if jsonl_file.exists():
                    with open(jsonl_file, "r") as f:
                        for line in f:
                            try:
                                d = json.loads(line)
                                timestamp_str = d.get("timestamp", "")
                                if timestamp_str:
                                    dt = datetime.fromisoformat(timestamp_str)
                                    base_filename = f"meteor_{dt.strftime('%Y%m%d_%H%M%S')}"
                                    mp4_path = f"{cam_dir.name}/{base_filename}.mp4"
                                    composite_path = f"{cam_dir.name}/{base_filename}_composite.jpg"
                                    composite_orig_path = f"{cam_dir.name}/{base_filename}_composite_original.jpg"
                                else:
                                    mp4_path = ""
                                    composite_path = ""
                                    composite_orig_path = ""

                                total += 1
                                detections.append(
                                    {
                                        "time": timestamp_str[:19].replace("T", " "),
                                        "camera": cam_dir.name,
                                        "confidence": f"{d.get('confidence', 0):.0%}",
                                        "image": composite_path,
                                        "mp4": mp4_path,
                                        "composite_original": composite_orig_path,
                                    }
                                )
                            except Exception:
                                pass
    except Exception:
        pass

    detections.sort(key=lambda x: x["time"], reverse=True)
    result = {
        "total": total,
        "recent": detections,
    }
    handler.wfile.write(json.dumps(result).encode())


def handle_detections_mtime(handler):
    if handler.path != "/detections_mtime":
        return False

    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()

    latest_mtime = 0.0
    try:
        for cam_dir in Path(DETECTIONS_DIR).iterdir():
            if cam_dir.is_dir():
                jsonl_file = cam_dir / "detections.jsonl"
                if jsonl_file.exists():
                    mtime = jsonl_file.stat().st_mtime
                    if mtime > latest_mtime:
                        latest_mtime = mtime
    except Exception:
        pass

    handler.wfile.write(json.dumps({"mtime": latest_mtime}).encode("utf-8"))
    return True


def handle_image(handler):
    try:
        parts = handler.path[7:].split("/", 1)
        if len(parts) == 2:
            camera_name, filename = parts
            image_path = Path(DETECTIONS_DIR) / camera_name / filename

            if image_path.exists() and image_path.is_file():
                file_size = image_path.stat().st_size

                if filename.endswith(".mp4"):
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
                            handler.send_header("Content-Type", "video/mp4")
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
                            handler.send_header("Content-Type", "video/mp4")
                            handler.send_header("Content-Length", str(file_size))
                            handler.send_header("Accept-Ranges", "bytes")
                            handler.end_headers()
                            with open(image_path, "rb") as f:
                                handler.wfile.write(f.read())
                    else:
                        handler.send_response(200)
                        handler.send_header("Content-Type", "video/mp4")
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
        camera_index = int(handler.path.split("/")[-1])
        if camera_index < 0 or camera_index >= len(CAMERAS):
            raise ValueError("camera index out of range")
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
    except (ValueError, URLError, TimeoutError) as e:
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


def handle_camera_stream(handler):
    if not handler.path.startswith("/camera_stream/"):
        return False

    try:
        camera_index = int(handler.path.split("/")[-1])
        if camera_index < 0 or camera_index >= len(CAMERAS):
            raise ValueError("camera index out of range")
        cam = CAMERAS[camera_index]
        target_url = _camera_url_for_proxy(cam["url"], camera_index) + "/stream"
        req = Request(target_url)
        with urlopen(req, timeout=5) as response:
            content_type = response.headers.get("Content-Type", "multipart/x-mixed-replace")
            handler.send_response(200)
            handler.send_header("Content-type", content_type)
            handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            handler.end_headers()

            while True:
                chunk = response.read(1024 * 16)
                if not chunk:
                    break
                handler.wfile.write(chunk)
        return True
    except (ValueError, URLError, TimeoutError) as e:
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
        camera_index = int(handler.path.split("/")[-1])
        if camera_index < 0 or camera_index >= len(CAMERAS):
            raise ValueError("camera index out of range")
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
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
