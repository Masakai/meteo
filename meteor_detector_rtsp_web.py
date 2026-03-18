#!/usr/bin/env python3
"""
RTSPストリームからリアルタイム流星検出（Webプレビュー付き）

Webブラウザでプレビューを確認できます。
http://localhost:8080/ でアクセス

使い方:
    python meteor_detector_rtsp_web.py rtsp://192.168.1.100:554/stream --web-port 8080

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

import argparse
import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict
from threading import Thread, Lock, RLock, Event
import json
from pathlib import Path
from datetime import datetime
import time
import signal
import sys
import os
import socket
import subprocess
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
from urllib.parse import urlparse, parse_qs

from meteor_detector_realtime import (
    DetectionParams,
    EventMerger,
    RTSPReader,
    RealtimeMeteorDetector,
    RingBuffer,
    probe_rtsp_endpoint,
    probe_rtsp_with_ffprobe,
    save_meteor_event,
    sanitize_fps,
)
from meteor_mask_utils import (
    build_exclusion_mask,
    build_exclusion_mask_from_frame,
    build_nuisance_mask_from_night,
)

VERSION = "3.2.0"

# 天文薄暮期間の判定用
try:
    from astro_utils import is_detection_active
except ImportError:
    is_detection_active = None


# グローバル変数（Webサーバー用）
current_frame = None
current_frame_lock = Lock()
current_frame_seq = 0
current_stream_jpeg = None
current_stream_jpeg_seq = 0
detection_count = 0
start_time_global = None
camera_name = ""
camera_display_name = ""  # Web表示用のカメラ名
last_frame_time = 0  # 最後にフレームを受信した時刻
stream_timeout = 10.0  # ストリームがタイムアウトとみなす秒数
is_detecting_now = False  # 現在検出処理中かどうか
current_detection_window_enabled = False
current_detection_window_active = True
current_detection_window_start = ""
current_detection_window_end = ""
current_detection_status = "INITIALIZING"
current_detection_enabled = True
current_detector = None
current_proc_size = (0, 0)
current_mask_dilate = 20
current_mask_save = None
current_nuisance_dilate = 3
current_clip_margin_before = 1.0
current_clip_margin_after = 1.0
current_output_dir = None
current_camera_name = ""  # 保存先・永続化用の識別子。display名は使わない
current_stop_flag = None
current_runtime_fps = 0.0
current_runtime_overrides_paths = []
current_rtsp_url = ""
current_pending_exclusion_mask = None
current_pending_mask_save_path = None
current_pending_mask_lock = Lock()
current_recording_lock = RLock()
current_recording_job = None
try:
    STREAM_JPEG_QUALITY = max(30, min(95, int(os.environ.get("STREAM_JPEG_QUALITY", "60"))))
except ValueError:
    STREAM_JPEG_QUALITY = 60
try:
    STREAM_MAX_FPS = max(1.0, min(30.0, float(os.environ.get("STREAM_MAX_FPS", "12"))))
except ValueError:
    STREAM_MAX_FPS = 12.0
STREAM_FRAME_INTERVAL = 1.0 / STREAM_MAX_FPS
# 設定情報（ダッシュボード表示用）
current_settings = {
    "sensitivity": "medium",
    "scale": 0.5,
    "buffer": 15.0,
    "extract_clips": True,
    "exclude_bottom": 0.0625,
    "exclude_edge_ratio": 0.0,
    "source_fps": 30.0,
    "nuisance_mask_image": "",
    "nuisance_from_night": "",
    "nuisance_dilate": 3,
    "nuisance_overlap_threshold": 0.60,
    "clip_margin_before": 1.0,
    "clip_margin_after": 1.0,
    "detection_enabled": True,
}


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _storage_camera_name(cam_name: str) -> str:
    """保存先・永続化ファイル名に使うカメラ識別子。表示名は使わない。"""
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(cam_name)).strip("_")
    return safe or "camera"


def _runtime_override_paths(output_dir: str, cam_name: str) -> List[Path]:
    safe = _storage_camera_name(cam_name)
    output_path = Path(output_dir)
    primary = output_path.parent / "runtime_settings" / f"{safe}.json"
    legacy = output_path / "runtime_settings" / f"{safe}.json"
    if primary == legacy:
        return [primary]
    return [primary, legacy]


def _load_runtime_overrides(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"[WARN] ランタイム設定の読み込みに失敗: {path} ({e})")
    return {}


def _save_runtime_overrides(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(path)


def _recordings_dir() -> Optional[Path]:
    if current_output_dir is None or not current_camera_name:
        return None
    return Path(current_output_dir) / "manual_recordings" / _storage_camera_name(current_camera_name)


def _recording_supported() -> bool:
    return shutil.which("ffmpeg") is not None and bool(current_rtsp_url)


def _format_recording_dt(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    try:
        return value.astimezone().isoformat(timespec="seconds")
    except Exception:
        return value.isoformat(timespec="seconds")


def _parse_recording_start_at(value) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now().astimezone()
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt.astimezone()


def _recording_snapshot_locked() -> dict:
    now = datetime.now().astimezone()
    payload = {
        "supported": _recording_supported(),
        "state": "idle",
        "camera": current_camera_name or camera_name,
        "job_id": "",
        "start_at": "",
        "scheduled_at": "",
        "started_at": "",
        "ended_at": "",
        "duration_sec": 0,
        "remaining_sec": 0,
        "output_path": "",
        "error": "",
    }
    job = current_recording_job
    if not job:
        return payload
    payload.update(
        {
            "state": job.get("state", "idle"),
            "job_id": job.get("job_id", ""),
            "start_at": _format_recording_dt(job.get("start_at")),
            "scheduled_at": _format_recording_dt(job.get("scheduled_at")),
            "started_at": _format_recording_dt(job.get("started_at")),
            "ended_at": _format_recording_dt(job.get("ended_at")),
            "duration_sec": int(job.get("duration_sec", 0) or 0),
            "output_path": str(job.get("output_path") or ""),
            "error": str(job.get("error") or ""),
        }
    )
    state = payload["state"]
    start_at = job.get("start_at")
    duration_sec = max(0, int(job.get("duration_sec", 0) or 0))
    if state == "scheduled" and start_at is not None:
        payload["remaining_sec"] = max(0, int((start_at - now).total_seconds()))
    elif state == "recording":
        started_at = job.get("started_at") or now
        elapsed = max(0.0, (now - started_at).total_seconds())
        payload["remaining_sec"] = max(0, int(duration_sec - elapsed))
    return payload


def _set_recording_job_state(job: dict, state: str, *, error: str = "") -> None:
    with current_recording_lock:
        if current_recording_job is not job:
            return
        job["state"] = state
        if error:
            job["error"] = error
        if state == "scheduled":
            job["scheduled_at"] = datetime.now().astimezone()
        elif state == "recording":
            job["started_at"] = datetime.now().astimezone()
        elif state in ("completed", "failed", "stopped"):
            job["ended_at"] = datetime.now().astimezone()
            job["process"] = None


def _stop_recording_process(job: dict, *, reason: str = "stopped") -> bool:
    proc = job.get("process")
    stop_event = job.get("stop_event")
    if stop_event is not None:
        stop_event.set()
    if proc is None:
        return False
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
    except Exception:
        pass
    _set_recording_job_state(job, "stopped", error=reason)
    return True


def _recording_worker(job: dict) -> None:
    stop_event = job["stop_event"]
    try:
        wait_seconds = max(0.0, (job["start_at"] - datetime.now().astimezone()).total_seconds())
        if wait_seconds > 0 and stop_event.wait(wait_seconds):
            _set_recording_job_state(job, "stopped", error="cancelled before start")
            return
        if stop_event.is_set():
            _set_recording_job_state(job, "stopped", error="cancelled before start")
            return
        recordings_dir = _recordings_dir()
        if recordings_dir is None:
            _set_recording_job_state(job, "failed", error="output directory not ready")
            return
        recordings_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            _set_recording_job_state(job, "failed", error="ffmpeg not found")
            return
        duration_sec = int(job["duration_sec"])
        output_path = Path(job["output_path"])
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            current_rtsp_url,
            "-t",
            str(duration_sec),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            str(output_path),
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with current_recording_lock:
            if current_recording_job is not job:
                try:
                    proc.terminate()
                except Exception:
                    pass
                return
            job["process"] = proc
        _set_recording_job_state(job, "recording")
        _, stderr = proc.communicate()
        if stop_event.is_set():
            _set_recording_job_state(job, "stopped", error="stopped")
            return
        if proc.returncode == 0:
            _set_recording_job_state(job, "completed")
            return
        err_text = stderr.decode("utf-8", errors="ignore").strip()
        _set_recording_job_state(job, "failed", error=err_text or f"ffmpeg exited with code {proc.returncode}")
    except Exception as e:
        _set_recording_job_state(job, "failed", error=str(e))


class MJPEGHandler(BaseHTTPRequestHandler):
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
            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Meteor Detector - {camera_display_name or camera_name}</title>
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
        <h1>Meteor Detector - {camera_display_name or camera_name}</h1>
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
                with current_frame_lock:
                    jpeg = current_stream_jpeg
                    frame_seq = current_stream_jpeg_seq

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
            with current_frame_lock:
                frame = None if current_frame is None else current_frame.copy()

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
            global current_detection_window_enabled, current_detection_window_active
            global current_detection_window_start, current_detection_window_end, current_detection_status
            elapsed = time.time() - start_time_global if start_time_global else 0
            current_time = time.time()
            time_since_last_frame = current_time - last_frame_time if last_frame_time > 0 else 0
            is_stream_alive = time_since_last_frame < stream_timeout
            mask_active = False
            if current_detector is not None:
                with current_detector.mask_lock:
                    mask_active = current_detector.exclusion_mask is not None
            with current_pending_mask_lock:
                has_pending_mask = current_pending_exclusion_mask is not None
            with current_recording_lock:
                recording = _recording_snapshot_locked()
            stats = {
                "detections": detection_count,
                "elapsed": round(elapsed, 1),
                "camera": camera_name,
                "settings": current_settings,
                "runtime_fps": round(current_runtime_fps, 2),
                "stream_alive": is_stream_alive,
                "time_since_last_frame": round(time_since_last_frame, 1),
                "is_detecting": is_detecting_now,
                "detection_status": current_detection_status,
                "detection_window_enabled": current_detection_window_enabled,
                "detection_window_active": current_detection_window_active,
                "detection_window_start": current_detection_window_start,
                "detection_window_end": current_detection_window_end,
                "detection_enabled": current_detection_enabled,
                "mask_active": mask_active,
                "mask_update_pending": has_pending_mask,
                "recording": recording,
            }
            self.wfile.write(json.dumps(stats).encode())
        elif path == '/recording/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with current_recording_lock:
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
                with current_pending_mask_lock:
                    if current_pending_exclusion_mask is not None:
                        mask = current_pending_exclusion_mask.copy()
            else:
                if current_detector is not None:
                    with current_detector.mask_lock:
                        if current_detector.exclusion_mask is not None:
                            mask = current_detector.exclusion_mask.copy()
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
        global current_mask_dilate, current_nuisance_dilate, current_detection_enabled
        global current_clip_margin_before, current_clip_margin_after
        global current_pending_exclusion_mask, current_pending_mask_save_path
        global current_recording_job
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/restart':
            self.send_response(202)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            if current_stop_flag is None:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "restart is not available"
                }).encode())
                return

            # レスポンス返却後に停止フラグを立てる
            def _request_restart():
                time.sleep(0.2)
                current_stop_flag.set()

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

            if current_detector is None or current_proc_size == (0, 0):
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "detector not ready"
                }).encode())
                return

            with current_frame_lock:
                frame = None if current_frame is None else current_frame.copy()

            if frame is None:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "current frame not available"
                }).encode())
                return

            save_path = None
            if current_output_dir and current_camera_name:
                save_dir = current_output_dir / "masks"
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"{_storage_camera_name(current_camera_name)}_mask.png"

            mask = build_exclusion_mask_from_frame(
                frame,
                current_proc_size,
                dilate_px=current_mask_dilate,
                save_path=None,
            )
            with current_pending_mask_lock:
                current_pending_exclusion_mask = None if mask is None else mask.copy()
                current_pending_mask_save_path = save_path

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

            if current_detector is None:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "detector not ready"
                }).encode())
                return

            with current_pending_mask_lock:
                pending_mask = None if current_pending_exclusion_mask is None else current_pending_exclusion_mask.copy()
                pending_save_path = current_pending_mask_save_path
                current_pending_exclusion_mask = None
                current_pending_mask_save_path = None

            if pending_mask is None:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "no pending mask"
                }).encode())
                return

            current_detector.update_exclusion_mask(pending_mask)
            saved = ""
            if pending_save_path:
                try:
                    pending_save_path.parent.mkdir(parents=True, exist_ok=True)
                    if cv2.imwrite(str(pending_save_path), pending_mask):
                        saved = str(pending_save_path)
                except Exception:
                    pass

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

            with current_pending_mask_lock:
                had_pending = current_pending_exclusion_mask is not None
                current_pending_exclusion_mask = None
                current_pending_mask_save_path = None

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

            with current_recording_lock:
                existing = current_recording_job
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
                safe_camera = _storage_camera_name(current_camera_name or camera_name)
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
                current_recording_job = job
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
            with current_recording_lock:
                job = current_recording_job
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
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            if current_detector is None or current_proc_size == (0, 0):
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
                ("exclude_edge_ratio", 0.0, 0.5),
                ("nuisance_overlap_threshold", 0.0, 1.0),
                ("nuisance_path_overlap_threshold", 0.0, 1.0),
                ("max_stationary_ratio", 0.0, 1.0),
                ("clip_margin_before", 0.0, 10.0),
                ("clip_margin_after", 0.0, 10.0),
            ]
            startup_float_fields = [
                ("scale", 0.05, 1.0),
                ("buffer", 1.0, 120.0),
            ]
            startup_bool_fields = ("extract_clips",)
            startup_text_fields = ("sensitivity",)
            startup_path_fields = ("mask_image", "mask_from_day", "nuisance_mask_image", "nuisance_from_night")

            applied = {}
            errors = []
            params = current_detector.params
            restart_required = False
            restart_triggers = []
            overrides_update = {}

            try:
                with current_detector.lock:
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
                    current_detection_enabled = new_detection_enabled
                    applied["detection_enabled"] = new_detection_enabled
                    overrides_update["detection_enabled"] = new_detection_enabled
                new_mask_dilate = _to_int("mask_dilate", 0, 255)
                if new_mask_dilate is not None:
                    current_mask_dilate = new_mask_dilate
                    applied["mask_dilate"] = new_mask_dilate
                    overrides_update["mask_dilate"] = new_mask_dilate
                new_nuisance_dilate = _to_int("nuisance_dilate", 0, 255)
                if new_nuisance_dilate is not None:
                    current_nuisance_dilate = new_nuisance_dilate
                    applied["nuisance_dilate"] = new_nuisance_dilate
                    overrides_update["nuisance_dilate"] = new_nuisance_dilate
                new_clip_margin_before = _to_float("clip_margin_before", 0.0, 10.0)
                if new_clip_margin_before is not None:
                    current_clip_margin_before = new_clip_margin_before
                    applied["clip_margin_before"] = new_clip_margin_before
                    overrides_update["clip_margin_before"] = new_clip_margin_before
                new_clip_margin_after = _to_float("clip_margin_after", 0.0, 10.0)
                if new_clip_margin_after is not None:
                    current_clip_margin_after = new_clip_margin_after
                    applied["clip_margin_after"] = new_clip_margin_after
                    overrides_update["clip_margin_after"] = new_clip_margin_after
            except Exception as e:
                errors.append(str(e))

            proc_w, proc_h = current_proc_size
            mask_image = str(payload.get("mask_image", "")).strip()
            mask_from_day = str(payload.get("mask_from_day", "")).strip()
            nuisance_mask_image = str(payload.get("nuisance_mask_image", "")).strip()
            nuisance_from_night = str(payload.get("nuisance_from_night", "")).strip()

            try:
                if mask_image:
                    mask_img = cv2.imread(mask_image, cv2.IMREAD_GRAYSCALE)
                    if mask_img is None:
                        raise ValueError(f"mask_image not readable: {mask_image}")
                    if (mask_img.shape[1], mask_img.shape[0]) != (proc_w, proc_h):
                        mask_img = cv2.resize(mask_img, (proc_w, proc_h), interpolation=cv2.INTER_NEAREST)
                    _, new_mask = cv2.threshold(mask_img, 1, 255, cv2.THRESH_BINARY)
                    current_detector.update_exclusion_mask(new_mask)
                    with current_pending_mask_lock:
                        current_pending_exclusion_mask = None
                        current_pending_mask_save_path = None
                    applied["mask_image"] = mask_image
                    overrides_update["mask_image"] = mask_image
                elif mask_from_day:
                    new_mask = build_exclusion_mask(
                        mask_from_day,
                        (proc_w, proc_h),
                        dilate_px=current_mask_dilate,
                        save_path=current_mask_save,
                    )
                    if new_mask is None:
                        raise ValueError(f"mask_from_day not readable: {mask_from_day}")
                    current_detector.update_exclusion_mask(new_mask)
                    with current_pending_mask_lock:
                        current_pending_exclusion_mask = None
                        current_pending_mask_save_path = None
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
                    auto_nuisance = build_nuisance_mask_from_night(
                        nuisance_from_night,
                        (proc_w, proc_h),
                        dilate_px=current_nuisance_dilate,
                    )
                    if auto_nuisance is None:
                        raise ValueError(f"nuisance_from_night not readable: {nuisance_from_night}")
                    new_nuisance_mask = auto_nuisance if new_nuisance_mask is None else cv2.bitwise_or(
                        new_nuisance_mask, auto_nuisance
                    )
                    applied["nuisance_from_night"] = nuisance_from_night
                    overrides_update["nuisance_from_night"] = nuisance_from_night

                if new_nuisance_mask is not None:
                    current_detector.update_nuisance_mask(new_nuisance_mask)
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

            if current_runtime_overrides_paths:
                try:
                    persisted = {}
                    for path in current_runtime_overrides_paths:
                        persisted = _load_runtime_overrides(path)
                        if persisted:
                            break
                    persisted.update(overrides_update)
                    for path in current_runtime_overrides_paths:
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
            ):
                if key in applied:
                    settings_updates[key] = applied[key]
            if settings_updates:
                current_settings.update(settings_updates)

            restart_requested = False
            if restart_required and current_stop_flag is not None:
                restart_requested = True

                def _request_restart():
                    time.sleep(0.2)
                    current_stop_flag.set()

                Thread(target=_request_restart, daemon=True).start()

            self.wfile.write(json.dumps({
                "success": len(errors) == 0,
                "applied": applied,
                "errors": errors,
                "restart_required": restart_required,
                "restart_requested": restart_requested,
                "restart_triggers": sorted(set(restart_triggers)),
            }).encode())
            return

        self.send_response(404)
        self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def detection_thread_worker(
    reader,
    params,
    process_scale,
    buffer_seconds,
    fps,
    output_path,
    extract_clips,
    stop_flag,
    mask_image=None,
    mask_from_day=None,
    mask_dilate=5,
    mask_save=None,
    nuisance_mask_image=None,
    nuisance_from_night=None,
    nuisance_dilate=3,
    clip_margin_before=1.0,
    clip_margin_after=1.0,
    enable_time_window=False,
    latitude=35.3606,
    longitude=138.7274,
    timezone="Asia/Tokyo",
):
    """検出処理を行うワーカースレッド"""
    global current_frame, current_frame_seq, current_stream_jpeg, current_stream_jpeg_seq
    global detection_count, last_frame_time, is_detecting_now, current_runtime_fps
    global current_detector, current_proc_size, current_mask_dilate, current_mask_save
    global current_nuisance_dilate
    global current_clip_margin_before, current_clip_margin_after
    global current_output_dir, current_camera_name
    global current_pending_exclusion_mask, current_pending_mask_save_path
    global current_detection_window_enabled, current_detection_window_active
    global current_detection_window_start, current_detection_window_end, current_detection_status
    global current_detection_enabled

    width, height = reader.frame_size
    proc_width = int(width * process_scale)
    proc_height = int(height * process_scale)
    scale_factor = 1.0 / process_scale

    ring_buffer = RingBuffer(buffer_seconds, fps)
    exclusion_mask = None
    nuisance_mask = None
    persistent_mask_path = None
    if output_path:
        persistent_mask_path = Path(output_path) / "masks" / f"{_storage_camera_name(camera_name)}_mask.png"
        if mask_image is None and persistent_mask_path.exists():
            mask_image = str(persistent_mask_path)
    if mask_image:
        mask_img = cv2.imread(mask_image, cv2.IMREAD_GRAYSCALE)
        if mask_img is None:
            print(f"[WARN] マスク画像を読み込めません: {mask_image}")
        else:
            if (mask_img.shape[1], mask_img.shape[0]) != (proc_width, proc_height):
                mask_img = cv2.resize(mask_img, (proc_width, proc_height), interpolation=cv2.INTER_NEAREST)
            _, exclusion_mask = cv2.threshold(mask_img, 1, 255, cv2.THRESH_BINARY)
            print(f"マスク適用: {mask_image}")
    elif mask_from_day:
        exclusion_mask = build_exclusion_mask(
            mask_from_day,
            (proc_width, proc_height),
            dilate_px=mask_dilate,
            save_path=mask_save,
        )
        if exclusion_mask is not None:
            print(f"マスク適用: {mask_from_day}")

    if nuisance_mask_image:
        nuisance_img = cv2.imread(nuisance_mask_image, cv2.IMREAD_GRAYSCALE)
        if nuisance_img is None:
            print(f"[WARN] ノイズ帯マスク画像を読み込めません: {nuisance_mask_image}")
        else:
            if (nuisance_img.shape[1], nuisance_img.shape[0]) != (proc_width, proc_height):
                nuisance_img = cv2.resize(nuisance_img, (proc_width, proc_height), interpolation=cv2.INTER_NEAREST)
            _, nuisance_mask = cv2.threshold(nuisance_img, 1, 255, cv2.THRESH_BINARY)
            print(f"ノイズ帯マスク適用: {nuisance_mask_image}")

    if nuisance_from_night:
        auto_nuisance = build_nuisance_mask_from_night(
            nuisance_from_night,
            (proc_width, proc_height),
            dilate_px=nuisance_dilate,
        )
        if auto_nuisance is not None:
            nuisance_mask = auto_nuisance if nuisance_mask is None else cv2.bitwise_or(nuisance_mask, auto_nuisance)
            print(f"ノイズ帯マスク自動生成: {nuisance_from_night}")

    detector = RealtimeMeteorDetector(
        params,
        fps,
        exclusion_mask=exclusion_mask,
        nuisance_mask=nuisance_mask,
    )
    merger = EventMerger(params)
    current_detector = detector
    current_proc_size = (proc_width, proc_height)
    current_mask_dilate = mask_dilate
    current_nuisance_dilate = nuisance_dilate
    current_clip_margin_before = clip_margin_before
    current_clip_margin_after = clip_margin_after
    current_mask_save = mask_save
    current_output_dir = Path(output_path)
    current_camera_name = camera_name
    with current_pending_mask_lock:
        current_pending_exclusion_mask = None
        current_pending_mask_save_path = None

    prev_gray = None
    frame_count = 0
    recent_frame_times: List[float] = []

    # 天文薄暮期間のチェック（ウィンドウ終了後に再計算）
    is_detection_time = True  # デフォルトは有効
    detection_start = None
    detection_end = None
    current_detection_window_enabled = bool(enable_time_window and is_detection_active)
    if enable_time_window and is_detection_active:
        is_detection_time, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
        current_detection_window_active = is_detection_time
        current_detection_window_start = detection_start.strftime("%Y-%m-%d %H:%M:%S")
        current_detection_window_end = detection_end.strftime("%Y-%m-%d %H:%M:%S")
    else:
        current_detection_window_active = True
        current_detection_window_start = ""
        current_detection_window_end = ""
    current_detection_status = "WAITING_FRAME"

    while not stop_flag.is_set():
        ret, timestamp, frame = reader.read()
        if not ret:
            is_detecting_now = False
            current_detection_status = "STREAM_LOST"
            break
        if frame is None:
            continue

        # ストリーム生存確認用の時刻を更新
        last_frame_time = time.time()
        recent_frame_times.append(timestamp)
        if len(recent_frame_times) > 30:
            recent_frame_times.pop(0)
        if len(recent_frame_times) >= 2:
            dt = recent_frame_times[-1] - recent_frame_times[0]
            if dt > 0:
                current_runtime_fps = (len(recent_frame_times) - 1) / dt

        ring_buffer.add(timestamp, frame)

        if process_scale != 1.0:
            proc_frame = cv2.resize(frame, (proc_width, proc_height), interpolation=cv2.INTER_AREA)
        else:
            proc_frame = frame

        gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)

        # 天文薄暮期間のチェック（定期的に）
        if enable_time_window and is_detection_active:
            if detection_start is None or detection_end is None:
                is_detection_time, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
            else:
                now = datetime.now(detection_start.tzinfo)
                if now > detection_end:
                    is_detection_time, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
                else:
                    is_detection_time = detection_start <= now <= detection_end
            current_detection_window_active = is_detection_time
            current_detection_window_start = detection_start.strftime("%Y-%m-%d %H:%M:%S")
            current_detection_window_end = detection_end.strftime("%Y-%m-%d %H:%M:%S")

        objects = []
        if prev_gray is not None:
            # 検出期間内の場合のみ検出処理を実行
            if not current_detection_enabled:
                objects = []
                is_detecting_now = False
                current_detection_status = "DISABLED"
            elif is_detection_time:
                # アクティブなトラックがある場合は追跡モードを有効化
                tracking_mode = len(detector.active_tracks) > 0
                objects = detector.detect_bright_objects(gray, prev_gray, tracking_mode=tracking_mode)
                is_detecting_now = True
                current_detection_status = "DETECTING"
            else:
                objects = []
                is_detecting_now = False
                current_detection_status = "OUT_OF_WINDOW"
        else:
            is_detecting_now = False
            current_detection_status = "WAITING_FRAME"

        if process_scale != 1.0:
            for obj in objects:
                cx, cy = obj["centroid"]
                obj["centroid"] = (int(cx * scale_factor), int(cy * scale_factor))

        events = detector.track_objects(objects, timestamp)

        for event in events:
            merged_events = merger.add_event(event)
            for merged_event in merged_events:
                detection_count += 1
                print(f"\n[{merged_event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
                print(f"  長さ: {merged_event.length:.1f}px, 時間: {merged_event.duration:.2f}秒")
                clip_path = save_meteor_event(
                    merged_event,
                    ring_buffer,
                    output_path,
                    fps=fps,
                    extract_clips=extract_clips,
                    clip_margin_before=current_clip_margin_before,
                    clip_margin_after=current_clip_margin_after,
                    composite_after=current_clip_margin_after,
                )

        expired_events = merger.flush_expired(timestamp)
        for expired_event in expired_events:
            detection_count += 1
            print(f"\n[{expired_event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
            print(f"  長さ: {expired_event.length:.1f}px, 時間: {expired_event.duration:.2f}秒")
            clip_path = save_meteor_event(
                expired_event,
                ring_buffer,
                output_path,
                fps=fps,
                extract_clips=extract_clips,
                clip_margin_before=current_clip_margin_before,
                clip_margin_after=current_clip_margin_after,
                composite_after=current_clip_margin_after,
            )

        # プレビュー用フレーム生成
        display = frame.copy()

        for obj in objects:
            cx, cy = obj["centroid"]
            cv2.circle(display, (cx, cy), 5, (0, 255, 0), 2)

        with detector.lock:
            for track_points in detector.active_tracks.values():
                if len(track_points) >= 2:
                    for i in range(1, len(track_points)):
                        pt1 = (track_points[i-1][1], track_points[i-1][2])
                        pt2 = (track_points[i][1], track_points[i][2])
                        cv2.line(display, pt1, pt2, (0, 255, 255), 2)

        elapsed = time.time() - start_time_global
        overlay_name = camera_display_name or camera_name
        cv2.putText(display, f"{overlay_name} | {elapsed:.0f}s | Detections: {detection_count}",
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        stream_jpeg = None
        ok, encoded_stream = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY])
        if ok:
            stream_jpeg = encoded_stream.tobytes()

        with current_frame_lock:
            current_frame = display
            current_frame_seq += 1
            if stream_jpeg is not None:
                current_stream_jpeg = stream_jpeg
                current_stream_jpeg_seq = current_frame_seq

        prev_gray = gray.copy()
        frame_count += 1

        if frame_count % (int(fps) * 60) == 0:
            elapsed = time.time() - start_time_global
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 稼働: {elapsed/60:.1f}分, 検出: {detection_count}個")

    # 終了処理
    events = detector.finalize_all()
    for event in events:
        merged_events = merger.add_event(event)
        for merged_event in merged_events:
            detection_count += 1
            clip_path = save_meteor_event(
                merged_event,
                ring_buffer,
                output_path,
                fps=fps,
                extract_clips=extract_clips,
                clip_margin_before=current_clip_margin_before,
                clip_margin_after=current_clip_margin_after,
                composite_after=current_clip_margin_after,
            )

    for event in merger.flush_all():
        detection_count += 1
        clip_path = save_meteor_event(
            event,
            ring_buffer,
            output_path,
            fps=fps,
            extract_clips=extract_clips,
            clip_margin_before=current_clip_margin_before,
            clip_margin_after=current_clip_margin_after,
            composite_after=current_clip_margin_after,
        )


def process_rtsp_stream(
    url: str,
    output_dir: str = "meteor_detections",
    params: DetectionParams = None,
    process_scale: float = 0.5,
    buffer_seconds: float = 15.0,
    sensitivity: str = "medium",
    web_port: int = 0,
    cam_name: str = "camera",
    extract_clips: bool = True,
    mask_image: Optional[str] = None,
    mask_from_day: Optional[str] = None,
    mask_dilate: int = 5,
    mask_save: Optional[str] = None,
    nuisance_mask_image: Optional[str] = None,
    nuisance_from_night: Optional[str] = None,
    nuisance_dilate: int = 3,
    nuisance_overlap_threshold: float = 0.60,
    clip_margin_before: float = 1.0,
    clip_margin_after: float = 1.0,
):
    global current_frame, detection_count, start_time_global, camera_name, camera_display_name, current_settings
    global current_runtime_fps, current_runtime_overrides_paths
    global current_stop_flag, current_detection_enabled, current_rtsp_url, current_recording_job

    params = params or DetectionParams()
    camera_name = _storage_camera_name(cam_name)
    # 環境変数からWeb表示用の名前を取得（オプション）
    import os
    camera_display_name = os.environ.get("CAMERA_NAME_DISPLAY", "")

    override_paths = _runtime_override_paths(output_dir, cam_name)
    current_runtime_overrides_paths = override_paths
    runtime_overrides = {}
    loaded_from = None
    for path in override_paths:
        runtime_overrides = _load_runtime_overrides(path)
        if runtime_overrides:
            loaded_from = path
            break
    if runtime_overrides:
        print(f"ランタイム設定を適用: {loaded_from}")
        # 旧パスから読んだ場合でも、優先保存先へ寄せる
        try:
            _save_runtime_overrides(override_paths[0], runtime_overrides)
        except Exception as e:
            print(f"[WARN] ランタイム設定の移行保存に失敗: {override_paths[0]} ({e})")

    sensitivity = str(runtime_overrides.get("sensitivity", sensitivity))
    process_scale = float(runtime_overrides.get("scale", process_scale))
    buffer_seconds = float(runtime_overrides.get("buffer", buffer_seconds))
    extract_clips = _to_bool(runtime_overrides.get("extract_clips", extract_clips), default=extract_clips)
    mask_image = runtime_overrides.get("mask_image", mask_image) or None
    mask_from_day = runtime_overrides.get("mask_from_day", mask_from_day) or None
    mask_dilate = int(runtime_overrides.get("mask_dilate", mask_dilate))
    nuisance_mask_image = runtime_overrides.get("nuisance_mask_image", nuisance_mask_image) or None
    nuisance_from_night = runtime_overrides.get("nuisance_from_night", nuisance_from_night) or None
    nuisance_dilate = int(runtime_overrides.get("nuisance_dilate", nuisance_dilate))
    nuisance_overlap_threshold = float(
        runtime_overrides.get("nuisance_overlap_threshold", nuisance_overlap_threshold)
    )
    clip_margin_before = float(runtime_overrides.get("clip_margin_before", clip_margin_before))
    clip_margin_after = float(runtime_overrides.get("clip_margin_after", clip_margin_after))
    current_detection_enabled = _to_bool(runtime_overrides.get("detection_enabled", True), default=True)

    params.exclude_bottom_ratio = float(runtime_overrides.get("exclude_bottom_ratio", params.exclude_bottom_ratio))
    params.exclude_edge_ratio = float(runtime_overrides.get("exclude_edge_ratio", params.exclude_edge_ratio))
    pending_param_overrides = {}
    for field in (
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
        "exclude_edge_ratio",
        "nuisance_path_overlap_threshold",
        "min_track_points",
        "max_stationary_ratio",
        "small_area_threshold",
    ):
        if field in runtime_overrides:
            pending_param_overrides[field] = runtime_overrides[field]

    if sensitivity == "low":
        params.diff_threshold = 40
        params.min_brightness = 220
    elif sensitivity == "high":
        params.diff_threshold = 20
        params.min_brightness = 180
    elif sensitivity == "faint":
        params.diff_threshold = 16
        params.min_brightness = 150
        params.min_length = 10
        params.min_duration = 0.06
        params.min_speed = 10.0
        params.min_linearity = 0.55
        params.min_track_points = 3
        params.min_area = 5
        params.max_distance = 90
    elif sensitivity == "fireball":
        params.diff_threshold = 15
        params.min_brightness = 150
        params.max_duration = 20.0
        params.min_speed = 20.0
        params.min_linearity = 0.6

    for field, value in pending_param_overrides.items():
        setattr(params, field, value)

    # 追跡中は検出閾値より低めにして追跡継続を優先
    if "min_brightness_tracking" not in runtime_overrides:
        params.min_brightness_tracking = (
            max(1, int(params.min_brightness * 0.8))
            if sensitivity == "faint"
            else params.min_brightness
        )
    params.nuisance_overlap_threshold = nuisance_overlap_threshold

    required_buffer = params.max_duration + 2.0
    effective_buffer_seconds = min(buffer_seconds, required_buffer)
    if effective_buffer_seconds != buffer_seconds:
        print(f"バッファ秒数を{effective_buffer_seconds:.1f}秒に調整（検出前後1秒 + 最大検出時間）")

    # 設定情報を更新（ダッシュボード表示用）
    current_settings.update({
        "sensitivity": sensitivity,
        "scale": process_scale,
        "buffer": effective_buffer_seconds,
        "extract_clips": extract_clips,
        "exclude_bottom": params.exclude_bottom_ratio,
        "exclude_bottom_ratio": params.exclude_bottom_ratio,
        "exclude_edge_ratio": params.exclude_edge_ratio,
        "source_fps": 30.0,
        "mask_image": mask_image or "",
        "mask_from_day": mask_from_day or "",
        "mask_dilate": mask_dilate,
        "nuisance_mask_image": nuisance_mask_image or "",
        "nuisance_from_night": nuisance_from_night or "",
        "nuisance_dilate": nuisance_dilate,
        "nuisance_overlap_threshold": nuisance_overlap_threshold,
        "clip_margin_before": clip_margin_before,
        "clip_margin_after": clip_margin_after,
        "detection_enabled": current_detection_enabled,
        "diff_threshold": params.diff_threshold,
        "min_brightness": params.min_brightness,
        "min_brightness_tracking": params.min_brightness_tracking,
        "min_length": params.min_length,
        "max_length": params.max_length,
        "min_duration": params.min_duration,
        "max_duration": params.max_duration,
        "min_speed": params.min_speed,
        "min_linearity": params.min_linearity,
        "min_area": params.min_area,
        "max_area": params.max_area,
        "max_gap_time": params.max_gap_time,
        "max_distance": params.max_distance,
        "merge_max_gap_time": params.merge_max_gap_time,
        "merge_max_distance": params.merge_max_distance,
        "merge_max_speed_ratio": params.merge_max_speed_ratio,
        "nuisance_path_overlap_threshold": params.nuisance_path_overlap_threshold,
        "min_track_points": params.min_track_points,
        "max_stationary_ratio": params.max_stationary_ratio,
        "small_area_threshold": params.small_area_threshold,
    })

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"RTSPストリーム: {url}", flush=True)
    print(f"出力先: {output_path}", flush=True)
    if web_port > 0:
        print(f"Webプレビュー: http://0.0.0.0:{web_port}/", flush=True)

    # Webサーバー起動
    httpd = None
    if web_port > 0:
        httpd = ThreadedHTTPServer(('0.0.0.0', web_port), MJPEGHandler)
        web_thread = Thread(target=httpd.serve_forever, daemon=True)
        web_thread.start()

    rtsp_log_detail = _to_bool(os.environ.get("RTSP_LOG_DETAIL", "true"), default=True)
    reader = RTSPReader(url, log_detail=rtsp_log_detail)
    print(f"RTSP事前診断: {probe_rtsp_endpoint(url)}", flush=True)
    if rtsp_log_detail:
        print(f"RTSP ffprobe診断: {probe_rtsp_with_ffprobe(url)}", flush=True)
    print("接続中...", flush=True)
    reader.start()

    if not reader.connected.is_set():
        print("接続失敗（10秒以内に接続確立できず）", flush=True)
        return

    width, height = reader.frame_size
    fps = sanitize_fps(reader.fps, default=30.0)

    current_settings["source_fps"] = fps
    current_rtsp_url = url

    print(f"解像度: {width}x{height}", flush=True)
    print("検出開始 (Ctrl+C で終了)", flush=True)
    print("-" * 50, flush=True)

    detection_count = 0
    start_time_global = time.time()
    current_runtime_fps = 0.0

    stop_flag = Event()
    current_stop_flag = stop_flag

    def signal_handler(sig, frame):
        print("\n終了中...")
        stop_flag.set()

    signal.signal(signal.SIGINT, signal_handler)

    # 環境変数から天文薄暮期間の設定を取得
    enable_time_window = os.environ.get('ENABLE_TIME_WINDOW', 'true').lower() == 'true'
    latitude = float(os.environ.get('LATITUDE', '35.3606'))
    longitude = float(os.environ.get('LONGITUDE', '138.7274'))
    timezone = os.environ.get('TIMEZONE', 'Asia/Tokyo')

    if enable_time_window:
        print(f"検出時間制限: 有効（緯度: {latitude}, 経度: {longitude}）", flush=True)
    else:
        print(f"検出時間制限: 無効（常時検出）", flush=True)

    # 検出処理を別スレッドで実行
    detection_thread = Thread(
        target=detection_thread_worker,
        args=(reader, params, process_scale, effective_buffer_seconds, fps, output_path, extract_clips, stop_flag),
        kwargs={
            'mask_image': mask_image,
            'mask_from_day': mask_from_day,
            'mask_dilate': mask_dilate,
            'mask_save': Path(mask_save) if mask_save else None,
            'nuisance_mask_image': nuisance_mask_image,
            'nuisance_from_night': nuisance_from_night,
            'nuisance_dilate': nuisance_dilate,
            'clip_margin_before': clip_margin_before,
            'clip_margin_after': clip_margin_after,
            'enable_time_window': enable_time_window,
            'latitude': latitude,
            'longitude': longitude,
            'timezone': timezone,
        },
        daemon=False,
    )
    detection_thread.start()

    # メインスレッドは停止シグナルを待機
    try:
        while not stop_flag.is_set():
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n終了中...")
        stop_flag.set()

    # 検出スレッドの終了を待機
    detection_thread.join(timeout=5.0)

    with current_recording_lock:
        job = current_recording_job
    if job and job.get("state") in ("scheduled", "recording"):
        _stop_recording_process(job, reason="camera service shutting down")

    reader.stop()
    if httpd:
        httpd.shutdown()
    current_stop_flag = None

    print(f"\n終了 - 検出数: {detection_count}個", flush=True)


def main():
    parser = argparse.ArgumentParser(description="RTSPストリーム流星検出（Webプレビュー付き）")

    parser.add_argument("url", help="RTSP URL")
    parser.add_argument("-o", "--output", default="meteor_detections", help="出力ディレクトリ")
    parser.add_argument("--sensitivity", choices=["low", "medium", "high", "faint", "fireball"], default="medium")
    parser.add_argument("--scale", type=float, default=0.5, help="処理スケール")
    parser.add_argument("--buffer", type=float, default=15.0, help="バッファ秒数")
    parser.add_argument("--exclude-bottom", type=float, default=1/16)
    parser.add_argument("--web-port", type=int, default=0, help="Webプレビューポート (0=無効)")
    parser.add_argument("--camera-name", default="camera", help="カメラ名")
    parser.add_argument("--extract-clips", action="store_true", default=True,
                        help="流星検出時に動画クリップを保存 (デフォルト: 有効)")
    parser.add_argument("--no-clips", action="store_true",
                        help="動画クリップを保存しない（コンポジット画像のみ）")
    parser.add_argument("--mask-image", help="作成済みの除外マスク画像を使用（優先）")
    parser.add_argument("--mask-from-day", help="昼間画像から検出除外マスクを生成（空以外を除外）")
    parser.add_argument("--mask-dilate", type=int, default=20, help="除外マスクの拡張ピクセル数")
    parser.add_argument("--mask-save", help="生成した除外マスク画像の保存先")
    parser.add_argument("--nuisance-mask-image", help="作成済みのノイズ帯マスク画像を使用")
    parser.add_argument("--nuisance-from-night", help="夜間基準画像からノイズ帯マスクを生成")
    parser.add_argument("--nuisance-dilate", type=int, default=3, help="ノイズ帯マスクの拡張ピクセル数")
    parser.add_argument(
        "--nuisance-overlap-threshold",
        type=float,
        default=0.60,
        help="小領域候補を除外するノイズ帯重なり率の閾値",
    )
    parser.add_argument("--clip-margin-before", type=float, default=1.0, help="検出前の記録秒数")
    parser.add_argument("--clip-margin-after", type=float, default=1.0, help="検出後の記録秒数")

    args = parser.parse_args()

    params = DetectionParams()
    params.exclude_bottom_ratio = args.exclude_bottom

    # クリップ抽出の判定（--no-clips または環境変数 EXTRACT_CLIPS=false で無効化）
    env_extract = os.environ.get("EXTRACT_CLIPS", "true").lower()
    extract_clips = not args.no_clips and env_extract not in ("false", "0", "no")

    mask_image = args.mask_image.strip() if args.mask_image else None
    mask_image = mask_image if mask_image else None
    mask_from_day = args.mask_from_day.strip() if args.mask_from_day else None
    mask_from_day = mask_from_day if mask_from_day else None
    mask_save = args.mask_save.strip() if args.mask_save else None
    mask_save = mask_save if mask_save else None
    nuisance_mask_image = args.nuisance_mask_image.strip() if args.nuisance_mask_image else None
    nuisance_mask_image = nuisance_mask_image if nuisance_mask_image else None
    nuisance_from_night = args.nuisance_from_night.strip() if args.nuisance_from_night else None
    nuisance_from_night = nuisance_from_night if nuisance_from_night else None

    process_rtsp_stream(
        args.url,
        output_dir=args.output,
        params=params,
        process_scale=args.scale,
        buffer_seconds=args.buffer,
        sensitivity=args.sensitivity,
        web_port=args.web_port,
        cam_name=args.camera_name,
        extract_clips=extract_clips,
        mask_image=mask_image,
        mask_from_day=mask_from_day,
        mask_dilate=args.mask_dilate,
        mask_save=mask_save,
        nuisance_mask_image=nuisance_mask_image,
        nuisance_from_night=nuisance_from_night,
        nuisance_dilate=args.nuisance_dilate,
        nuisance_overlap_threshold=args.nuisance_overlap_threshold,
        clip_margin_before=args.clip_margin_before,
        clip_margin_after=args.clip_margin_after,
    )


if __name__ == "__main__":
    main()
