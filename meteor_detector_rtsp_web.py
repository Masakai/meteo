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
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
from collections import deque
from threading import Thread, Lock, Event
from queue import Queue, Empty
import json
from pathlib import Path
from datetime import datetime
import time
import signal
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

VERSION = "1.2.0"

# 天文薄暮期間の判定用
try:
    from astro_utils import is_detection_active
except ImportError:
    is_detection_active = None


@dataclass
class MeteorEvent:
    """検出された流星イベント"""
    timestamp: datetime
    start_time: float
    end_time: float
    start_point: Tuple[int, int]
    end_point: Tuple[int, int]
    peak_brightness: float
    confidence: float
    frames: List[Tuple[float, np.ndarray]]

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def length(self) -> float:
        dx = self.end_point[0] - self.start_point[0]
        dy = self.end_point[1] - self.start_point[1]
        return np.sqrt(dx**2 + dy**2)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "duration": round(self.duration, 3),
            "start_point": self.start_point,
            "end_point": self.end_point,
            "length_pixels": round(self.length, 1),
            "peak_brightness": round(self.peak_brightness, 1),
            "confidence": round(self.confidence, 2),
        }


@dataclass
class DetectionParams:
    """検出パラメータ"""
    diff_threshold: int = 30
    min_brightness: int = 200
    min_brightness_tracking: int = 150  # 追跡中は低い閾値で検出
    min_length: int = 20
    max_length: int = 5000
    min_duration: float = 0.1
    max_duration: float = 10.0
    min_speed: float = 50.0
    min_linearity: float = 0.7
    min_area: int = 5
    max_area: int = 10000
    max_gap_time: float = 2.0  # 流星が消えていく過程を追跡するため延長（1.0→2.0秒）
    max_distance: float = 80
    exclude_bottom_ratio: float = 1/16


class RingBuffer:
    """リングバッファ"""
    def __init__(self, max_seconds: float, fps: float = 30):
        self.max_frames = int(max_seconds * fps)
        self.buffer: deque = deque(maxlen=self.max_frames)
        self.lock = Lock()

    def add(self, timestamp: float, frame: np.ndarray):
        with self.lock:
            self.buffer.append((timestamp, frame.copy()))

    def get_range(self, start_time: float, end_time: float) -> List[Tuple[float, np.ndarray]]:
        with self.lock:
            return [(t, f.copy()) for t, f in self.buffer if start_time <= t <= end_time]


class RTSPReader:
    """RTSPストリーム読み込み"""
    def __init__(self, url: str, reconnect_delay: float = 5.0):
        self.url = url
        self.reconnect_delay = reconnect_delay
        self.queue = Queue(maxsize=30)
        self.stopped = Event()
        self.connected = Event()
        self.thread = None
        self.fps = 30.0
        self.width = 0
        self.height = 0
        self.start_time = None
        self.lock = Lock()

    def start(self):
        self.thread = Thread(target=self._read_loop, daemon=True)
        self.thread.start()
        self.connected.wait(timeout=10)
        return self

    def _read_loop(self):
        while not self.stopped.is_set():
            cap = cv2.VideoCapture(self.url)
            if not cap.isOpened():
                print(f"接続失敗: {self.url}")
                time.sleep(self.reconnect_delay)
                continue

            with self.lock:
                self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                if self.start_time is None:
                    self.start_time = time.time()

            print(f"接続成功: {self.width}x{self.height} @ {self.fps:.1f}fps")
            self.connected.set()

            consecutive_failures = 0
            while not self.stopped.is_set():
                ret, frame = cap.read()
                if not ret:
                    consecutive_failures += 1
                    if consecutive_failures > 30:
                        break
                    time.sleep(0.01)
                    continue

                consecutive_failures = 0
                timestamp = time.time() - self.start_time

                if self.queue.full():
                    try:
                        self.queue.get_nowait()
                    except Empty:
                        pass
                self.queue.put((timestamp, frame))

            cap.release()
            self.connected.clear()
            if not self.stopped.is_set():
                time.sleep(self.reconnect_delay)

    def read(self) -> Tuple[bool, float, Optional[np.ndarray]]:
        if self.stopped.is_set():
            return False, 0, None
        try:
            timestamp, frame = self.queue.get(timeout=1.0)
            return True, timestamp, frame
        except Empty:
            return True, 0, None

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=2.0)

    @property
    def frame_size(self):
        with self.lock:
            return (self.width, self.height)


class RealtimeMeteorDetector:
    """リアルタイム流星検出器"""
    def __init__(self, params: DetectionParams, fps: float = 30, exclusion_mask: Optional[np.ndarray] = None):
        self.params = params
        self.fps = fps
        self.exclusion_mask = exclusion_mask
        self.active_tracks: Dict[int, List[Tuple[float, int, int, float]]] = {}
        self.next_track_id = 0
        self.lock = Lock()
        self.mask_lock = Lock()

    def detect_bright_objects(self, frame: np.ndarray, prev_frame: np.ndarray, tracking_mode: bool = False) -> List[dict]:
        """
        明るい移動物体を検出

        Args:
            frame: 現在のフレーム
            prev_frame: 前のフレーム
            tracking_mode: True の場合、追跡中物体のために低い閾値で検出
        """
        height = frame.shape[0]
        max_y = int(height * (1 - self.params.exclude_bottom_ratio))

        diff = cv2.absdiff(frame, prev_frame)
        _, thresh = cv2.threshold(diff, self.params.diff_threshold, 255, cv2.THRESH_BINARY)
        thresh[max_y:, :] = 0
        with self.mask_lock:
            mask = self.exclusion_mask
        if mask is not None:
            thresh[mask > 0] = 0

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 追跡中は低い閾値を使用
        min_brightness = self.params.min_brightness_tracking if tracking_mode else self.params.min_brightness

        objects = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if not (self.params.min_area <= area <= self.params.max_area):
                continue

            M = cv2.moments(contour)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])

            if cy >= max_y:
                continue

            mask = np.zeros(frame.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            brightness = cv2.mean(frame, mask=mask)[0]

            if brightness >= min_brightness:
                objects.append({
                    "centroid": (cx, cy),
                    "area": area,
                    "brightness": brightness,
                })

        return objects

    def track_objects(self, objects: List[dict], timestamp: float) -> List[MeteorEvent]:
        completed_events = []
        used_objects = set()

        with self.lock:
            tracks_to_remove = []
            for track_id, track_points in self.active_tracks.items():
                if not track_points:
                    continue

                last_time, last_x, last_y, _ = track_points[-1]
                gap = timestamp - last_time

                if gap > self.params.max_gap_time:
                    tracks_to_remove.append(track_id)
                    continue

                best_match = None
                best_dist = float('inf')

                for i, obj in enumerate(objects):
                    if i in used_objects:
                        continue

                    cx, cy = obj["centroid"]
                    dist = np.sqrt((cx - last_x)**2 + (cy - last_y)**2)

                    if len(track_points) >= 2:
                        prev_time, prev_x, prev_y, _ = track_points[-2]
                        dt = last_time - prev_time
                        if dt > 0:
                            vx = (last_x - prev_x) / dt
                            vy = (last_y - prev_y) / dt
                            pred_x = last_x + vx * gap
                            pred_y = last_y + vy * gap
                            pred_dist = np.sqrt((cx - pred_x)**2 + (cy - pred_y)**2)
                            dist = min(dist, pred_dist)

                    if dist < self.params.max_distance and dist < best_dist:
                        best_dist = dist
                        best_match = i

                if best_match is not None:
                    obj = objects[best_match]
                    cx, cy = obj["centroid"]
                    track_points.append((timestamp, cx, cy, obj["brightness"]))
                    used_objects.add(best_match)

            for track_id in tracks_to_remove:
                event = self._finalize_track(track_id)
                if event:
                    completed_events.append(event)

            for i, obj in enumerate(objects):
                if i not in used_objects:
                    cx, cy = obj["centroid"]
                    self.active_tracks[self.next_track_id] = [
                        (timestamp, cx, cy, obj["brightness"])
                    ]
                    self.next_track_id += 1

        return completed_events

    def _finalize_track(self, track_id: int) -> Optional[MeteorEvent]:
        if track_id not in self.active_tracks:
            return None

        track_points = self.active_tracks.pop(track_id)
        times = [p[0] for p in track_points]
        duration = max(times) - min(times)

        if not (self.params.min_duration <= duration <= self.params.max_duration):
            return None

        xs = [p[1] for p in track_points]
        ys = [p[2] for p in track_points]
        brightness = [p[3] for p in track_points]

        start_idx = times.index(min(times))
        end_idx = times.index(max(times))
        start_point = (xs[start_idx], ys[start_idx])
        end_point = (xs[end_idx], ys[end_idx])

        length = np.sqrt((end_point[0] - start_point[0])**2 +
                        (end_point[1] - start_point[1])**2)

        if not (self.params.min_length <= length <= self.params.max_length):
            return None

        speed = length / max(0.001, duration)
        if speed < self.params.min_speed:
            return None

        linearity = self._calculate_linearity(xs, ys)
        if linearity < self.params.min_linearity:
            return None

        confidence = self._calculate_confidence(length, speed, linearity, max(brightness), duration)

        return MeteorEvent(
            timestamp=datetime.now(),
            start_time=min(times),
            end_time=max(times),
            start_point=start_point,
            end_point=end_point,
            peak_brightness=max(brightness),
            confidence=confidence,
            frames=[],
        )

    def _calculate_linearity(self, xs: List[int], ys: List[int]) -> float:
        if len(xs) < 3:
            return 1.0
        xs = np.array(xs)
        ys = np.array(ys)
        points = np.column_stack([xs, ys])
        centroid = np.mean(points, axis=0)
        centered = points - centroid
        cov = np.cov(centered.T)
        eigenvalues = np.linalg.eigvalsh(cov)
        eigenvalues = np.sort(eigenvalues)[::-1]
        if eigenvalues[0] == 0:
            return 0.0
        return eigenvalues[0] / (eigenvalues[0] + eigenvalues[1] + 1e-10)

    def _calculate_confidence(self, length, speed, linearity, brightness, duration) -> float:
        length_score = min(1.0, length / 100)
        speed_score = min(1.0, speed / 500)
        linearity_score = linearity
        brightness_score = min(1.0, brightness / 255)
        duration_bonus = min(0.2, duration * 0.1)
        return min(1.0, length_score * 0.25 + speed_score * 0.2 +
                   linearity_score * 0.25 + brightness_score * 0.2 + duration_bonus)

    def finalize_all(self) -> List[MeteorEvent]:
        events = []
        with self.lock:
            for track_id in list(self.active_tracks.keys()):
                event = self._finalize_track(track_id)
                if event:
                    events.append(event)
        return events

    def update_exclusion_mask(self, new_mask: Optional[np.ndarray]) -> None:
        with self.mask_lock:
            self.exclusion_mask = new_mask


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
current_mask_dilate = 5
current_mask_save = None
current_output_dir = None
current_camera_name = ""
# 設定情報（ダッシュボード表示用）
current_settings = {
    "sensitivity": "medium",
    "scale": 0.5,
    "buffer": 15.0,
    "extract_clips": True,
    "exclude_bottom": 0.0625,
}


class MJPEGHandler(BaseHTTPRequestHandler):
    """MJPEG ストリーミングハンドラ"""

    def log_message(self, format, *args):
        pass  # ログを抑制

    def do_GET(self):
        if self.path == '/':
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
        }}
        .video img {{ width: 100%; display: block; }}
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
    </style>
</head>
<body>
    <div class="container">
        <h1>Meteor Detector - {camera_name}</h1>
        <div class="video">
            <img src="/stream" alt="Live Stream">
        </div>
        <div class="stats">
            <span>Status: <b style="color:#00ff88">RUNNING</b></span>
            <span>Detections: <b class="count" id="count">-</b></span>
        </div>
        <p style="color:#888; margin-top:20px;">
            緑丸: 検出中の物体 / 黄線: 追跡中の軌跡 / 赤表示: 流星検出
        </p>
    </div>
    <script>
        setInterval(() => {{
            fetch('/stats').then(r => r.json()).then(data => {{
                document.getElementById('count').textContent = data.detections;
            }});
        }}, 1000);
    </script>
</body>
</html>'''
            self.wfile.write(html.encode())

        elif self.path == '/stream':
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

        elif self.path == '/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            elapsed = time.time() - start_time_global if start_time_global else 0
            current_time = time.time()
            time_since_last_frame = current_time - last_frame_time if last_frame_time > 0 else 0
            is_stream_alive = time_since_last_frame < stream_timeout
            stats = {
                "detections": detection_count,
                "elapsed": round(elapsed, 1),
                "camera": camera_name,
                "settings": current_settings,
                "stream_alive": is_stream_alive,
                "time_since_last_frame": round(time_since_last_frame, 1),
                "is_detecting": is_detecting_now,
            }
            self.wfile.write(json.dumps(stats).encode())

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

            save_path = None
            if current_output_dir and current_camera_name:
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

        self.send_response(404)
        self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def build_exclusion_mask(
    day_image_path: str,
    proc_size: Tuple[int, int],
    dilate_px: int = 5,
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
    dilate_px: int = 5,
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


def save_meteor_event(event, ring_buffer, output_dir, fps=30, extract_clips=True):
    """流星イベントを保存"""
    start = max(0, event.start_time - 1.0)
    end = event.end_time + 2.0
    frames = ring_buffer.get_range(start, end)

    if not frames:
        return

    ts = event.timestamp.strftime("%Y%m%d_%H%M%S")
    base_name = f"meteor_{ts}"

    height, width = frames[0][1].shape[:2]

    # クリップ動画の保存
    if extract_clips:
        clip_path = output_dir / f"{base_name}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(str(clip_path), fourcc, fps, (width, height))

        for _, frame in frames:
            writer.write(frame)
        writer.release()

    # 合成画像用のフレーム範囲を拡張（終了時刻+1秒）
    composite_end = min(event.end_time + 1.0, end)
    event_frames = ring_buffer.get_range(event.start_time, composite_end)
    if event_frames:
        composite = event_frames[0][1].astype(np.float32)
        for _, f in event_frames[1:]:
            composite = np.maximum(composite, f.astype(np.float32))
        composite = np.clip(composite, 0, 255).astype(np.uint8)

        marked = composite.copy()
        cv2.line(marked, event.start_point, event.end_point, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(marked, event.start_point, 6, (0, 255, 0), 2)
        cv2.circle(marked, event.end_point, 6, (0, 0, 255), 2)

        cv2.imwrite(str(output_dir / f"{base_name}_composite.jpg"), marked)
        cv2.imwrite(str(output_dir / f"{base_name}_composite_original.jpg"), composite)

    log_path = output_dir / "detections.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    if extract_clips:
        print(f"  保存: {clip_path.name}")
    else:
        print(f"  保存: {base_name}_composite.jpg")


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
):
    """検出処理を行うワーカースレッド"""
    global current_frame, detection_count, last_frame_time, is_detecting_now
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

    detector = RealtimeMeteorDetector(params, fps, exclusion_mask=exclusion_mask)
    current_detector = detector
    current_proc_size = (proc_width, proc_height)
    current_mask_dilate = mask_dilate
    current_mask_save = mask_save
    current_output_dir = Path(output_path)
    current_camera_name = camera_name

    prev_gray = None
    frame_count = 0

    # 天文薄暮期間のチェック間隔（秒）
    last_time_check = 0
    time_check_interval = 60  # 1分ごとにチェック
    is_detection_time = True  # デフォルトは有効

    while not stop_flag.is_set():
        ret, timestamp, frame = reader.read()
        if not ret:
            break
        if frame is None:
            continue

        # ストリーム生存確認用の時刻を更新
        last_frame_time = time.time()

        ring_buffer.add(timestamp, frame)

        if process_scale != 1.0:
            proc_frame = cv2.resize(frame, (proc_width, proc_height), interpolation=cv2.INTER_AREA)
        else:
            proc_frame = frame

        gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)

        # 天文薄暮期間のチェック（定期的に）
        current_time = time.time()
        if enable_time_window and is_detection_active and (current_time - last_time_check) > time_check_interval:
            is_detection_time, _, _ = is_detection_active(latitude, longitude, timezone)
            last_time_check = current_time

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
                detection_count += 1
                print(f"\n[{event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
                print(f"  長さ: {event.length:.1f}px, 時間: {event.duration:.2f}秒")
                save_meteor_event(event, ring_buffer, output_path, fps=fps, extract_clips=extract_clips)

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
        detection_count += 1
        save_meteor_event(event, ring_buffer, output_path, fps=fps, extract_clips=extract_clips)


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
):
    global current_frame, detection_count, start_time_global, camera_name, current_settings

    params = params or DetectionParams()
    camera_name = cam_name

    # 設定情報を更新（ダッシュボード表示用）
    current_settings.update({
        "sensitivity": sensitivity,
        "scale": process_scale,
        "buffer": buffer_seconds,
        "extract_clips": extract_clips,
        "exclude_bottom": params.exclude_bottom_ratio,
        "mask_image": mask_image or "",
        "mask_from_day": mask_from_day or "",
        "mask_dilate": mask_dilate,
    })

    if sensitivity == "low":
        params.diff_threshold = 40
        params.min_brightness = 220
    elif sensitivity == "high":
        params.diff_threshold = 20
        params.min_brightness = 180
    elif sensitivity == "fireball":
        params.diff_threshold = 15
        params.min_brightness = 150
        params.max_duration = 20.0
        params.min_speed = 20.0
        params.min_linearity = 0.6

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
    fps = reader.fps

    print(f"解像度: {width}x{height}")
    print("検出開始 (Ctrl+C で終了)")
    print("-" * 50)

    detection_count = 0
    start_time_global = time.time()

    stop_flag = Event()

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
        args=(reader, params, process_scale, buffer_seconds, fps, output_path, extract_clips, stop_flag),
        kwargs={
            'mask_image': mask_image,
            'mask_from_day': mask_from_day,
            'mask_dilate': mask_dilate,
            'mask_save': Path(mask_save) if mask_save else None,
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

    reader.stop()
    if httpd:
        httpd.shutdown()

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
                        help="流星検出時にMP4クリップを保存 (デフォルト: 有効)")
    parser.add_argument("--no-clips", action="store_true",
                        help="MP4クリップを保存しない（コンポジット画像のみ）")
    parser.add_argument("--mask-image", help="作成済みの除外マスク画像を使用（優先）")
    parser.add_argument("--mask-from-day", help="昼間画像から検出除外マスクを生成（空以外を除外）")
    parser.add_argument("--mask-dilate", type=int, default=5, help="除外マスクの拡張ピクセル数")
    parser.add_argument("--mask-save", help="生成した除外マスク画像の保存先")

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
    )


if __name__ == "__main__":
    main()
