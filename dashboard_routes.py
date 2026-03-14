"""HTTP route handlers for the dashboard."""

from datetime import datetime
import hashlib
import logging
from time import time
import json
import os
from pathlib import Path
from threading import Event, Lock, Thread
import threading
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import URLError

import dashboard_camera_handlers as camera_handlers
from dashboard_config import CAMERAS, DETECTIONS_DIR, VERSION, get_detection_window
from dashboard_templates import render_dashboard_html, render_settings_html

logger = logging.getLogger(__name__)


_IN_DOCKER = os.path.exists("/.dockerenv")
_SERVER_START_TIME = time()
_LABELS_FILENAME = "detection_labels.json"
_DETECTION_MONITOR_INTERVAL = float(os.environ.get("DETECTION_MONITOR_INTERVAL", "2.0"))
_CAMERA_MONITOR_INTERVAL = float(os.environ.get("CAMERA_MONITOR_INTERVAL", "2.0"))
_CAMERA_MONITOR_TIMEOUT = float(os.environ.get("CAMERA_MONITOR_TIMEOUT", "6.0"))
_CAMERA_RESTART_TIMEOUT = float(os.environ.get("CAMERA_RESTART_TIMEOUT", "5.0"))
_CAMERA_RESTART_COOLDOWN_SEC = float(os.environ.get("CAMERA_RESTART_COOLDOWN_SEC", "120"))
_CAMERA_MONITOR_ENABLED = os.environ.get("CAMERA_MONITOR_ENABLED", "true").lower() in ("1", "true", "yes")
_CAMERA_MONITOR_FAIL_THRESHOLD = int(os.environ.get("CAMERA_MONITOR_FAIL_THRESHOLD", "12"))
_detection_cache_lock = Lock()
_detection_cache = {
    "detections_dir": "",
    "mtime": 0.0,
    "total": 0,
    "recent": [],
}
_detection_monitor_stop = Event()
_detection_monitor_thread = None
_camera_monitor_lock = Lock()
_camera_monitor_stop = Event()
_camera_monitor_thread = None
_camera_monitor_state = {}
_dashboard_cpu_lock = Lock()
_dashboard_cpu = {
    "cpu_percent": 0.0,
    "last_total": None,
    "last_idle": None,
}


def _read_system_cpu_totals():
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            first = f.readline().strip()
        if not first.startswith("cpu "):
            return None, None
        parts = first.split()[1:]
        if len(parts) < 4:
            return None, None
        values = [int(v) for v in parts]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        return total, idle
    except Exception:
        return None, None


def _sample_dashboard_cpu():
    now_total, now_idle = _read_system_cpu_totals()
    if now_total is None or now_idle is None:
        try:
            load1, _, _ = os.getloadavg()
            cpu_count = max(1, os.cpu_count() or 1)
            approx = max(0.0, min(100.0, (load1 / cpu_count) * 100.0))
            with _dashboard_cpu_lock:
                _dashboard_cpu["cpu_percent"] = approx
        except Exception:
            pass
        return
    with _dashboard_cpu_lock:
        prev_total = _dashboard_cpu["last_total"]
        prev_idle = _dashboard_cpu["last_idle"]
        if prev_total is not None and prev_idle is not None:
            total_delta = now_total - prev_total
            idle_delta = now_idle - prev_idle
            if total_delta > 0:
                busy = 1.0 - (idle_delta / total_delta)
                _dashboard_cpu["cpu_percent"] = max(0.0, min(100.0, busy * 100.0))
        _dashboard_cpu["last_total"] = now_total
        _dashboard_cpu["last_idle"] = now_idle


def get_dashboard_cpu_snapshot(refresh=True):
    if refresh:
        _sample_dashboard_cpu()
    with _dashboard_cpu_lock:
        return {
            "cpu_percent": round(float(_dashboard_cpu["cpu_percent"]), 1),
        }


def _parse_camera_index(path):
    return camera_handlers.parse_camera_index(path, len(CAMERAS))


def _camera_url_for_proxy(raw_url, camera_index=None):
    return camera_handlers.camera_url_for_proxy(raw_url, _IN_DOCKER, camera_index)


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


def _make_detection_id(camera_name, record):
    source = {
        "camera": camera_name,
        "timestamp": record.get("timestamp", ""),
        "start_time": record.get("start_time", ""),
        "end_time": record.get("end_time", ""),
        "start_point": record.get("start_point", ""),
        "end_point": record.get("end_point", ""),
    }
    digest = hashlib.sha1(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"det_{digest[:20]}"


def _normalize_detection_id(camera_name, record):
    value = str(record.get("id", "")).strip()
    return value or _make_detection_id(camera_name, record)


def _safe_datetime_from_record(record):
    timestamp_str = str(record.get("timestamp", "")).strip()
    if not timestamp_str:
        return None
    try:
        return datetime.fromisoformat(timestamp_str)
    except Exception:
        return None


def _legacy_base_name_from_record(record):
    dt = _safe_datetime_from_record(record)
    if dt is None:
        return ""
    return f"meteor_{dt.strftime('%Y%m%d_%H%M%S')}"


def _normalize_relative_asset_path(camera_name, path_value):
    path_str = str(path_value or "").strip()
    if not path_str:
        return ""
    if "/" in path_str:
        return path_str
    return f"{camera_name}/{path_str}"


def _resolve_asset_path(cam_dir, camera_name, record, field_name, legacy_suffix):
    explicit_rel = _normalize_relative_asset_path(camera_name, record.get(field_name, ""))
    if explicit_rel:
        explicit_path = Path(DETECTIONS_DIR) / explicit_rel
        if explicit_path.exists():
            return explicit_rel

    base_name = str(record.get("base_name", "")).strip() or _legacy_base_name_from_record(record)
    if not base_name:
        return ""

    rel = f"{camera_name}/{base_name}{legacy_suffix}"
    abs_path = cam_dir / f"{base_name}{legacy_suffix}"
    return rel if abs_path.exists() else ""


def _resolve_detection_assets(cam_dir, camera_name, record):
    clip_rel = ""
    for field_name, suffix in (("clip_path", ".mp4"), ("clip_path", ".mov")):
        candidate = _resolve_asset_path(cam_dir, camera_name, record, field_name, suffix)
        if candidate:
            clip_rel = candidate
            break

    image_rel = _resolve_asset_path(cam_dir, camera_name, record, "image_path", "_composite.jpg")
    original_rel = _resolve_asset_path(
        cam_dir,
        camera_name,
        record,
        "composite_original_path",
        "_composite_original.jpg",
    )
    return clip_rel, image_rel, original_rel


def _normalize_extra_asset_paths(camera_name, values):
    normalized = []
    for value in values or []:
        rel = _normalize_relative_asset_path(camera_name, value)
        if rel:
            normalized.append(rel)
    return normalized


def _normalize_detection_record(camera_name, cam_dir, record):
    normalized = dict(record)
    detection_id = _normalize_detection_id(camera_name, normalized)
    dt = _safe_datetime_from_record(normalized)
    display_time = (
        dt.isoformat(sep=" ")[:19]
        if dt
        else str(normalized.get("timestamp", "")).replace("T", " ")[:19]
    )
    clip_rel, image_rel, original_rel = _resolve_detection_assets(cam_dir, camera_name, normalized)
    normalized["id"] = detection_id
    normalized["time"] = display_time
    normalized["camera"] = camera_name
    normalized["camera_display"] = _camera_display_name(camera_name)
    normalized["clip_path"] = clip_rel
    normalized["image_path"] = image_rel
    normalized["composite_original_path"] = original_rel
    normalized["alternate_clip_paths"] = _normalize_extra_asset_paths(
        camera_name, normalized.get("alternate_clip_paths", [])
    )
    normalized["legacy_label_key"] = _detection_label_key(camera_name, display_time) if display_time else ""
    return normalized


def _iter_camera_detection_records(camera_name):
    cam_dir = Path(DETECTIONS_DIR) / camera_name
    jsonl_file = cam_dir / "detections.jsonl"
    records = []
    if not jsonl_file.exists():
        return records, cam_dir, jsonl_file

    with open(jsonl_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                records.append((line, raw, _normalize_detection_record(camera_name, cam_dir, raw)))
            except Exception:
                logger.exception(
                    "Failed to parse detection entry for camera=%s line=%r",
                    camera_name,
                    line[:200],
                )

    return records, cam_dir, jsonl_file


def _find_detection_record(camera_name, detection_id):
    records, cam_dir, jsonl_file = _iter_camera_detection_records(camera_name)
    for index, (line, raw, normalized) in enumerate(records):
        if normalized["id"] == detection_id:
            return {
                "records": records,
                "cam_dir": cam_dir,
                "jsonl_file": jsonl_file,
                "index": index,
                "line": line,
                "raw": raw,
                "normalized": normalized,
            }
    raise FileNotFoundError(f"detection id not found: {camera_name} {detection_id}")


def _records_referencing_relpath(records, relpath, *, exclude_id=None):
    target = str(relpath or "").strip()
    if not target:
        return 0

    count = 0
    for _, _, normalized in records:
        if exclude_id and normalized["id"] == exclude_id:
            continue
        for key in ("clip_path", "image_path", "composite_original_path"):
            if normalized.get(key) == target:
                count += 1
                break
        else:
            if target in normalized.get("alternate_clip_paths", []):
                count += 1
    return count


def _delete_detection_assets_if_unreferenced(records, normalized):
    deleted_files = []
    for key in ("clip_path", "image_path", "composite_original_path"):
        relpath = normalized.get(key, "")
        if not relpath:
            continue
        if _records_referencing_relpath(records, relpath, exclude_id=normalized["id"]) > 0:
            continue
        abs_path = Path(DETECTIONS_DIR) / relpath
        if abs_path.exists() and abs_path.is_file():
            abs_path.unlink()
            deleted_files.append(abs_path.name)
    for relpath in normalized.get("alternate_clip_paths", []):
        if _records_referencing_relpath(records, relpath, exclude_id=normalized["id"]) > 0:
            continue
        abs_path = Path(DETECTIONS_DIR) / relpath
        if abs_path.exists() and abs_path.is_file():
            abs_path.unlink()
            deleted_files.append(abs_path.name)
    return deleted_files


def _normalize_detection_label(label):
    value = str(label or "").strip()
    if value == "post_detected":
        return "post_detected"
    return "detected"


def _camera_display_name(camera_name):
    for cam in CAMERAS:
        if cam.get("name") == camera_name:
            return cam.get("display_name") or camera_name
    return camera_name


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
    camera_summaries = []

    try:
        for cam_dir in Path(DETECTIONS_DIR).iterdir():
            if cam_dir.is_dir():
                jsonl_file = cam_dir / "detections.jsonl"
                if jsonl_file.exists():
                    processed_lines = 0
                    missing_composite = 0
                    missing_original = 0
                    missing_video = 0
                    camera_errors = 0
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                d = json.loads(line)
                                normalized = _normalize_detection_record(cam_dir.name, cam_dir, d)
                                mp4_path = normalized["clip_path"]
                                composite_path = normalized["image_path"]
                                composite_orig_path = normalized["composite_original_path"]
                                image_path = composite_path or composite_orig_path
                                if not composite_path:
                                    missing_composite += 1
                                if not composite_orig_path:
                                    missing_original += 1
                                if not mp4_path:
                                    missing_video += 1

                                total += 1
                                processed_lines += 1
                                display_time = normalized["time"]
                                label_key = normalized["legacy_label_key"]
                                detections.append(
                                    {
                                        "id": normalized["id"],
                                        "time": display_time,
                                        "camera": cam_dir.name,
                                        "camera_display": _camera_display_name(cam_dir.name),
                                        "confidence": f"{d.get('confidence', 0):.0%}",
                                        "image": image_path,
                                        "mp4": mp4_path,
                                        "composite_original": composite_orig_path,
                                        "label": _normalize_detection_label(
                                            labels.get(normalized["id"], labels.get(label_key, ""))
                                        ),
                                    }
                                )
                            except Exception:
                                camera_errors += 1
                                logger.exception(
                                    "Failed to parse detection entry: camera=%s line=%r",
                                    cam_dir.name,
                                    line.strip()[:200],
                                )
                    camera_summaries.append(
                        {
                            "camera": cam_dir.name,
                            "processed": processed_lines,
                            "missing_composite": missing_composite,
                            "missing_original": missing_original,
                            "missing_video": missing_video,
                            "errors": camera_errors,
                        }
                    )
                else:
                    camera_summaries.append(
                        {
                            "camera": cam_dir.name,
                            "processed": 0,
                            "missing_composite": 0,
                            "missing_original": 0,
                            "missing_video": 0,
                            "errors": 0,
                            "note": "detections.jsonl not found",
                        }
                    )
    except Exception:
        logger.exception("Failed to build detections payload: detections_dir=%s", DETECTIONS_DIR)

    detections.sort(key=lambda x: x["time"], reverse=True)
    logger.info(
        "Detections payload rebuilt: detections_dir=%s total=%d recent=%d cameras=%s",
        DETECTIONS_DIR,
        total,
        len(detections),
        camera_summaries,
    )
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

    logger.info(
        "Refreshing detection cache: force=%s current_dir=%s previous_dir=%s latest_mtime=%s previous_mtime=%s",
        force,
        current_dir,
        cache_dir,
        latest_mtime,
        cache_mtime,
    )
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


def _camera_restart_target(camera_index):
    cam = CAMERAS[camera_index]
    return _camera_url_for_proxy(cam["url"], camera_index) + "/restart"


def _camera_stats_target(camera_index):
    cam = CAMERAS[camera_index]
    return _camera_url_for_proxy(cam["url"], camera_index) + "/stats"


def _camera_apply_settings_target(camera_index):
    cam = CAMERAS[camera_index]
    return _camera_url_for_proxy(cam["url"], camera_index) + "/apply_settings"


def _camera_monitor_default_snapshot(camera_index):
    now_ts = time()
    cam_name = CAMERAS[camera_index]["name"] if camera_index < len(CAMERAS) else f"camera{camera_index+1}"
    return {
        "camera": cam_name,
        "stream_alive": False,
        "time_since_last_frame": None,
        "runtime_fps": 0.0,
        "detections": 0,
        "is_detecting": False,
        "mask_active": False,
        "monitor_enabled": _CAMERA_MONITOR_ENABLED,
        "monitor_checked_at": now_ts,
        "monitor_error": "not initialized",
        "monitor_stop_reason": "unknown",
        "monitor_last_restart_at": 0.0,
        "monitor_restart_count": 0,
        "monitor_stats_failures": 0,
        "monitor_fail_threshold": max(1, _CAMERA_MONITOR_FAIL_THRESHOLD),
    }


def _classify_stop_reason(stats):
    stream_alive = stats.get("stream_alive", False) is not False
    stuck = stats.get("stuck", False) is True
    if (not stream_alive) and stuck:
        return "timeout_and_stuck"
    if not stream_alive:
        return "timeout"
    if stuck:
        return "stuck"
    return "none"


def _request_camera_restart(camera_index):
    req = Request(_camera_restart_target(camera_index), method="POST")
    with urlopen(req, timeout=_CAMERA_RESTART_TIMEOUT) as response:
        payload = response.read()
    data = json.loads(payload.decode("utf-8")) if payload else {}
    return bool(data.get("success", False)), data


def _refresh_camera_monitor_once():
    now_ts = time()
    for camera_index in range(len(CAMERAS)):
        with _camera_monitor_lock:
            state = _camera_monitor_state.get(camera_index, _camera_monitor_default_snapshot(camera_index))
            last_restart_at = float(state.get("monitor_last_restart_at", 0.0) or 0.0)
            restart_count = int(state.get("monitor_restart_count", 0) or 0)
            stats_failures = int(state.get("monitor_stats_failures", 0) or 0)

        monitor_error = ""
        restart_triggered = False
        stop_reason = "none"
        stats = None

        try:
            req = Request(_camera_stats_target(camera_index), headers={"Accept": "application/json"})
            with urlopen(req, timeout=_CAMERA_MONITOR_TIMEOUT) as response:
                payload = response.read()
            stats = json.loads(payload.decode("utf-8")) if payload else {}
            if not isinstance(stats, dict):
                raise ValueError("camera stats payload is not object")
            stats_failures = 0
            stop_reason = _classify_stop_reason(stats)
        except Exception as e:
            monitor_error = str(e)
            stats_failures += 1
            threshold = max(1, _CAMERA_MONITOR_FAIL_THRESHOLD)
            if stats_failures < threshold:
                # 一時的な取得失敗では直前スナップショットを維持して誤検知を避ける
                stats = dict(state)
                stop_reason = "stats_unreachable_transient"
            else:
                stats = _camera_monitor_default_snapshot(camera_index)
                stop_reason = "stats_unreachable"

        should_restart = _CAMERA_MONITOR_ENABLED and (stop_reason in ("timeout", "stuck", "timeout_and_stuck", "stats_unreachable"))
        restart_allowed = (now_ts - last_restart_at) >= _CAMERA_RESTART_COOLDOWN_SEC
        if should_restart and restart_allowed:
            try:
                ok, _ = _request_camera_restart(camera_index)
                restart_triggered = ok
                if ok:
                    last_restart_at = time()
                    restart_count += 1
            except Exception as e:
                monitor_error = monitor_error or str(e)

        stats["monitor_enabled"] = _CAMERA_MONITOR_ENABLED
        stats["monitor_checked_at"] = now_ts
        stats["monitor_error"] = monitor_error
        stats["monitor_stop_reason"] = stop_reason
        stats["monitor_last_restart_at"] = last_restart_at
        stats["monitor_restart_count"] = restart_count
        stats["monitor_stats_failures"] = stats_failures
        stats["monitor_fail_threshold"] = max(1, _CAMERA_MONITOR_FAIL_THRESHOLD)
        stats["monitor_restart_triggered"] = restart_triggered

        with _camera_monitor_lock:
            _camera_monitor_state[camera_index] = stats


def _camera_monitor_loop():
    while not _camera_monitor_stop.wait(_CAMERA_MONITOR_INTERVAL):
        try:
            _refresh_camera_monitor_once()
        except Exception:
            pass


def start_camera_monitor():
    global _camera_monitor_thread
    with _camera_monitor_lock:
        if _camera_monitor_thread and _camera_monitor_thread.is_alive():
            return
        _camera_monitor_state.clear()
        for camera_index in range(len(CAMERAS)):
            _camera_monitor_state[camera_index] = _camera_monitor_default_snapshot(camera_index)
    _refresh_camera_monitor_once()
    _camera_monitor_stop.clear()
    thread = Thread(target=_camera_monitor_loop, name="camera-monitor", daemon=True)
    thread.start()
    with _camera_monitor_lock:
        _camera_monitor_thread = thread


def stop_camera_monitor():
    global _camera_monitor_thread
    _camera_monitor_stop.set()
    with _camera_monitor_lock:
        thread = _camera_monitor_thread
        _camera_monitor_thread = None
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=1.0)


def get_camera_monitor_snapshot(camera_index):
    with _camera_monitor_lock:
        snapshot = _camera_monitor_state.get(camera_index)
    if snapshot is None:
        snapshot = _camera_monitor_default_snapshot(camera_index)
    return dict(snapshot)


def start_detection_monitor():
    global _detection_monitor_thread
    with _detection_cache_lock:
        if _detection_monitor_thread and _detection_monitor_thread.is_alive():
            return
    _refresh_detection_cache(force=True)
    with _dashboard_cpu_lock:
        _dashboard_cpu["last_total"] = None
        _dashboard_cpu["last_idle"] = None
        _dashboard_cpu["cpu_percent"] = 0.0
    _sample_dashboard_cpu()
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


def handle_settings_page(handler):
    if handler.path != "/settings":
        return False

    handler.send_response(200)
    handler.send_header("Content-type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.end_headers()
    html = render_settings_html(CAMERAS, VERSION)
    handler.wfile.write(html.encode("utf-8"))
    return True


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
            camera_name = unquote(parts[0])
            filename = unquote(parts[1])
            image_path = Path(DETECTIONS_DIR) / camera_name / filename
            logger.info(
                "Image request: raw_path=%s camera=%s filename=%s resolved=%s exists=%s",
                handler.path,
                camera_name,
                filename,
                image_path,
                image_path.exists(),
            )

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
                            logger.exception(
                                "Range request error: path=%s range=%s",
                                image_path,
                                range_header,
                            )
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
            logger.warning(
                "Image request resolved to missing file: raw_path=%s resolved=%s is_file=%s detections_dir=%s",
                handler.path,
                image_path,
                image_path.is_file(),
                DETECTIONS_DIR,
            )
        else:
            logger.warning("Image request path format invalid: raw_path=%s parts=%s", handler.path, parts)
    except Exception as e:
        logger.exception("Error serving file: raw_path=%s", handler.path)

    handler.send_response(404)
    handler.end_headers()
    return True


def handle_camera_stats(handler):
    if not handler.path.startswith("/camera_stats/"):
        return False

    try:
        camera_index = _parse_camera_index(handler.path)
        payload = get_camera_monitor_snapshot(camera_index)

        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(json.dumps(payload).encode("utf-8"))
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
            camera_name = unquote(parts[0])
            detection_id = unquote(parts[1])
            match = _find_detection_record(camera_name, detection_id)
            records = match["records"]
            cam_dir = match["cam_dir"]
            jsonl_file = match["jsonl_file"]
            normalized = match["normalized"]

            deleted_files = _delete_detection_assets_if_unreferenced(records, normalized)
            if jsonl_file.exists():
                temp_file = cam_dir / "detections.jsonl.tmp"

                with open(jsonl_file, "r", encoding="utf-8") as f_in, open(
                    temp_file, "w", encoding="utf-8"
                ) as f_out:
                    for line in f_in:
                        try:
                            d = json.loads(line)
                            if _normalize_detection_id(camera_name, d) != detection_id:
                                f_out.write(line)
                        except Exception:
                            f_out.write(line)

                temp_file.replace(jsonl_file)

            labels = _load_detection_labels()
            labels.pop(detection_id, None)
            legacy_label_key = normalized.get("legacy_label_key", "")
            if legacy_label_key:
                labels.pop(legacy_label_key, None)
            _save_detection_labels(labels)
            _refresh_detection_cache(force=True)

            handler.send_response(200)
            handler.send_header("Content-type", "application/json")
            handler.end_headers()

            response = {
                "success": True,
                "id": detection_id,
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
        detection_id = str(payload.get("id", "")).strip()
        label = str(payload.get("label", "")).strip()

        allowed_labels = {"detected", "post_detected"}
        if label not in allowed_labels:
            raise ValueError("invalid label")
        if not camera or not detection_id:
            raise ValueError("camera and id are required")

        labels = _load_detection_labels()
        match = _find_detection_record(camera, detection_id)
        key = detection_id
        if label:
            labels[key] = label
        else:
            labels.pop(key, None)
        legacy_label_key = match["normalized"].get("legacy_label_key", "")
        if legacy_label_key:
            labels.pop(legacy_label_key, None)
        _save_detection_labels(labels)
        _refresh_detection_cache(force=True)

        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(
            json.dumps({"success": True, "camera": camera, "id": detection_id, "label": label}).encode("utf-8")
        )
        return True
    except Exception as e:
        handler.send_response(400)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def handle_camera_snapshot(handler):
    return camera_handlers.handle_camera_snapshot(
        handler,
        CAMERAS,
        _IN_DOCKER,
        _parse_camera_index,
        Request,
        urlopen,
    )


def handle_camera_mask(handler):
    return camera_handlers.handle_camera_mask(
        handler,
        CAMERAS,
        _IN_DOCKER,
        _parse_camera_index,
        Request,
        urlopen,
    )


def handle_camera_mask_confirm(handler):
    return camera_handlers.handle_camera_mask_confirm(
        handler,
        CAMERAS,
        _IN_DOCKER,
        _parse_camera_index,
        Request,
        urlopen,
    )


def handle_camera_mask_discard(handler):
    return camera_handlers.handle_camera_mask_discard(
        handler,
        CAMERAS,
        _IN_DOCKER,
        _parse_camera_index,
        Request,
        urlopen,
    )


def handle_camera_restart(handler):
    return camera_handlers.handle_camera_restart(
        handler,
        CAMERAS,
        _IN_DOCKER,
        _parse_camera_index,
        Request,
        urlopen,
    )


def handle_camera_mask_image(handler):
    return camera_handlers.handle_camera_mask_image(
        handler,
        CAMERAS,
        _IN_DOCKER,
        _parse_camera_index,
        Request,
        urlopen,
    )


def handle_camera_settings_current(handler):
    return camera_handlers.handle_camera_settings_current(
        handler,
        CAMERAS,
        _camera_stats_target,
        Request,
        urlopen,
    )


def handle_camera_settings_apply_all(handler):
    return camera_handlers.handle_camera_settings_apply_all(
        handler,
        CAMERAS,
        _camera_apply_settings_target,
        Request,
        urlopen,
    )


def handle_bulk_delete_non_meteor(handler):
    parsed_path = urlparse(handler.path).path
    prefix = "/bulk_delete_non_meteor/"
    if not parsed_path.startswith(prefix):
        return False

    try:
        camera_part = parsed_path[len(prefix):]
        if (not camera_part) or ("/" in camera_part):
            raise ValueError("invalid path")
        camera_name = unquote(camera_part)

        labels = _load_detection_labels()
        cam_dir = Path(DETECTIONS_DIR) / camera_name
        if not cam_dir.is_dir():
            raise ValueError(f"camera directory not found: {camera_name}")

        deleted_count = 0
        deleted_detections = []

        jsonl_file = cam_dir / "detections.jsonl"
        if jsonl_file.exists():
            records, _, _ = _iter_camera_detection_records(camera_name)
            records_by_id = {normalized["id"]: (line, raw, normalized) for line, raw, normalized in records}
            ids_to_delete = []
            for _, _, normalized in records:
                label = _normalize_detection_label(
                    labels.get(normalized["id"], labels.get(normalized.get("legacy_label_key", ""), ""))
                )
                if label == "post_detected":
                    ids_to_delete.append(normalized["id"])
            remaining_records = [entry for entry in records if entry[2]["id"] not in ids_to_delete]

            temp_file = cam_dir / "detections.jsonl.tmp"
            with open(jsonl_file, "r", encoding="utf-8") as f_in, open(
                temp_file, "w", encoding="utf-8"
            ) as f_out:
                for line in f_in:
                    try:
                        d = json.loads(line)
                        detection_id = _normalize_detection_id(camera_name, d)
                        if detection_id in ids_to_delete:
                            normalized = records_by_id[detection_id][2]
                            _delete_detection_assets_if_unreferenced(remaining_records, normalized)
                            labels.pop(detection_id, None)
                            legacy_label_key = normalized.get("legacy_label_key", "")
                            if legacy_label_key:
                                labels.pop(legacy_label_key, None)
                            deleted_count += 1
                            deleted_detections.append(normalized["time"])
                        else:
                            f_out.write(line)
                    except Exception:
                        f_out.write(line)

            temp_file.replace(jsonl_file)

        _save_detection_labels(labels)
        _refresh_detection_cache(force=True)

        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()

        response = {
            "success": True,
            "deleted_count": deleted_count,
            "deleted_detections": deleted_detections,
            "message": f"{camera_name}: {deleted_count}件の「それ以外」を削除しました",
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
