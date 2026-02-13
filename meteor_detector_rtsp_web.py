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
from threading import Thread, Lock, Event
import json
from pathlib import Path
from datetime import datetime
import time
import signal
import sys
import os
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
from urllib.parse import urlparse, parse_qs

from meteor_detector_realtime import (
    DetectionParams,
    EventMerger,
    RTSPReader,
    RealtimeMeteorDetector,
    RingBuffer,
    save_meteor_event,
    sanitize_fps,
)

VERSION = "1.9.0"

# 天文薄暮期間の判定用
try:
    from astro_utils import is_detection_active
except ImportError:
    is_detection_active = None


# グローバル変数（Webサーバー用）
current_frame = None
current_frame_lock = Lock()
detection_count = 0
start_time_global = None
camera_name = ""
last_frame_time = 0  # 最後にフレームを受信した時刻
stream_timeout = 10.0  # ストリームがタイムアウトとみなす秒数
is_detecting_now = False  # 現在検出処理中かどうか
current_detector = None
current_proc_size = (0, 0)
current_mask_dilate = 20
current_mask_save = None
current_output_dir = None
current_camera_name = ""
current_stop_flag = None
current_runtime_fps = 0.0
# 設定情報（ダッシュボード表示用）
current_settings = {
    "sensitivity": "medium",
    "scale": 0.5,
    "buffer": 15.0,
    "extract_clips": True,
    "exclude_bottom": 0.0625,
    "fb_normalize": False,
    "fb_delete_mov": False,
    "source_fps": 30.0,
}


def _apply_sensitivity_params(params: DetectionParams, sensitivity: str) -> str:
    value = str(sensitivity or "medium").strip().lower()
    if value not in {"low", "medium", "high", "fireball"}:
        value = "medium"

    if value == "low":
        params.diff_threshold = 40
        params.min_brightness = 220
        params.max_duration = 12.0
        params.min_speed = 50.0
        params.min_linearity = 0.7
    elif value == "high":
        params.diff_threshold = 20
        params.min_brightness = 180
        params.max_duration = 12.0
        params.min_speed = 50.0
        params.min_linearity = 0.7
    elif value == "fireball":
        params.diff_threshold = 15
        params.min_brightness = 150
        params.max_duration = 20.0
        params.min_speed = 20.0
        params.min_linearity = 0.6
    else:
        params.diff_threshold = 30
        params.min_brightness = 200
        params.max_duration = 12.0
        params.min_speed = 50.0
        params.min_linearity = 0.7

    params.min_brightness_tracking = max(1, int(params.min_brightness * 0.8))
    return value


def _collect_detector_settings(params: Optional[DetectionParams]) -> dict:
    if params is None:
        return dict(current_settings)
    settings = dict(current_settings)
    settings.update(
        {
            "diff_threshold": int(params.diff_threshold),
            "min_brightness": int(params.min_brightness),
            "min_brightness_tracking": int(params.min_brightness_tracking),
            "min_length": int(params.min_length),
            "max_length": int(params.max_length),
            "min_duration": float(params.min_duration),
            "max_duration": float(params.max_duration),
            "min_speed": float(params.min_speed),
            "min_linearity": float(params.min_linearity),
            "min_area": int(params.min_area),
            "max_area": int(params.max_area),
            "max_gap_time": float(params.max_gap_time),
            "max_distance": float(params.max_distance),
            "merge_max_gap_time": float(params.merge_max_gap_time),
            "merge_max_distance": float(params.merge_max_distance),
            "merge_max_speed_ratio": float(params.merge_max_speed_ratio),
            "exclude_bottom": float(params.exclude_bottom_ratio),
        }
    )
    return settings


def fb_normalize_clip(
    clip_path: Path,
    *,
    overwrite: bool = True,
    delete_source: bool = False,
) -> Optional[Path]:
    if clip_path is None:
        return None
    out_path = clip_path.with_suffix(".mp4")
    if out_path.exists() and not overwrite:
        return None

    fps = 30.0
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(clip_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if probe.returncode == 0:
            rate = probe.stdout.strip()
            if "/" in rate:
                num, den = rate.split("/", 1)
                den_f = float(den)
                if den_f != 0:
                    fps = float(num) / den_f
            elif rate:
                fps = float(rate)
    except Exception:
        pass
    fps = sanitize_fps(fps, default=30.0)
    gop = max(1, int(round(fps * 2)))

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-i",
        str(clip_path),
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level",
        "3.1",
        "-pix_fmt",
        "yuv420p",
        "-r",
        f"{fps:.3f}",
        "-g",
        str(gop),
        "-keyint_min",
        str(gop),
        "-sc_threshold",
        "0",
        "-tag:v",
        "avc1",
        "-an",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return None
    if delete_source:
        try:
            clip_path.unlink()
        except Exception:
            print(f"[WARN] 元MOV削除に失敗: {clip_path}")
    return out_path


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
    <title>Meteor Detector - {camera_name}</title>
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
            flex-wrap: wrap;
        }}
        .snapshot-btn {{
            margin-right: auto;
            background: #1e3b37;
            border: 1px solid #48d1bf;
            color: #9ff7e9;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
        }}
        .snapshot-btn:hover {{
            background: #48d1bf;
            color: #0f1530;
        }}
        .snapshot-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
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
        .mask-reset-btn {{
            background: #3a2430;
            border: 1px solid #ff7f7f;
            color: #ffb3b3;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
        }}
        .mask-reset-btn:hover {{
            background: #ff6b6b;
            color: #1a1a2e;
        }}
        .mask-reset-btn:disabled {{
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
        .settings-box {{
            margin-top: 16px;
            padding: 12px;
            background: #16213e;
            border-radius: 8px;
        }}
        .settings-box h3 {{
            margin: 0 0 10px;
            color: #00d4ff;
            font-size: 1em;
        }}
        .settings-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 6px 12px;
            font-size: 0.85em;
        }}
        .settings-item {{
            display: flex;
            justify-content: space-between;
            gap: 8px;
            border-bottom: 1px dashed #2a3f6f;
            padding-bottom: 3px;
        }}
        .settings-item .k {{
            color: #9bb1d8;
        }}
        .settings-item .v {{
            color: #c8ffe7;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Meteor Detector - {camera_name}</h1>
        <div class="video">
            <img src="/stream" alt="Live Stream">
            <img class="mask-overlay" id="mask-overlay" data-src="/mask" alt="mask">
        </div>
        <div class="actions">
            <button class="snapshot-btn" id="snapshot-btn" onclick="downloadSnapshot()">スナップショット保存</button>
            <button class="mask-btn" id="mask-update-btn" onclick="updateMask()">マスク更新</button>
            <button class="mask-reset-btn" id="mask-reset-btn" onclick="resetMask()">マスクリセット</button>
            <button class="mask-toggle-btn" id="mask-toggle-btn" onclick="toggleMask()" disabled>マスク表示</button>
        </div>
        <div class="stats">
            <span>Stream: <b class="status online" id="stream-status">ONLINE</b></span>
            <span>Detect: <b class="status idle" id="detect-status">IDLE</b></span>
            <span>Mask: <b class="status idle" id="mask-status">OFF</b></span>
            <span>Detections: <b class="count" id="count">-</b></span>
        </div>
        <div class="settings-box">
            <h3>現在のパラメータ</h3>
            <div class="settings-grid" id="settings-grid"></div>
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
                overlay.src = overlay.dataset.src + '?t=' + Date.now();
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
            btn.disabled = true;
            btn.textContent = '更新中...';
            fetch('/update_mask', {{ method: 'POST' }})
                .then(r => r.json())
                .then(data => {{
                    btn.textContent = data.success ? '更新完了' : '失敗';
                    if (data.success && maskVisible) {{
                        setMaskOverlay(true);
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

        function resetMask() {{
            const btn = document.getElementById('mask-reset-btn');
            if (!btn) return;
            if (!confirm('マスクをリセットしますか?')) return;
            btn.disabled = true;
            btn.textContent = 'リセット中...';
            fetch('/reset_mask', {{ method: 'POST' }})
                .then(r => r.json())
                .then(data => {{
                    btn.textContent = data.success ? 'リセット完了' : '失敗';
                    if (data.success) {{
                        setMaskOverlay(false);
                    }}
                }})
                .catch(() => {{
                    btn.textContent = '失敗';
                }})
                .finally(() => {{
                    setTimeout(() => {{
                        btn.textContent = 'マスクリセット';
                        btn.disabled = false;
                    }}, 1500);
                }});
        }}

        function downloadSnapshot() {{
            const btn = document.getElementById('snapshot-btn');
            if (!btn) return;
            btn.disabled = true;
            btn.textContent = '保存中...';
            try {{
                const ts = new Date().toISOString().replace(/[:.]/g, '-');
                const link = document.createElement('a');
                link.href = '/snapshot?t=' + Date.now();
                link.download = `snapshot_{camera_name}_${{ts}}.jpg`;
                link.style.display = 'none';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                btn.textContent = '保存要求済み';
            }} catch (_) {{
                btn.textContent = '失敗';
            }} finally {{
                setTimeout(() => {{
                    btn.textContent = 'スナップショット保存';
                    btn.disabled = false;
                }}, 1500);
            }}
        }}

        function renderSettings(settings) {{
            const grid = document.getElementById('settings-grid');
            if (!grid) return;
            if (!settings || typeof settings !== 'object') {{
                grid.innerHTML = '<div class="settings-item"><span class="k">settings</span><span class="v">-</span></div>';
                return;
            }}
            const order = [
                'sensitivity', 'diff_threshold', 'min_brightness', 'min_brightness_tracking',
                'min_length', 'max_length', 'min_duration', 'max_duration',
                'min_speed', 'min_linearity', 'min_area', 'max_area',
                'max_gap_time', 'max_distance', 'merge_max_gap_time', 'merge_max_distance',
                'merge_max_speed_ratio', 'exclude_bottom', 'extract_clips', 'scale', 'buffer',
                'fb_normalize', 'fb_delete_mov', 'mask_dilate', 'source_fps'
            ];
            const renderedKeys = new Set();
            const items = [];
            order.forEach((key) => {{
                if (!(key in settings)) return;
                renderedKeys.add(key);
                items.push(`<div class="settings-item"><span class="k">${{key}}</span><span class="v">${{settings[key]}}</span></div>`);
            }});
            Object.keys(settings).sort().forEach((key) => {{
                if (renderedKeys.has(key)) return;
                items.push(`<div class="settings-item"><span class="k">${{key}}</span><span class="v">${{settings[key]}}</span></div>`);
            }});
            grid.innerHTML = items.join('');
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
                    detectStatus.textContent = data.is_detecting ? 'DETECTING' : 'IDLE';
                    detectStatus.className = data.is_detecting ? 'status detecting' : 'status idle';
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
                renderSettings(data.settings);
            }});
        }}, 1000);
    </script>
</body>
</html>'''
            self.wfile.write(html.encode())

        elif path == '/stream':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()

            while True:
                with current_frame_lock:
                    if current_frame is None:
                        continue
                    _, jpeg = cv2.imencode('.jpg', current_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])

                try:
                    self.wfile.write(b'--frame\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                    self.wfile.write(jpeg.tobytes())
                    self.wfile.write(b'\r\n')
                    time.sleep(0.033)  # ~30fps
                except:
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
            elapsed = time.time() - start_time_global if start_time_global else 0
            current_time = time.time()
            time_since_last_frame = current_time - last_frame_time if last_frame_time > 0 else 0
            is_stream_alive = time_since_last_frame < stream_timeout
            mask_active = False
            if current_detector is not None:
                with current_detector.mask_lock:
                    mask_active = current_detector.exclusion_mask is not None
            stats = {
                "detections": detection_count,
                "elapsed": round(elapsed, 1),
                "camera": camera_name,
                "settings": current_settings,
                "runtime_fps": round(current_runtime_fps, 2),
                "stream_alive": is_stream_alive,
                "time_since_last_frame": round(time_since_last_frame, 1),
                "is_detecting": is_detecting_now,
                "mask_active": mask_active,
            }
            self.wfile.write(json.dumps(stats).encode())
        elif path == '/settings':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "settings": current_settings}).encode())
        elif path == '/mask':
            mask = None
            if current_detector is not None:
                with current_detector.mask_lock:
                    if current_detector.exclusion_mask is not None:
                        mask = current_detector.exclusion_mask.copy()
            if mask is None:
                self.send_response(404)
                self.end_headers()
                return
            query = parse_qs(parsed.query)
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
        global current_mask_dilate
        if self.path == '/restart':
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

        if self.path == '/update_mask':
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

            save_path = current_mask_save if current_mask_save else None
            if save_path is None and current_output_dir and current_camera_name:
                save_dir = current_output_dir / "masks"
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"{current_camera_name}_mask.png"

            mask = build_exclusion_mask_from_frame(
                frame,
                current_proc_size,
                dilate_px=current_mask_dilate,
                save_path=save_path,
            )
            current_detector.update_exclusion_mask(mask)

            self.wfile.write(json.dumps({
                "success": mask is not None,
                "message": "mask updated" if mask is not None else "mask update failed",
                "saved": str(save_path) if save_path else ""
            }).encode())
            return

        if self.path == '/reset_mask':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            try:
                if current_detector is None:
                    raise ValueError("detector not ready")

                current_detector.update_exclusion_mask(None)

                deleted = ""
                save_path = current_mask_save if current_mask_save else None
                if save_path is None and current_output_dir and current_camera_name:
                    save_path = current_output_dir / "masks" / f"{current_camera_name}_mask.png"
                if save_path and Path(save_path).exists():
                    Path(save_path).unlink()
                    deleted = str(save_path)

                self.wfile.write(json.dumps({
                    "success": True,
                    "message": "mask reset",
                    "deleted": deleted,
                }).encode())
            except Exception as e:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": str(e),
                }).encode())
            return

        if self.path == '/settings':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            try:
                content_length = int(self.headers.get('Content-Length', '0'))
                raw = self.rfile.read(content_length) if content_length > 0 else b'{}'
                payload = json.loads(raw.decode('utf-8')) if raw else {}
                if not isinstance(payload, dict):
                    raise ValueError("payload must be object")
                if current_detector is None:
                    raise ValueError("detector not ready")

                params = current_detector.params
                if "sensitivity" in payload:
                    current_settings["sensitivity"] = _apply_sensitivity_params(params, payload.get("sensitivity"))

                if "extract_clips" in payload:
                    val = payload.get("extract_clips")
                    if not isinstance(val, bool):
                        val = str(val).strip().lower() in ('1', 'true', 'yes', 'on')
                    current_settings["extract_clips"] = bool(val)

                if "fb_normalize" in payload:
                    val = payload.get("fb_normalize")
                    if not isinstance(val, bool):
                        val = str(val).strip().lower() in ('1', 'true', 'yes', 'on')
                    current_settings["fb_normalize"] = bool(val)

                if "fb_delete_mov" in payload:
                    val = payload.get("fb_delete_mov")
                    if not isinstance(val, bool):
                        val = str(val).strip().lower() in ('1', 'true', 'yes', 'on')
                    current_settings["fb_delete_mov"] = bool(val)

                float_fields = [
                    ("min_duration", 0.01, 120.0),
                    ("max_duration", 0.01, 120.0),
                    ("min_speed", 0.0, 10000.0),
                    ("min_linearity", 0.0, 1.0),
                    ("max_gap_time", 0.0, 60.0),
                    ("max_distance", 1.0, 5000.0),
                    ("merge_max_gap_time", 0.0, 60.0),
                    ("merge_max_distance", 1.0, 5000.0),
                    ("merge_max_speed_ratio", 0.0, 10.0),
                    ("exclude_bottom", 0.0, 0.5),
                ]
                for key, lo, hi in float_fields:
                    if key not in payload:
                        continue
                    value = float(payload.get(key))
                    value = max(lo, min(hi, value))
                    if key == "exclude_bottom":
                        params.exclude_bottom_ratio = value
                    else:
                        setattr(params, key, value)
                    current_settings[key] = value

                int_fields = [
                    ("diff_threshold", 1, 255),
                    ("min_brightness", 1, 255),
                    ("min_brightness_tracking", 1, 255),
                    ("min_length", 1, 20000),
                    ("max_length", 1, 50000),
                    ("min_area", 1, 100000),
                    ("max_area", 1, 1000000),
                    ("mask_dilate", 0, 500),
                ]
                for key, lo, hi in int_fields:
                    if key not in payload:
                        continue
                    value = int(payload.get(key))
                    value = max(lo, min(hi, value))
                    if key == "mask_dilate":
                        current_mask_dilate = value
                    else:
                        setattr(params, key, value)
                    current_settings[key] = value

                if "scale" in payload:
                    current_settings["scale"] = float(payload.get("scale"))
                if "buffer" in payload:
                    current_settings["buffer"] = float(payload.get("buffer"))

                if "min_brightness" in payload and "min_brightness_tracking" not in payload:
                    params.min_brightness_tracking = max(1, int(params.min_brightness * 0.8))
                    current_settings["min_brightness_tracking"] = int(params.min_brightness_tracking)

                current_settings.update(_collect_detector_settings(params))

                self.wfile.write(json.dumps({
                    "success": True,
                    "settings": current_settings,
                }).encode())
            except Exception as e:
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": str(e),
                }).encode())
            return

        self.send_response(404)
        self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def build_exclusion_mask(
    day_image_path: str,
    proc_size: Tuple[int, int],
    dilate_px: int = 20,
    save_path: Optional[Path] = None,
) -> Optional[np.ndarray]:
    """昼間画像から検出除外マスクを生成（空以外を除外）"""
    img = cv2.imread(day_image_path)
    if img is None:
        print(f"[WARN] マスク画像を読み込めません: {day_image_path}")
        return None

    proc_w, proc_h = proc_size
    resized = cv2.resize(img, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)

    # 青空（H:90-140）と白い雲（S低 & V高）を空として扱う
    sky_blue = cv2.inRange(hsv, (90, 20, 80), (140, 200, 255))
    sky_white = cv2.inRange(hsv, (0, 0, 160), (180, 40, 255))
    sky_mask = cv2.bitwise_or(sky_blue, sky_white)

    # 空は上端と連結している領域を優先
    num_labels, labels = cv2.connectedComponents(sky_mask)
    top_labels = set(labels[0, :]) - {0}
    if top_labels:
        sky_keep = np.isin(labels, list(top_labels)).astype(np.uint8) * 255
    else:
        sky_keep = sky_mask

    # 空以外を除外領域としてマスク化
    exclusion = cv2.bitwise_not(sky_keep)

    # 空の最下端より下はすべて除外（屋根・山・電柱などを確実にマスク）
    h, w = sky_keep.shape[:2]
    for x in range(w):
        ys = np.where(sky_keep[:, x] > 0)[0]
        if ys.size == 0:
            exclusion[:, x] = 255
        else:
            y_max = ys.max()
            if y_max + 1 < h:
                exclusion[y_max + 1:, x] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    exclusion = cv2.morphologyEx(exclusion, cv2.MORPH_CLOSE, kernel)
    if dilate_px > 0:
        dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_px, dilate_px))
        exclusion = cv2.dilate(exclusion, dilate_kernel)

    if save_path:
        try:
            cv2.imwrite(str(save_path), exclusion)
        except Exception:
            print(f"[WARN] マスク保存に失敗: {save_path}")

    return exclusion


def build_exclusion_mask_from_frame(
    frame: np.ndarray,
    proc_size: Tuple[int, int],
    dilate_px: int = 20,
    save_path: Optional[Path] = None,
) -> Optional[np.ndarray]:
    """現在フレームから検出除外マスクを生成（空以外を除外）"""
    if frame is None:
        return None
    proc_w, proc_h = proc_size
    resized = cv2.resize(frame, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)

    sky_blue = cv2.inRange(hsv, (90, 20, 80), (140, 200, 255))
    sky_white = cv2.inRange(hsv, (0, 0, 160), (180, 40, 255))
    sky_mask = cv2.bitwise_or(sky_blue, sky_white)

    num_labels, labels = cv2.connectedComponents(sky_mask)
    top_labels = set(labels[0, :]) - {0}
    if top_labels:
        sky_keep = np.isin(labels, list(top_labels)).astype(np.uint8) * 255
    else:
        sky_keep = sky_mask

    exclusion = cv2.bitwise_not(sky_keep)

    # 空の最下端より下はすべて除外（屋根・山・電柱などを確実にマスク）
    h, w = sky_keep.shape[:2]
    for x in range(w):
        ys = np.where(sky_keep[:, x] > 0)[0]
        if ys.size == 0:
            exclusion[:, x] = 255
        else:
            y_max = ys.max()
            if y_max + 1 < h:
                exclusion[y_max + 1:, x] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    exclusion = cv2.morphologyEx(exclusion, cv2.MORPH_CLOSE, kernel)
    if dilate_px > 0:
        dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_px, dilate_px))
        exclusion = cv2.dilate(exclusion, dilate_kernel)

    if save_path:
        try:
            cv2.imwrite(str(save_path), exclusion)
        except Exception:
            print(f"[WARN] マスク保存に失敗: {save_path}")

    return exclusion


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
    enable_time_window=False,
    latitude=35.3606,
    longitude=138.7274,
    timezone="Asia/Tokyo",
    fb_normalize=False,
    fb_delete_mov=False,
):
    """検出処理を行うワーカースレッド"""
    global current_frame, detection_count, last_frame_time, is_detecting_now, current_runtime_fps
    global current_detector, current_proc_size, current_mask_dilate, current_mask_save
    global current_output_dir, current_camera_name

    width, height = reader.frame_size
    proc_width = int(width * process_scale)
    proc_height = int(height * process_scale)
    scale_factor = 1.0 / process_scale

    ring_buffer = RingBuffer(buffer_seconds, fps)
    exclusion_mask = None
    persistent_mask_path = None
    if output_path:
        persistent_mask_path = Path(output_path) / "masks" / f"{camera_name}_mask.png"
        if persistent_mask_path.exists():
            # /update_mask で更新した永続マスクを最優先する（再起動後も維持）
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

    detector = RealtimeMeteorDetector(params, fps, exclusion_mask=exclusion_mask)
    merger = EventMerger(params)
    current_detector = detector
    current_proc_size = (proc_width, proc_height)
    current_mask_dilate = mask_dilate
    current_mask_save = mask_save
    current_output_dir = Path(output_path)
    current_camera_name = camera_name

    prev_gray = None
    frame_count = 0
    recent_frame_times: List[float] = []

    # 天文薄暮期間のチェック（ウィンドウ終了後に再計算）
    is_detection_time = True  # デフォルトは有効
    detection_start = None
    detection_end = None
    if enable_time_window and is_detection_active:
        is_detection_time, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)

    while not stop_flag.is_set():
        ret, timestamp, frame = reader.read()
        if not ret:
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

        if prev_gray is not None:
            # 検出期間内の場合のみ検出処理を実行
            if is_detection_time:
                # アクティブなトラックがある場合は追跡モードを有効化
                tracking_mode = len(detector.active_tracks) > 0
                objects = detector.detect_bright_objects(gray, prev_gray, tracking_mode=tracking_mode)
                is_detecting_now = True
            else:
                objects = []
                is_detecting_now = False

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
                        extract_clips=bool(current_settings.get("extract_clips", extract_clips)),
                        clip_margin_before=1.0,
                        clip_margin_after=1.0,
                        composite_after=1.0,
                    )
                    if bool(current_settings.get("fb_normalize", fb_normalize)) and clip_path is not None:
                        fb_normalize_clip(
                            clip_path,
                            delete_source=bool(current_settings.get("fb_delete_mov", fb_delete_mov)),
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
                    extract_clips=bool(current_settings.get("extract_clips", extract_clips)),
                    clip_margin_before=1.0,
                    clip_margin_after=1.0,
                    composite_after=1.0,
                )
                if bool(current_settings.get("fb_normalize", fb_normalize)) and clip_path is not None:
                    fb_normalize_clip(
                        clip_path,
                        delete_source=bool(current_settings.get("fb_delete_mov", fb_delete_mov)),
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
            cv2.putText(display, f"{camera_name} | {elapsed:.0f}s | Detections: {detection_count}",
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            with current_frame_lock:
                current_frame = display

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
                extract_clips=bool(current_settings.get("extract_clips", extract_clips)),
                clip_margin_before=1.0,
                clip_margin_after=1.0,
                composite_after=1.0,
            )
            if bool(current_settings.get("fb_normalize", fb_normalize)) and clip_path is not None:
                fb_normalize_clip(
                    clip_path,
                    delete_source=bool(current_settings.get("fb_delete_mov", fb_delete_mov)),
                )

    for event in merger.flush_all():
        detection_count += 1
        clip_path = save_meteor_event(
            event,
            ring_buffer,
            output_path,
            fps=fps,
            extract_clips=bool(current_settings.get("extract_clips", extract_clips)),
            clip_margin_before=1.0,
            clip_margin_after=1.0,
            composite_after=1.0,
        )
        if bool(current_settings.get("fb_normalize", fb_normalize)) and clip_path is not None:
            fb_normalize_clip(
                clip_path,
                delete_source=bool(current_settings.get("fb_delete_mov", fb_delete_mov)),
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
    fb_normalize: bool = False,
    fb_delete_mov: bool = False,
):
    global current_frame, detection_count, start_time_global, camera_name, current_settings
    global current_runtime_fps
    global current_stop_flag

    params = params or DetectionParams()
    camera_name = cam_name

    sensitivity = _apply_sensitivity_params(params, sensitivity)

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
        "fb_normalize": fb_normalize,
        "source_fps": 30.0,
        "mask_image": mask_image or "",
        "mask_from_day": mask_from_day or "",
        "mask_dilate": mask_dilate,
    })
    current_settings.update(_collect_detector_settings(params))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"RTSPストリーム: {url}")
    print(f"出力先: {output_path}")
    if web_port > 0:
        print(f"Webプレビュー: http://0.0.0.0:{web_port}/")

    # Webサーバー起動
    httpd = None
    if web_port > 0:
        httpd = ThreadedHTTPServer(('0.0.0.0', web_port), MJPEGHandler)
        web_thread = Thread(target=httpd.serve_forever, daemon=True)
        web_thread.start()

    reader = RTSPReader(url)
    print("接続中...")
    reader.start()

    if not reader.connected.is_set():
        print("接続失敗")
        return

    width, height = reader.frame_size
    fps = sanitize_fps(reader.fps, default=30.0)

    current_settings["source_fps"] = fps

    print(f"解像度: {width}x{height}")
    print("検出開始 (Ctrl+C で終了)")
    print("-" * 50)

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
        print(f"検出時間制限: 有効（緯度: {latitude}, 経度: {longitude}）")
    else:
        print(f"検出時間制限: 無効（常時検出）")

    # 検出処理を別スレッドで実行
    detection_thread = Thread(
        target=detection_thread_worker,
        args=(reader, params, process_scale, effective_buffer_seconds, fps, output_path, extract_clips, stop_flag),
        kwargs={
            'mask_image': mask_image,
            'mask_from_day': mask_from_day,
            'mask_dilate': mask_dilate,
            'mask_save': Path(mask_save) if mask_save else None,
            'enable_time_window': enable_time_window,
            'latitude': latitude,
            'longitude': longitude,
            'timezone': timezone,
            'fb_normalize': fb_normalize,
            'fb_delete_mov': fb_delete_mov,
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

    reader.stop()
    if httpd:
        httpd.shutdown()
    current_stop_flag = None

    print(f"\n終了 - 検出数: {detection_count}個")


def main():
    parser = argparse.ArgumentParser(description="RTSPストリーム流星検出（Webプレビュー付き）")

    parser.add_argument("url", help="RTSP URL")
    parser.add_argument("-o", "--output", default="meteor_detections", help="出力ディレクトリ")
    parser.add_argument("--sensitivity", choices=["low", "medium", "high", "fireball"], default="medium")
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
    parser.add_argument("--fb-normalize", action="store_true",
                        help="Facebook向けにH.264 MP4へ正規化")
    parser.add_argument("--fb-delete-mov", action="store_true",
                        help="正規化後に元MOVを削除")

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
        fb_normalize=args.fb_normalize,
        fb_delete_mov=args.fb_delete_mov,
    )


if __name__ == "__main__":
    main()
