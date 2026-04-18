"""
http_handlers.py
MJPEGHandler HTTP リクエストハンドラと ThreadedHTTPServer。

detection_state.state を通じてグローバル状態にアクセスする。
recording_manager の録画関数を呼び出す。
"""
import cv2
import hashlib
import json
import numpy as np
import socket
import socketserver
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread, Event
from urllib.parse import urlparse, parse_qs

from detection_state import state, _storage_camera_name, _load_runtime_overrides, _save_runtime_overrides
from recording_manager import (
    _recordings_dir,
    _recording_supported,
    _recording_snapshot_locked,
    _set_recording_job_state,
    _stop_recording_process,
    _recording_worker,
    _parse_recording_start_at,
)
from detection_filters import _to_bool

from meteor_mask_utils import (
    build_exclusion_mask,
    build_exclusion_mask_from_frame,
    build_nuisance_mask_from_night,
)

import os

try:
    STREAM_JPEG_QUALITY = max(30, min(95, int(os.environ.get("STREAM_JPEG_QUALITY", "60"))))
except ValueError:
    STREAM_JPEG_QUALITY = 60
try:
    STREAM_MAX_FPS = max(1.0, min(30.0, float(os.environ.get("STREAM_MAX_FPS", "12"))))
except ValueError:
    STREAM_MAX_FPS = 12.0
STREAM_FRAME_INTERVAL = 1.0 / STREAM_MAX_FPS


def _is_mask_manually_modified(mask_save_path: str, hashes_json_path: str) -> bool:
    """手動更新済みマスクかどうかをハッシュで判定する。
    ハッシュ記録が存在しない・読み込みエラーの場合は False（上書き許可）を返す。
    """
    if not mask_save_path or not hashes_json_path:
        return False
    try:
        hashes_path = Path(hashes_json_path)
        hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    mask_path = Path(mask_save_path)
    filename = mask_path.name
    stored_hash = hashes.get(filename, "")
    if not stored_hash:
        return False
    try:
        current_hash = hashlib.sha256(mask_path.read_bytes()).hexdigest()
    except (OSError, FileNotFoundError):
        return False
    return current_hash != stored_hash


def _write_mask_to_build_dir(mask_build_dir: str, pending_save_path, pending_mask) -> None:
    """MASK_BUILD_DIR が設定されている場合、masks/ にもマスク画像を書き込む。
    パストラバーサルを防ぐため dest が build_dir 直下であることを確認する。
    """
    if not (mask_build_dir and pending_save_path):
        return
    try:
        build_dir = Path(mask_build_dir).resolve()
        dest = (build_dir / Path(pending_save_path).name).resolve()
        if str(dest).startswith(str(build_dir) + os.sep) or dest.parent == build_dir:
            dest.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(dest), pending_mask)
    except Exception:
        pass


class MJPEGHandler(BaseHTTPRequestHandler):  # pragma: no cover
    """MJPEG ストリーミングハンドラ"""

    def log_message(self, format, *args):
        pass  # ログを抑制

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            display_name = state.camera_display_name if hasattr(state, 'camera_display_name') else state.camera_name
            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Meteor Detector - {display_name or state.camera_name}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background: #1a1a2e;
            color: #eee;
            margin: 0;
            padding: 20px;
        }}
        h1 {{ color: #00d4ff; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .video {{
            background: #000;
            border: 2px solid #00d4ff;
            border-radius: 8px;
            overflow: hidden;
            position: relative;
        }}
        .video img {{ width: 100%; display: block; }}
        .mask-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: none;
            pointer-events: none;
        }}
        .actions {{
            margin-top: 12px;
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }}
        .mask-btn {{
            background: #2a3f6f;
            border: 1px solid #00d4ff;
            color: #00d4ff;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
        }}
        .mask-btn:hover {{
            background: #00d4ff;
            color: #0f1530;
        }}
        .mask-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .mask-toggle-btn {{
            background: #1f324f;
            border: 1px solid #ff6b6b;
            color: #ff6b6b;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
        }}
        .mask-toggle-btn:hover {{
            background: #ff6b6b;
            color: #0f1530;
        }}
        .mask-toggle-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        .stats {{
            margin-top: 20px;
            padding: 15px;
            background: #16213e;
            border-radius: 8px;
        }}
        .stats span {{
            display: inline-block;
            margin-right: 30px;
            font-size: 18px;
        }}
        .count {{ color: #00ff88; font-weight: bold; }}
        .status {{
            font-weight: bold;
        }}
        .status.online {{ color: #00ff88; }}
        .status.offline {{ color: #ff4444; }}
        .status.detecting {{ color: #ff4444; }}
        .status.idle {{ color: #888; }}
        .status.out-of-window {{ color: #58d68d; }}
        .status.waiting {{ color: #f4d03f; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Meteor Detector - {display_name or state.camera_name}</h1>
        <div class="video">
            <img src="/stream" alt="Live Stream">
            <img class="mask-overlay" id="mask-overlay" data-src="/mask" alt="mask">
        </div>
        <div class="actions">
            <button class="mask-btn" id="mask-update-btn" onclick="updateMask()">マスク更新</button>
            <button class="mask-toggle-btn" id="mask-toggle-btn" onclick="toggleMask()" disabled>マスク表示</button>
        </div>
        <div class="stats">
            <span>Stream: <b class="status online" id="stream-status">ONLINE</b></span>
            <span>Detect: <b class="status idle" id="detect-status">INITIALIZING</b></span>
            <span>Mask: <b class="status idle" id="mask-status">OFF</b></span>
            <span>Detections: <b class="count" id="count">-</b></span>
        </div>
        <p style="color:#888; margin-top:20px;">
            緑丸: 検出中の物体 / 黄線: 追跡中の軌跡 / 赤表示: 流星検出
        </p>
    </div>
    <script>
        let maskVisible = false;

        function setMaskOverlay(visible) {{
            const overlay = document.getElementById('mask-overlay');
            const btn = document.getElementById('mask-toggle-btn');
            if (!overlay || !btn) return;
            if (visible) {{
                const baseSrc = overlay.dataset.src || '';
                const sep = baseSrc.includes('?') ? '&' : '?';
                overlay.src = baseSrc + sep + 't=' + Date.now();
                overlay.style.display = 'block';
                btn.textContent = 'マスク非表示';
                maskVisible = true;
            }} else {{
                overlay.style.display = 'none';
                btn.textContent = 'マスク表示';
                maskVisible = false;
            }}
        }}

        function toggleMask() {{
            setMaskOverlay(!maskVisible);
        }}

        function updateMask() {{
            const btn = document.getElementById('mask-update-btn');
            if (!btn) return;
            const overlay = document.getElementById('mask-overlay');
            const wasVisible = maskVisible;
            btn.disabled = true;
            btn.textContent = '更新中...';
            fetch('/update_mask', {{ method: 'POST' }})
                .then(r => r.json())
                .then(async (data) => {{
                    if (!data.success) {{
                        btn.textContent = '失敗';
                        return;
                    }}
                    if (overlay) {{
                        overlay.dataset.src = '/mask?pending=1';
                        setMaskOverlay(true);
                    }}
                    const apply = confirm('新しいマスクを表示しました。入れ替えを適用しますか？');
                    const endpoint = apply ? '/confirm_mask_update' : '/discard_mask_update';
                    const applyResponse = await fetch(endpoint, {{ method: 'POST' }});
                    const applyData = await applyResponse.json();
                    btn.textContent = applyData.success ? (apply ? '更新完了' : '更新取消') : '失敗';
                    if (overlay) {{
                        overlay.dataset.src = '/mask';
                        if (applyData.success) {{
                            if (wasVisible) {{
                                setMaskOverlay(true);
                            }} else {{
                                setMaskOverlay(false);
                            }}
                        }}
                    }}
                }})
                .catch(() => {{
                    btn.textContent = '失敗';
                }})
                .finally(() => {{
                    setTimeout(() => {{
                        btn.textContent = 'マスク更新';
                        btn.disabled = false;
                    }}, 1500);
                }});
        }}

        setInterval(() => {{
            fetch('/stats').then(r => r.json()).then(data => {{
                document.getElementById('count').textContent = data.detections;
                const streamStatus = document.getElementById('stream-status');
                const detectStatus = document.getElementById('detect-status');
                const maskStatus = document.getElementById('mask-status');
                const maskToggleBtn = document.getElementById('mask-toggle-btn');

                if (streamStatus) {{
                    streamStatus.textContent = data.stream_alive ? 'ONLINE' : 'OFFLINE';
                    streamStatus.className = data.stream_alive ? 'status online' : 'status offline';
                }}
                if (detectStatus) {{
                    detectStatus.textContent = data.detection_status || (data.is_detecting ? 'DETECTING' : 'IDLE');
                    if (data.detection_status === 'DETECTING') {{
                        detectStatus.className = 'status detecting';
                    }} else if (data.detection_status === 'OUT_OF_WINDOW') {{
                        detectStatus.className = 'status out-of-window';
                    }} else if (data.detection_status === 'WAITING_FRAME' || data.detection_status === 'STREAM_LOST') {{
                        detectStatus.className = 'status waiting';
                    }} else {{
                        detectStatus.className = 'status idle';
                    }}
                    if (data.detection_window_enabled && data.detection_window_start && data.detection_window_end) {{
                        detectStatus.title = `window: ${{data.detection_window_start}} - ${{data.detection_window_end}}`;
                    }} else {{
                        detectStatus.title = '';
                    }}
                }}
                if (maskStatus) {{
                    const maskActive = data.mask_active === true;
                    maskStatus.textContent = maskActive ? 'ON' : 'OFF';
                    maskStatus.className = maskActive ? 'status online' : 'status idle';
                    if (maskToggleBtn) {{
                        maskToggleBtn.disabled = !maskActive;
                        if (!maskActive) {{
                            setMaskOverlay(false);
                        }}
                    }}
                }}
            }});
        }}, 1000);
    </script>
</body>
</html>'''
            self.wfile.write(html.encode())

        elif path == '/stream':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            try:
                self.connection.settimeout(15.0)
            except Exception:
                pass

            last_sent_seq = -1
            last_send_at = 0.0
            while True:
                with state.current_frame_lock:
                    jpeg = state.current_stream_jpeg
                    frame_seq = state.current_stream_jpeg_seq

                if jpeg is None:
                    time.sleep(0.03)
                    continue

                now = time.time()
                if frame_seq == last_sent_seq:
                    time.sleep(0.02)
                    continue
                if (now - last_send_at) < STREAM_FRAME_INTERVAL:
                    time.sleep(min(0.02, STREAM_FRAME_INTERVAL / 2.0))
                    continue

                try:
                    self.wfile.write(b'--frame\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                    self.wfile.write(jpeg)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                    last_sent_seq = frame_seq
                    last_send_at = now
                except (BrokenPipeError, ConnectionResetError, socket.timeout, TimeoutError, OSError):
                    break

        elif path == '/snapshot':
            with state.current_frame_lock:
                frame = None if state.current_frame is None else state.current_frame.copy()

            if frame is None:
                self.send_response(503)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "current frame not available"
                }).encode())
                return

            ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                self.send_response(500)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header('Content-type', 'image/jpeg')
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(jpeg.tobytes())

        elif path == '/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            elapsed = time.time() - state.start_time_global if state.start_time_global else 0
            current_time = time.time()
            time_since_last_frame = current_time - state.last_frame_time if state.last_frame_time > 0 else 0
            is_stream_alive = time_since_last_frame < state.stream_timeout
            mask_active = False
            if state.current_detector is not None:
                with state.current_detector.mask_lock:
                    mask_active = state.current_detector.exclusion_mask is not None
            with state.current_pending_mask_lock:
                has_pending_mask = state.current_pending_exclusion_mask is not None
            with state.current_recording_lock:
                recording = _recording_snapshot_locked()
            proc_w, proc_h = state.current_proc_size
            stats = {
                "detections": state.detection_count,
                "elapsed": round(elapsed, 1),
                "camera": state.camera_name,
                "settings": state.current_settings,
                "runtime_fps": round(state.current_runtime_fps, 2),
                "process_min_dim": min(proc_w, proc_h) if proc_w > 0 and proc_h > 0 else 0,
                "stream_alive": is_stream_alive,
                "time_since_last_frame": round(time_since_last_frame, 1),
                "is_detecting": state.is_detecting_now,
                "detection_status": state.current_detection_status,
                "detection_window_enabled": state.current_detection_window_enabled,
                "detection_window_active": state.current_detection_window_active,
                "detection_window_start": state.current_detection_window_start,
                "detection_window_end": state.current_detection_window_end,
                "detection_enabled": state.current_detection_enabled,
                "mask_active": mask_active,
                "mask_update_pending": has_pending_mask,
                "recording": recording,
                "twilight_active": state.current_twilight_active,
                "twilight_detection_mode": state.current_twilight_detection_mode,
                "twilight_type": state.current_twilight_type,
            }
            self.wfile.write(json.dumps(stats).encode())
        elif path == '/recording/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with state.current_recording_lock:
                payload = {
                    "success": True,
                    "recording": _recording_snapshot_locked(),
                }
            self.wfile.write(json.dumps(payload).encode())
        elif path == '/mask':
            mask = None
            query = parse_qs(parsed.query)
            show_pending = query.get("pending", ["0"])[0] in ("1", "true", "yes", "on")
            if show_pending:
                with state.current_pending_mask_lock:
                    if state.current_pending_exclusion_mask is not None:
                        mask = state.current_pending_exclusion_mask.copy()
            else:
                if state.current_detector is not None:
                    with state.current_detector.mask_lock:
                        if state.current_detector.exclusion_mask is not None:
                            mask = state.current_detector.exclusion_mask.copy()
            if mask is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                alpha = int(query.get("alpha", ["120"])[0])
            except (TypeError, ValueError):
                alpha = 120
            alpha = max(0, min(alpha, 255))
            overlay = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)
            overlay[mask > 0] = (0, 0, 255, alpha)
            ok, png = cv2.imencode('.png', overlay)
            if not ok:
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(png.tobytes())

        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/restart':
            self.send_response(202)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            if state.current_stop_flag is None:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "restart is not available"
                }).encode())
                return

            def _request_restart():
                time.sleep(0.2)
                state.current_stop_flag.set()

            Thread(target=_request_restart, daemon=True).start()
            self.wfile.write(json.dumps({
                "success": True,
                "message": "restart requested"
            }).encode())
            return

        if path == '/update_mask':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            if state.current_detector is None or state.current_proc_size == (0, 0):
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "detector not ready"
                }).encode())
                return

            with state.current_frame_lock:
                frame = None if state.current_frame is None else state.current_frame.copy()

            if frame is None:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "current frame not available"
                }).encode())
                return

            save_path = None
            if state.current_output_dir and state.current_camera_name:
                save_dir = state.current_output_dir / "masks"
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"{_storage_camera_name(state.current_camera_name)}_mask.png"

            mask = build_exclusion_mask_from_frame(
                frame,
                state.current_proc_size,
                dilate_px=state.current_mask_dilate,
                save_path=None,
            )
            with state.current_pending_mask_lock:
                state.current_pending_exclusion_mask = None if mask is None else mask.copy()
                state.current_pending_mask_save_path = save_path

            self.wfile.write(json.dumps({
                "success": mask is not None,
                "message": "mask preview ready" if mask is not None else "mask update failed",
                "saved": str(save_path) if save_path else "",
                "requires_confirmation": mask is not None,
            }).encode())
            return

        if path == '/confirm_mask_update':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            if state.current_detector is None:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "detector not ready"
                }).encode())
                return

            with state.current_pending_mask_lock:
                pending_mask = (
                    None if state.current_pending_exclusion_mask is None
                    else state.current_pending_exclusion_mask.copy()
                )
                pending_save_path = state.current_pending_mask_save_path
                state.current_pending_exclusion_mask = None
                state.current_pending_mask_save_path = None

            if pending_mask is None:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "no pending mask"
                }).encode())
                return

            state.current_detector.update_exclusion_mask(pending_mask)
            saved = ""
            if pending_save_path:
                try:
                    pending_save_path.parent.mkdir(parents=True, exist_ok=True)
                    if cv2.imwrite(str(pending_save_path), pending_mask):
                        saved = str(pending_save_path)
                except Exception:
                    pass

            # masks/ への書き込み（generate_compose.py 再実行時の上書き保護のため）
            if saved:
                _write_mask_to_build_dir(
                    os.environ.get("MASK_BUILD_DIR", ""),
                    pending_save_path,
                    pending_mask,
                )

            self.wfile.write(json.dumps({
                "success": True,
                "message": "mask updated",
                "saved": saved,
            }).encode())
            return

        if path == '/discard_mask_update':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            with state.current_pending_mask_lock:
                had_pending = state.current_pending_exclusion_mask is not None
                state.current_pending_exclusion_mask = None
                state.current_pending_mask_save_path = None

            self.wfile.write(json.dumps({
                "success": True,
                "message": "pending mask discarded" if had_pending else "no pending mask",
            }).encode())
            return

        if path == '/recording/schedule':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            if not _recording_supported():
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "recording is not available",
                    "recording": _recording_snapshot_locked(),
                }).encode())
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                if not isinstance(payload, dict):
                    raise ValueError("payload must be object")
                start_at = _parse_recording_start_at(payload.get("start_at"))
                duration_sec = int(float(payload.get("duration_sec", 0)))
                if duration_sec <= 0:
                    raise ValueError("duration_sec must be > 0")
                if duration_sec > 86400:
                    raise ValueError("duration_sec must be <= 86400")
            except Exception as e:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": f"invalid payload: {e}",
                }).encode())
                return

            with state.current_recording_lock:
                existing = state.current_recording_job
                if existing and existing.get("state") in ("scheduled", "recording"):
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "recording already scheduled or running",
                        "recording": _recording_snapshot_locked(),
                    }).encode())
                    return
                recordings_dir = _recordings_dir()
                if recordings_dir is None:
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "output directory not ready",
                    }).encode())
                    return
                safe_camera = _storage_camera_name(state.current_camera_name or state.camera_name)
                file_stamp = start_at.strftime("%Y%m%d_%H%M%S")
                output_path = recordings_dir / f"manual_{safe_camera}_{file_stamp}_{duration_sec}s.mp4"
                job = {
                    "job_id": f"rec_{int(time.time() * 1000)}",
                    "state": "scheduled",
                    "scheduled_at": datetime.now().astimezone(),
                    "start_at": start_at,
                    "started_at": None,
                    "ended_at": None,
                    "duration_sec": duration_sec,
                    "output_path": str(output_path),
                    "error": "",
                    "process": None,
                    "stop_event": Event(),
                }
                state.current_recording_job = job
                Thread(target=_recording_worker, args=(job,), daemon=True).start()
                response = {
                    "success": True,
                    "message": "recording scheduled",
                    "recording": _recording_snapshot_locked(),
                }
            self.wfile.write(json.dumps(response).encode())
            return

        if path == '/recording/stop':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with state.current_recording_lock:
                job = state.current_recording_job
                if not job or job.get("state") not in ("scheduled", "recording"):
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "no scheduled or active recording",
                        "recording": _recording_snapshot_locked(),
                    }).encode())
                    return
                _stop_recording_process(job, reason="stopped by user")
                payload = {
                    "success": True,
                    "message": "recording stop requested",
                    "recording": _recording_snapshot_locked(),
                }
            self.wfile.write(json.dumps(payload).encode())
            return

        if path == '/apply_settings':
            if state.current_detector is None or state.current_proc_size == (0, 0):
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "detector not ready"
                }).encode())
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                if not isinstance(payload, dict):
                    raise ValueError("payload must be object")
            except Exception as e:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": f"invalid payload: {e}"
                }).encode())
                return

            def _to_int(name, minimum=None, maximum=None):
                if name not in payload or payload.get(name) in ("", None):
                    return None
                value = int(payload[name])
                if minimum is not None and value < minimum:
                    raise ValueError(f"{name} must be >= {minimum}")
                if maximum is not None and value > maximum:
                    raise ValueError(f"{name} must be <= {maximum}")
                return value

            def _to_float(name, minimum=None, maximum=None):
                if name not in payload or payload.get(name) in ("", None):
                    return None
                value = float(payload[name])
                if minimum is not None and value < minimum:
                    raise ValueError(f"{name} must be >= {minimum}")
                if maximum is not None and value > maximum:
                    raise ValueError(f"{name} must be <= {maximum}")
                return value

            def _to_bool_field(name):
                if name not in payload or payload.get(name) in ("", None):
                    return None
                return _to_bool(payload.get(name))

            int_fields = [
                ("diff_threshold", 1, 255),
                ("min_brightness", 0, 255),
                ("min_brightness_tracking", 0, 255),
                ("min_length", 1, None),
                ("max_length", 1, None),
                ("min_area", 1, None),
                ("max_area", 1, None),
                ("min_track_points", 2, None),
                ("small_area_threshold", 1, None),
                ("mask_dilate", 0, 255),
                ("nuisance_dilate", 0, 255),
            ]
            float_fields = [
                ("min_duration", 0.0, None),
                ("max_duration", 0.0, None),
                ("min_speed", 0.0, None),
                ("min_linearity", 0.0, 1.0),
                ("max_gap_time", 0.0, None),
                ("max_distance", 0.0, None),
                ("merge_max_gap_time", 0.0, None),
                ("merge_max_distance", 0.0, None),
                ("merge_max_speed_ratio", 0.0, 1.0),
                ("exclude_bottom_ratio", 0.0, 1.0),
                ("exclude_edge_ratio", 0.0, 0.5),  # UI入力は%（0〜50）→ /100 変換後の値
                ("nuisance_overlap_threshold", 0.0, 1.0),
                ("nuisance_path_overlap_threshold", 0.0, 1.0),
                ("max_stationary_ratio", 0.0, 1.0),
                ("clip_margin_before", 0.0, 10.0),
                ("clip_margin_after", 0.0, 10.0),
            ]
            startup_float_fields = [
                ("scale", 0.05, 1.0),
                ("buffer", 1.0, 120.0),
                ("bird_min_brightness", 0.0, 255.0),
                ("twilight_bird_min_brightness", 0.0, 255.0),
            ]
            startup_bool_fields = ("extract_clips", "bird_filter_enabled", "twilight_bird_filter_enabled")
            startup_text_fields = ("sensitivity",)
            startup_path_fields = ("mask_image", "mask_from_day", "nuisance_mask_image", "nuisance_from_night")

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            applied = {}
            errors = []
            skipped = {}
            params = state.current_detector.params
            restart_required = False
            restart_triggers = []
            overrides_update = {}

            try:
                with state.current_detector.lock:
                    for field, min_v, max_v in int_fields:
                        if field in ("mask_dilate", "nuisance_dilate"):
                            continue
                        value = _to_int(field, min_v, max_v)
                        if value is not None:
                            setattr(params, field, value)
                            applied[field] = value

                    for field, min_v, max_v in float_fields:
                        value = _to_float(field, min_v, max_v)
                        if value is not None:
                            setattr(params, field, value)
                            applied[field] = value

                    if params.max_length < params.min_length:
                        params.max_length = params.min_length
                        applied["max_length"] = params.max_length
                    if params.max_duration < params.min_duration:
                        params.max_duration = params.min_duration
                        applied["max_duration"] = params.max_duration
                    if params.max_area < params.min_area:
                        params.max_area = params.min_area
                        applied["max_area"] = params.max_area
            except Exception as e:
                errors.append(str(e))

            try:
                new_detection_enabled = _to_bool_field("detection_enabled")
                if new_detection_enabled is not None:
                    state.current_detection_enabled = new_detection_enabled
                    applied["detection_enabled"] = new_detection_enabled
                    overrides_update["detection_enabled"] = new_detection_enabled
                new_mask_dilate = _to_int("mask_dilate", 0, 255)
                if new_mask_dilate is not None:
                    state.current_mask_dilate = new_mask_dilate
                    applied["mask_dilate"] = new_mask_dilate
                    overrides_update["mask_dilate"] = new_mask_dilate
                new_nuisance_dilate = _to_int("nuisance_dilate", 0, 255)
                if new_nuisance_dilate is not None:
                    state.current_nuisance_dilate = new_nuisance_dilate
                    applied["nuisance_dilate"] = new_nuisance_dilate
                    overrides_update["nuisance_dilate"] = new_nuisance_dilate
                new_clip_margin_before = _to_float("clip_margin_before", 0.0, 10.0)
                if new_clip_margin_before is not None:
                    state.current_clip_margin_before = new_clip_margin_before
                    applied["clip_margin_before"] = new_clip_margin_before
                    overrides_update["clip_margin_before"] = new_clip_margin_before
                new_clip_margin_after = _to_float("clip_margin_after", 0.0, 10.0)
                if new_clip_margin_after is not None:
                    state.current_clip_margin_after = new_clip_margin_after
                    applied["clip_margin_after"] = new_clip_margin_after
                    overrides_update["clip_margin_after"] = new_clip_margin_after
            except Exception as e:
                errors.append(str(e))

            proc_w, proc_h = state.current_proc_size
            mask_image = str(payload.get("mask_image", "")).strip()
            mask_from_day = str(payload.get("mask_from_day", "")).strip()
            nuisance_mask_image = str(payload.get("nuisance_mask_image", "")).strip()
            nuisance_from_night = str(payload.get("nuisance_from_night", "")).strip()

            app_dir = Path(__file__).parent.resolve()

            def _validate_app_path(raw: str) -> bool:
                if not raw:
                    return True
                try:
                    resolved = Path(raw).resolve()
                    return app_dir == resolved or app_dir in resolved.parents
                except Exception:
                    return False

            for _field_name, _field_val in (
                ("mask_image", mask_image),
                ("mask_from_day", mask_from_day),
                ("nuisance_mask_image", nuisance_mask_image),
                ("nuisance_from_night", nuisance_from_night),
            ):
                if _field_val and not _validate_app_path(_field_val):
                    self.send_response(400)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": f"invalid path for {_field_name}"
                    }).encode())
                    return

            try:
                if mask_image:
                    mask_img = cv2.imread(mask_image, cv2.IMREAD_GRAYSCALE)
                    if mask_img is None:
                        raise ValueError(f"mask_image not readable: {mask_image}")
                    if (mask_img.shape[1], mask_img.shape[0]) != (proc_w, proc_h):
                        mask_img = cv2.resize(mask_img, (proc_w, proc_h), interpolation=cv2.INTER_NEAREST)
                    _, new_mask = cv2.threshold(mask_img, 1, 255, cv2.THRESH_BINARY)
                    state.current_detector.update_exclusion_mask(new_mask)
                    with state.current_pending_mask_lock:
                        state.current_pending_exclusion_mask = None
                        state.current_pending_mask_save_path = None
                    applied["mask_image"] = mask_image
                    overrides_update["mask_image"] = mask_image
                elif mask_from_day:
                    mask_build_dir = os.environ.get("MASK_BUILD_DIR", "")
                    hashes_json_path = os.path.join(mask_build_dir, ".generated_hashes.json") if mask_build_dir else ""
                    if _is_mask_manually_modified(str(state.current_mask_save) if state.current_mask_save else "", hashes_json_path):
                        skipped["mask_from_day"] = "manually_modified"
                    else:
                        new_mask = build_exclusion_mask(
                            mask_from_day,
                            (proc_w, proc_h),
                            dilate_px=state.current_mask_dilate,
                            save_path=state.current_mask_save,
                        )
                        if new_mask is None:
                            raise ValueError(f"mask_from_day not readable: {mask_from_day}")
                        state.current_detector.update_exclusion_mask(new_mask)
                        with state.current_pending_mask_lock:
                            state.current_pending_exclusion_mask = None
                            state.current_pending_mask_save_path = None
                        applied["mask_from_day"] = mask_from_day
                        overrides_update["mask_from_day"] = mask_from_day
            except Exception as e:
                errors.append(str(e))

            try:
                new_nuisance_mask = None
                if nuisance_mask_image:
                    nuisance_img = cv2.imread(nuisance_mask_image, cv2.IMREAD_GRAYSCALE)
                    if nuisance_img is None:
                        raise ValueError(f"nuisance_mask_image not readable: {nuisance_mask_image}")
                    if (nuisance_img.shape[1], nuisance_img.shape[0]) != (proc_w, proc_h):
                        nuisance_img = cv2.resize(nuisance_img, (proc_w, proc_h), interpolation=cv2.INTER_NEAREST)
                    _, new_nuisance_mask = cv2.threshold(nuisance_img, 1, 255, cv2.THRESH_BINARY)
                    applied["nuisance_mask_image"] = nuisance_mask_image
                    overrides_update["nuisance_mask_image"] = nuisance_mask_image

                if nuisance_from_night:
                    mask_build_dir = os.environ.get("MASK_BUILD_DIR", "")
                    hashes_json_path = os.path.join(mask_build_dir, ".generated_hashes.json") if mask_build_dir else ""
                    nuisance_save_path = ""
                    if state.current_mask_save:
                        base_name = Path(state.current_mask_save).stem.removesuffix("_mask")
                        nuisance_save_path = str(Path(state.current_mask_save).parent / f"{base_name}_nuisance_mask.png")
                    if _is_mask_manually_modified(nuisance_save_path, hashes_json_path):
                        skipped["nuisance_from_night"] = "manually_modified"
                    else:
                        auto_nuisance = build_nuisance_mask_from_night(
                            nuisance_from_night,
                            (proc_w, proc_h),
                            dilate_px=state.current_nuisance_dilate,
                        )
                        if auto_nuisance is None:
                            raise ValueError(f"nuisance_from_night not readable: {nuisance_from_night}")
                        new_nuisance_mask = auto_nuisance if new_nuisance_mask is None else cv2.bitwise_or(
                            new_nuisance_mask, auto_nuisance
                        )
                        applied["nuisance_from_night"] = nuisance_from_night
                        overrides_update["nuisance_from_night"] = nuisance_from_night

                if new_nuisance_mask is not None:
                    state.current_detector.update_nuisance_mask(new_nuisance_mask)
            except Exception as e:
                errors.append(str(e))

            for field, min_v, max_v in startup_float_fields:
                try:
                    value = _to_float(field, min_v, max_v)
                    if value is not None:
                        overrides_update[field] = value
                        applied[field] = value
                        restart_required = True
                        restart_triggers.append(field)
                except Exception as e:
                    errors.append(str(e))

            for field in startup_bool_fields:
                try:
                    value = _to_bool_field(field)
                    if value is not None:
                        overrides_update[field] = value
                        applied[field] = value
                        restart_required = True
                        restart_triggers.append(field)
                except Exception as e:
                    errors.append(str(e))

            for field in startup_text_fields:
                if field not in payload:
                    continue
                value = str(payload.get(field, "")).strip().lower()
                if not value:
                    continue
                if field == "sensitivity" and value not in ("low", "medium", "high", "faint", "fireball"):
                    errors.append("sensitivity must be one of low/medium/high/faint/fireball")
                    continue
                overrides_update[field] = value
                applied[field] = value
                restart_required = True
                restart_triggers.append(field)

            for field in startup_path_fields:
                if field not in payload:
                    continue
                value = str(payload.get(field, "")).strip()
                overrides_update[field] = value
                applied[field] = value
                restart_required = True
                restart_triggers.append(field)

            for field in (
                "exclude_bottom_ratio",
                "exclude_edge_ratio",
                "diff_threshold",
                "min_brightness",
                "min_brightness_tracking",
                "min_length",
                "max_length",
                "min_duration",
                "max_duration",
                "min_speed",
                "min_linearity",
                "min_area",
                "max_area",
                "max_gap_time",
                "max_distance",
                "merge_max_gap_time",
                "merge_max_distance",
                "merge_max_speed_ratio",
                "nuisance_overlap_threshold",
                "nuisance_path_overlap_threshold",
                "min_track_points",
                "max_stationary_ratio",
                "small_area_threshold",
            ):
                if field in applied:
                    overrides_update[field] = applied[field]

            if state.current_runtime_overrides_paths:
                try:
                    persisted = {}
                    for path in state.current_runtime_overrides_paths:
                        persisted = _load_runtime_overrides(path)
                        if persisted:
                            break
                    persisted.update(overrides_update)
                    for path in state.current_runtime_overrides_paths:
                        _save_runtime_overrides(path, persisted)
                except Exception as e:
                    errors.append(f"failed to save runtime overrides: {e}")

            settings_updates = {}
            for key in (
                "diff_threshold",
                "min_brightness",
                "min_brightness_tracking",
                "min_length",
                "max_length",
                "min_duration",
                "max_duration",
                "min_speed",
                "min_linearity",
                "min_area",
                "max_area",
                "max_gap_time",
                "max_distance",
                "merge_max_gap_time",
                "merge_max_distance",
                "merge_max_speed_ratio",
                "exclude_bottom_ratio",
                "exclude_edge_ratio",
                "nuisance_overlap_threshold",
                "nuisance_path_overlap_threshold",
                "min_track_points",
                "max_stationary_ratio",
                "small_area_threshold",
                "sensitivity",
                "scale",
                "buffer",
                "extract_clips",
                "mask_dilate",
                "nuisance_dilate",
                "clip_margin_before",
                "clip_margin_after",
                "detection_enabled",
                "mask_image",
                "mask_from_day",
                "nuisance_mask_image",
                "nuisance_from_night",
                "twilight_detection_mode",
                "twilight_type",
                "twilight_sensitivity",
                "twilight_min_speed",
                "bird_filter_enabled",
                "bird_min_brightness",
                "twilight_bird_filter_enabled",
                "twilight_bird_min_brightness",
            ):
                if key in applied:
                    settings_updates[key] = applied[key]
            if settings_updates:
                state.current_settings.update(settings_updates)

            restart_requested = False
            if restart_required and state.current_stop_flag is not None:
                restart_requested = True

                def _request_restart():
                    time.sleep(0.2)
                    state.current_stop_flag.set()

                Thread(target=_request_restart, daemon=True).start()

            self.wfile.write(json.dumps({
                "success": len(errors) == 0,
                "applied": applied,
                "skipped": skipped,
                "errors": errors,
                "restart_required": restart_required,
                "restart_requested": restart_requested,
                "restart_triggers": sorted(set(restart_triggers)),
            }).encode())
            return

        self.send_response(404)
        self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):  # pragma: no cover
    daemon_threads = True
