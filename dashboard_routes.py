"""HTTP route handlers for the dashboard."""

from datetime import date, datetime, timedelta
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
from zoneinfo import ZoneInfo

import dashboard_camera_handlers as camera_handlers
from dashboard_config import CAMERAS, DETECTIONS_DIR, GO2RTC_API_URL, VERSION, get_detection_window

try:
    from astro_utils import get_detection_window_for_date as _get_detection_window_for_date
except ImportError:
    _get_detection_window_for_date = None
from dashboard_templates import render_dashboard_html, render_settings_html
import detection_store

logger = logging.getLogger(__name__)


_IN_DOCKER = os.path.exists("/.dockerenv")
_SERVER_START_TIME = time()
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
    digest = hashlib.sha1(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8"), usedforsecurity=False).hexdigest()
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


def _db_path():
    return str(Path(DETECTIONS_DIR) / "detections.db")


def _build_detections_payload():
    detections = []
    total = 0
    db = _db_path()

    try:
        rows = detection_store.query_detections(db)
        for row in rows:
            mp4_path = row.get("clip_path", "")
            composite_path = row.get("image_path", "")
            composite_orig_path = row.get("composite_original_path", "")
            image_path = composite_path or composite_orig_path
            camera_name = row["camera"]
            display_time = row["timestamp"].replace("T", " ")[:19]
            confidence_raw = row.get("confidence")
            if confidence_raw is not None:
                confidence_str = f"{float(confidence_raw):.0%}"
            else:
                confidence_str = "0%"
            total += 1
            detections.append(
                {
                    "id": row["id"],
                    "time": display_time,
                    "camera": camera_name,
                    "camera_display": _camera_display_name(camera_name),
                    "confidence": confidence_str,
                    "image": image_path,
                    "mp4": mp4_path,
                    "composite_original": composite_orig_path,
                    "label": _normalize_detection_label(row.get("label", "")),
                }
            )
    except Exception:
        logger.exception("Failed to query detections from SQLite: db=%s", db)

    try:
        for cam_dir in Path(DETECTIONS_DIR).iterdir():
            if not cam_dir.is_dir():
                continue
            manual_root = cam_dir / "manual_recordings"
            if not (manual_root.exists() and manual_root.is_dir()):
                continue
            for clip_path in sorted(manual_root.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    stat = clip_path.stat()
                    timestamp = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    relpath = clip_path.relative_to(Path(DETECTIONS_DIR)).as_posix()
                    thumb_path = clip_path.with_suffix(".jpg")
                    thumb_relpath = (
                        thumb_path.relative_to(Path(DETECTIONS_DIR)).as_posix()
                        if thumb_path.exists()
                        else ""
                    )
                    total += 1
                    detections.append(
                        {
                            "id": f"manual_{cam_dir.name}_{clip_path.stem}",
                            "time": timestamp,
                            "camera": cam_dir.name,
                            "camera_display": _camera_display_name(cam_dir.name),
                            "confidence": "手動録画",
                            "image": thumb_relpath,
                            "mp4": relpath,
                            "composite_original": "",
                            "label": "",
                            "source_type": "manual_recording",
                        }
                    )
                except Exception:
                    logger.exception("Failed to parse manual recording entry: clip=%s", clip_path)
    except Exception:
        logger.exception("Failed to scan manual recordings: detections_dir=%s", DETECTIONS_DIR)

    detections.sort(key=lambda x: x["time"], reverse=True)
    logger.info(
        "Detections payload rebuilt: detections_dir=%s total=%d recent=%d",
        DETECTIONS_DIR,
        total,
        len(detections),
    )
    return {"total": total, "recent": detections}


def _refresh_detection_cache(force=False):
    current_dir = str(Path(DETECTIONS_DIR).resolve())
    db = _db_path()

    try:
        detection_store.init_db(db)
        for cam_dir in Path(DETECTIONS_DIR).iterdir():
            if cam_dir.is_dir():
                detection_store.sync_camera_from_jsonl(
                    cam_dir.name, cam_dir, db, _normalize_detection_record
                )
    except Exception:
        logger.exception("Failed to sync JSONL to SQLite: detections_dir=%s", DETECTIONS_DIR)

    payload = _build_detections_payload()
    with _detection_cache_lock:
        _detection_cache["detections_dir"] = current_dir
        _detection_cache["total"] = payload["total"]
        _detection_cache["recent"] = payload["recent"]


def get_detection_cache_snapshot():
    _refresh_detection_cache(force=False)
    with _detection_cache_lock:
        return {
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


def _camera_recording_status_target(camera_index):
    cam = CAMERAS[camera_index]
    return _camera_url_for_proxy(cam["url"], camera_index) + "/recording/status"


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

    db = Path(DETECTIONS_DIR) / "detections.db"
    try:
        mtime = db.stat().st_mtime if db.exists() else 0
    except OSError:
        mtime = 0
    handler.wfile.write(json.dumps({"mtime": mtime}).encode("utf-8"))
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
            detections_root = Path(DETECTIONS_DIR).resolve()
            if detections_root not in image_path.resolve().parents:
                logger.warning(
                    "Image request path escapes detections dir: raw_path=%s resolved=%s",
                    handler.path,
                    image_path.resolve(),
                )
                handler.send_response(404)
                handler.end_headers()
                return True
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
            db = _db_path()
            detection_store.init_db(db)
            row = detection_store.get_detection_by_id(db, detection_id)
            if row is None:
                raise FileNotFoundError(f"detection id not found: {camera_name} {detection_id}")

            detections_root = Path(DETECTIONS_DIR).resolve()
            deleted_files = []
            for key in ("clip_path", "image_path", "composite_original_path"):
                relpath = row.get(key, "")
                if not relpath:
                    continue
                if detection_store.count_asset_references(db, relpath, exclude_id=detection_id) > 0:
                    continue
                abs_path = (detections_root / relpath).resolve()
                if detections_root not in abs_path.parents:
                    continue
                if abs_path.exists() and abs_path.is_file():
                    abs_path.unlink()
                    deleted_files.append(abs_path.name)
            for relpath in row.get("alternate_clip_paths", []):
                if detection_store.count_asset_references(db, relpath, exclude_id=detection_id) > 0:
                    continue
                abs_path = (detections_root / relpath).resolve()
                if detections_root not in abs_path.parents:
                    continue
                if abs_path.exists() and abs_path.is_file():
                    abs_path.unlink()
                    deleted_files.append(abs_path.name)

            detection_store.soft_delete(db, detection_id)
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


def handle_delete_manual_recording(handler):
    if not handler.path.startswith("/manual_recording/"):
        return False

    try:
        relpath = Path(unquote(handler.path[len("/manual_recording/"):]))
        if relpath.suffix.lower() != ".mp4":
            raise ValueError("manual recording must be mp4")
        if "manual_recordings" not in relpath.parts:
            raise ValueError("path is not manual recording")
        abs_path = (Path(DETECTIONS_DIR) / relpath).resolve()
        detections_root = Path(DETECTIONS_DIR).resolve()
        if detections_root not in abs_path.parents:
            raise ValueError("path escapes detections dir")
        if not abs_path.exists() or not abs_path.is_file():
            raise FileNotFoundError(str(relpath))

        abs_path.unlink()
        thumb_path = abs_path.with_suffix(".jpg")
        if thumb_path.exists() and thumb_path.is_file():
            thumb_path.unlink()
        _refresh_detection_cache(force=True)

        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(
            json.dumps(
                {
                    "success": True,
                    "path": relpath.as_posix(),
                    "message": "手動録画を削除しました",
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )
        return True
    except Exception as e:
        handler.send_response(400 if isinstance(e, ValueError) else 404 if isinstance(e, FileNotFoundError) else 500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
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

        db = _db_path()
        detection_store.init_db(db)
        row = detection_store.get_detection_by_id(db, detection_id)
        if row is None:
            raise FileNotFoundError(f"detection id not found: {camera} {detection_id}")
        detection_store.set_label(db, detection_id, label)
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


def handle_camera_recording_status(handler):
    if not handler.path.startswith("/camera_recording_status/"):
        return False
    return camera_handlers.proxy_camera_recording_request(
        handler,
        target_path="/recording/status",
        method="GET",
        cameras=CAMERAS,
        in_docker=_IN_DOCKER,
        parse_index=_parse_camera_index,
        request_cls=Request,
        urlopen_fn=urlopen,
        timeout=5,
    )


def handle_camera_recording_schedule(handler):
    if not handler.path.startswith("/camera_recording_schedule/"):
        return False
    return camera_handlers.proxy_camera_recording_request(
        handler,
        target_path="/recording/schedule",
        method="POST",
        cameras=CAMERAS,
        in_docker=_IN_DOCKER,
        parse_index=_parse_camera_index,
        request_cls=Request,
        urlopen_fn=urlopen,
        timeout=10,
    )


def handle_camera_recording_stop(handler):
    if not handler.path.startswith("/camera_recording_stop/"):
        return False
    return camera_handlers.proxy_camera_recording_request(
        handler,
        target_path="/recording/stop",
        method="POST",
        cameras=CAMERAS,
        in_docker=_IN_DOCKER,
        parse_index=_parse_camera_index,
        request_cls=Request,
        urlopen_fn=urlopen,
        timeout=10,
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

        cam_dir = Path(DETECTIONS_DIR) / camera_name
        if not cam_dir.is_dir():
            raise ValueError(f"camera directory not found: {camera_name}")

        db = _db_path()
        detection_store.init_db(db)

        deleted_count = 0
        deleted_detections = []

        jsonl_file = cam_dir / "detections.jsonl"
        if jsonl_file.exists():
            records, _, _ = _iter_camera_detection_records(camera_name)
            records_by_id = {normalized["id"]: (line, raw, normalized) for line, raw, normalized in records}
            ids_to_delete = []
            for _, _, normalized in records:
                db_row = detection_store.get_detection_by_id(db, normalized["id"])
                db_label = db_row.get("label", "") if db_row else ""
                label = _normalize_detection_label(db_label)
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
                            detection_store.soft_delete(db, detection_id)
                            deleted_count += 1
                            deleted_detections.append(normalized["time"])
                        else:
                            f_out.write(line)
                    except Exception:
                        f_out.write(line)

            temp_file.replace(jsonl_file)
            detection_store.reset_sync_state(db, camera_name)

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


def handle_youtube_start(handler):
    return camera_handlers.handle_youtube_start(
        handler, CAMERAS, GO2RTC_API_URL, _parse_camera_index, Request, urlopen,
    )


def handle_youtube_stop(handler):
    return camera_handlers.handle_youtube_stop(
        handler, CAMERAS, GO2RTC_API_URL, _parse_camera_index, Request, urlopen,
    )


def handle_youtube_status(handler):
    return camera_handlers.handle_youtube_status(
        handler, CAMERAS, GO2RTC_API_URL, _parse_camera_index, Request, urlopen,
    )


def compute_nightly_stats(db_path, camera_display_names, days=30):
    """カメラ別・夜別（日没〜翌日の日の出）の流星検出数を集計する。

    Args:
        db_path: SQLite DBパス
        camera_display_names: {"camera1": "East", ...} 形式のdict
        days: 遡る日数（デフォルト30）

    Returns:
        {
            "nights": [{"date": "2026-04-12", "sunset": "...", "sunrise": "...",
                        "total": 12, "by_camera": {"East": 7, "South": 5},
                        "duplicates": 3, "ongoing": False}, ...],
            "cameras": ["East", "South", "West"],
            "total_events": 73,
        }
    """
    latitude = float(os.environ.get("LATITUDE", "35.3606"))
    longitude = float(os.environ.get("LONGITUDE", "138.7274"))
    timezone = os.environ.get("TIMEZONE", "Asia/Tokyo")
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    today = now.date()

    camera_names_ordered = list(dict.fromkeys(camera_display_names.values()))

    nights = []
    total_events = 0

    for offset in range(days):
        target_date = today - timedelta(days=offset)

        if _get_detection_window_for_date is None:
            continue

        try:
            sunset, sunrise = _get_detection_window_for_date(target_date, latitude, longitude, timezone)
        except Exception:
            logger.exception("compute_nightly_stats: failed to get window for %s", target_date)
            continue

        ongoing = now < sunrise

        start_ts = sunset.astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")
        end_ts = sunrise.astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")

        try:
            rows = detection_store.query_detections_for_stats(db_path, start_ts, end_ts)
        except Exception:
            logger.exception("compute_nightly_stats: query failed for %s", target_date)
            rows = []

        # 5秒グリーディー重複除去:
        # 複数カメラが同一流星を同時に検出する場合、タイムスタンプは数百ms〜3秒程度ずれる。
        # タイムスタンプ昇順の検出リストを走査し、直前に確定した流星から5秒以内の検出は
        # 「同一流星の別カメラ検出」とみなしてスキップする。
        # カメラをまたいで判定するため、同一カメラ内で5秒未満に連続した2件も重複扱いになるが、
        # 流星の継続時間（通常1秒未満）を考慮すると実用上は問題ない。
        last_event_ts = None
        duplicates = 0
        unique_count = 0
        by_camera = {name: 0 for name in camera_names_ordered}

        for row in rows:
            ts_str = row["timestamp"]
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=tz)
            except Exception:
                continue

            if last_event_ts is not None and (ts - last_event_ts).total_seconds() <= 5:
                duplicates += 1
                continue

            last_event_ts = ts
            unique_count += 1
            cam_key = row["camera"]
            display = camera_display_names.get(cam_key, cam_key)
            if display in by_camera:
                by_camera[display] += 1
            else:
                by_camera[display] = 1

        total_events += unique_count

        nights.append({
            "date": target_date.isoformat(),
            "sunset": sunset.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
            "sunrise": sunrise.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
            "total": unique_count,
            "by_camera": by_camera,
            "duplicates": duplicates,
            "ongoing": ongoing,
        })

    return {
        "nights": nights,
        "cameras": camera_names_ordered,
        "total_events": total_events,
    }


def compute_hourly_stats(db_path, camera_display_names, days=30) -> dict:
    """カメラ別・時間帯別（0〜23時）の流星検出数を集計する。

    Args:
        db_path: SQLite DBパス
        camera_display_names: {"camera1": "East", ...} 形式のdict
        days: 遡る日数（デフォルト30）

    Returns:
        {
            "hours": [0, 1, ..., 23],
            "cameras": ["East", "South"],
            "by_hour": {"East": [0]*24, "South": [0]*24},
        }
    """
    latitude = float(os.environ.get("LATITUDE", "35.3606"))
    longitude = float(os.environ.get("LONGITUDE", "138.7274"))
    timezone = os.environ.get("TIMEZONE", "Asia/Tokyo")
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    today = now.date()

    camera_names_ordered = list(dict.fromkeys(camera_display_names.values()))
    by_hour = {name: [0] * 24 for name in camera_names_ordered}

    for offset in range(days):
        target_date = today - timedelta(days=offset)

        if _get_detection_window_for_date is None:
            continue

        try:
            sunset, sunrise = _get_detection_window_for_date(target_date, latitude, longitude, timezone)
        except Exception:
            logger.exception("compute_hourly_stats: failed to get window for %s", target_date)
            continue

        start_ts = sunset.astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")
        end_ts = sunrise.astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")

        try:
            rows = detection_store.query_detections_for_stats(db_path, start_ts, end_ts)
        except Exception:
            logger.exception("compute_hourly_stats: query failed for %s", target_date)
            rows = []

        last_event_ts = None

        for row in rows:
            ts_str = row["timestamp"]
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=tz)
            except Exception:
                continue

            if last_event_ts is not None and (ts - last_event_ts).total_seconds() <= 5:
                continue

            last_event_ts = ts
            hour = ts.astimezone(tz).hour
            cam_key = row["camera"]
            display = camera_display_names.get(cam_key, cam_key)
            if display in by_hour:
                by_hour[display][hour] += 1

    return {
        "hours": list(range(24)),
        "cameras": camera_names_ordered,
        "by_hour": by_hour,
    }


def handle_stats_data(handler):
    if not handler.path.startswith("/stats_data"):
        return False

    query = parse_qs(urlparse(handler.path).query)
    try:
        days = int(query.get("days", ["30"])[0])
    except (ValueError, IndexError):
        days = 30
    days = min(max(days, 1), 365)

    camera_display_names = {cam["name"]: cam.get("display_name") or cam["name"] for cam in CAMERAS}
    db = _db_path()

    try:
        result = compute_nightly_stats(db, camera_display_names, days=days)
    except Exception as e:
        logger.exception("handle_stats_data: compute_nightly_stats failed")
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": "統計データの集計に失敗しました"}).encode("utf-8"))
        return True

    try:
        hourly = compute_hourly_stats(db, camera_display_names, days=days)
        result["hourly"] = hourly
    except Exception:
        logger.exception("handle_stats_data: compute_hourly_stats failed")
        result["hourly"] = {}

    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()
    handler.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    return True
