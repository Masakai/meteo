"""
RTSPリアルタイム検出の共通コンポーネント

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from collections import deque
from threading import Thread, Lock, Event
from queue import Queue, Empty
import json
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

import cv2
import numpy as np

from meteor_detector_common import calculate_linearity, calculate_confidence, open_video_writer


def write_mp4_clip_ffmpeg(
    output_path: Path,
    frames: List[Tuple[float, np.ndarray]],
    *,
    fps: float,
    size: Tuple[int, int],
) -> bool:
    """ffmpegで目的メタデータに近いMP4を直接出力する。"""
    width, height = size
    target_fps = sanitize_fps(fps, default=30.0)
    target_fps = 30.0 if abs(target_fps - 30.0) > 0.01 else 30.0
    gop = int(target_fps * 2)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{target_fps:.0f}",
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-profile:v",
        "baseline",
        "-level",
        "4.0",
        "-pix_fmt",
        "yuv420p",
        "-bf",
        "0",
        "-refs",
        "1",
        "-coder",
        "0",
        "-x264-params",
        "cabac=0:ref=1:bframes=0:weightp=0:8x8dct=0:force-cfr=1",
        "-fps_mode",
        "cfr",
        "-g",
        str(gop),
        "-keyint_min",
        str(gop),
        "-sc_threshold",
        "0",
        "-video_track_timescale",
        "15360",
        "-tag:v",
        "avc1",
        "-brand",
        "isom",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return False
    except Exception:
        return False

    try:
        assert proc.stdin is not None
        for _, frame in frames:
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        stderr = b""
        if proc.stderr is not None:
            stderr = proc.stderr.read()
        proc.wait()
    except Exception:
        proc.kill()
        proc.wait()
        return False

    if proc.returncode != 0:
        if stderr:
            sys.stderr.write(stderr.decode("utf-8", errors="ignore"))
        return False
    return True


def write_clip_with_fallback(
    output_path: Path,
    frames: List[Tuple[float, np.ndarray]],
    *,
    fps: float,
    size: Tuple[int, int],
) -> bool:
    """ffmpeg優先でMP4を書き出し、失敗時のみOpenCVへフォールバックする。"""
    if write_mp4_clip_ffmpeg(output_path, frames, fps=fps, size=size):
        return True

    writer = open_video_writer(output_path, fps, size)
    if writer is None:
        return False
    for _, frame in frames:
        writer.write(frame)
    writer.release()
    return True


def sanitize_fps(value: Optional[float], default: float = 30.0) -> float:
    """FPS値を実用範囲に正規化"""
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(fps):
        return default
    if fps < 1.0 or fps > 120.0:
        return default
    return fps


def estimate_fps_from_frames(
    frames: List[Tuple[float, np.ndarray]],
    fallback_fps: float = 30.0,
) -> float:
    """フレーム時刻差の中央値から実効FPSを推定"""
    if len(frames) < 2:
        return sanitize_fps(fallback_fps, default=30.0)

    deltas: List[float] = []
    for idx in range(1, len(frames)):
        dt = frames[idx][0] - frames[idx - 1][0]
        if dt > 0:
            deltas.append(dt)

    if not deltas:
        return sanitize_fps(fallback_fps, default=30.0)

    median_dt = float(np.median(np.array(deltas, dtype=np.float64)))
    if median_dt <= 0:
        return sanitize_fps(fallback_fps, default=30.0)

    return sanitize_fps(1.0 / median_dt, default=sanitize_fps(fallback_fps, default=30.0))


def probe_rtsp_endpoint(url: str, timeout: float = 3.0) -> str:
    """RTSP先の host:port 到達性を簡易診断して文字列で返す。"""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = int(parsed.port or 554)
    except Exception as e:
        return f"probe=invalid_url error={e}"

    if not host:
        return "probe=invalid_url error=missing_host"

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return f"probe=tcp_ok host={host} port={port}"
    except Exception as e:
        return f"probe=tcp_error host={host} port={port} error={type(e).__name__}: {e}"


def probe_rtsp_with_ffprobe(url: str, timeout: float = 8.0) -> str:
    """ffprobe で RTSP セッション開始可否を簡易診断する。"""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-show_streams",
        url,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return "ffprobe=missing"
    except subprocess.TimeoutExpired:
        return f"ffprobe=timeout timeout={timeout}s"
    except Exception as e:
        return f"ffprobe=error error={type(e).__name__}: {e}"

    if result.returncode == 0:
        return "ffprobe=ok"

    detail = (result.stderr or result.stdout or "").strip().replace("\n", " | ")
    if not detail:
        detail = f"returncode={result.returncode}"
    return f"ffprobe=error detail={detail}"


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
    min_brightness_tracking: Optional[int] = None
    min_length: int = 20
    max_length: int = 5000
    min_duration: float = 0.1
    max_duration: float = 10.0
    min_speed: float = 50.0
    min_linearity: float = 0.7
    min_area: int = 5
    max_area: int = 10000
    max_gap_time: float = 2.0
    max_distance: float = 80
    merge_max_gap_time: float = 1.5
    merge_max_distance: float = 80
    merge_max_speed_ratio: float = 0.5
    exclude_bottom_ratio: float = 1 / 16
    exclude_edge_ratio: float = 0.0  # 四辺から除外する割合（0.0〜0.5）。UIからはpx指定→ratio変換で設定される。例: 20px / min(幅,高さ)
    nuisance_overlap_threshold: float = 0.60
    nuisance_path_overlap_threshold: float = 0.70
    min_track_points: int = 4
    max_stationary_ratio: float = 0.40
    small_area_threshold: int = 40

    def __post_init__(self):
        if self.min_brightness_tracking is None:
            self.min_brightness_tracking = self.min_brightness


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

    def __init__(self, url: str, reconnect_delay: float = 5.0, log_detail: bool = False):
        self.url = url
        self.reconnect_delay = reconnect_delay
        self.log_detail = log_detail
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
        attempt = 0
        while not self.stopped.is_set():
            attempt += 1
            cap = cv2.VideoCapture(self.url)

            if not cap.isOpened():
                probe = probe_rtsp_endpoint(self.url)
                print(f"接続失敗: {self.url} ({probe}, attempt={attempt})", flush=True)
                if self.log_detail:
                    if attempt <= 3 or (attempt % 12) == 0:
                        ffprobe_detail = probe_rtsp_with_ffprobe(self.url)
                        print(f"RTSP詳細診断: {ffprobe_detail}", flush=True)
                    print("OpenCVがRTSPセッションを開始できませんでした。認証情報、URLパス、RTSPポート、カメラ側同時接続数を確認してください。", flush=True)
                    print(f"{self.reconnect_delay}秒後に再接続...", flush=True)
                time.sleep(self.reconnect_delay)
                continue

            with self.lock:
                self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.fps = sanitize_fps(cap.get(cv2.CAP_PROP_FPS), default=30.0)
                if self.start_time is None:
                    self.start_time = time.time()

            print(f"接続成功: {self.width}x{self.height} @ {self.fps:.1f}fps", flush=True)
            attempt = 0
            self.connected.set()

            consecutive_failures = 0
            while not self.stopped.is_set():
                ret, frame = cap.read()

                if not ret:
                    consecutive_failures += 1
                    if consecutive_failures > 30:
                        if self.log_detail:
                            print("ストリーム切断を検出", flush=True)
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
                if self.log_detail:
                    print(f"{self.reconnect_delay}秒後に再接続...", flush=True)
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

    CONF_SPEED_NORM = 500.0
    CONF_DURATION_NORM = 1.0
    CONF_DURATION_SCALE = 0.1
    CONF_DURATION_MAX = 0.2

    def __init__(
        self,
        params: DetectionParams,
        fps: float = 30,
        exclusion_mask: Optional[np.ndarray] = None,
        nuisance_mask: Optional[np.ndarray] = None,
    ):
        self.params = params
        self.fps = fps
        self.exclusion_mask = exclusion_mask
        self.nuisance_mask = nuisance_mask
        self.active_tracks: Dict[int, List[Tuple[float, int, int, float]]] = {}
        self.next_track_id = 0
        self.lock = Lock()
        self.mask_lock = Lock()

    def detect_bright_objects(self, frame: np.ndarray, prev_frame: np.ndarray, tracking_mode: bool = False) -> List[dict]:
        """明るい移動物体を検出"""
        height = frame.shape[0]
        width = frame.shape[1]
        max_y = int(height * (1 - self.params.exclude_bottom_ratio))

        diff = cv2.absdiff(frame, prev_frame)
        _, thresh = cv2.threshold(diff, self.params.diff_threshold, 255, cv2.THRESH_BINARY)
        thresh[max_y:, :] = 0
        # 画像周辺の固定ノイズを除外
        edge = max(0, int(min(width, height) * self.params.exclude_edge_ratio))
        if edge > 0:
            thresh[:edge, :] = 0
            thresh[height - edge:, :] = 0
            thresh[:, :edge] = 0
            thresh[:, width - edge:] = 0
        with self.mask_lock:
            exclusion_mask = self.exclusion_mask
            nuisance_mask = self.nuisance_mask
        if exclusion_mask is not None:
            thresh[exclusion_mask > 0] = 0

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

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

            mask_img = np.zeros(frame.shape, dtype=np.uint8)
            cv2.drawContours(mask_img, [contour], -1, 255, -1)
            brightness = cv2.mean(frame, mask=mask_img)[0]
            nuisance_overlap_ratio = 0.0
            if nuisance_mask is not None and area <= self.params.small_area_threshold:
                nuisance_overlap_ratio = self._calculate_mask_overlap_ratio(mask_img, nuisance_mask)
                if nuisance_overlap_ratio >= self.params.nuisance_overlap_threshold:
                    print(
                        f"[DEBUG] rejected_by=nuisance_overlap area={area:.1f} "
                        f"ratio={nuisance_overlap_ratio:.2f}"
                    )
                    continue

            if brightness >= min_brightness:
                objects.append({
                    "centroid": (cx, cy),
                    "area": area,
                    "brightness": brightness,
                    "nuisance_overlap_ratio": nuisance_overlap_ratio,
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
                best_dist = float("inf")

                for i, obj in enumerate(objects):
                    if i in used_objects:
                        continue

                    cx, cy = obj["centroid"]
                    dist = np.sqrt((cx - last_x) ** 2 + (cy - last_y) ** 2)

                    if len(track_points) >= 2:
                        prev_time, prev_x, prev_y, _ = track_points[-2]
                        dt = last_time - prev_time
                        if dt > 0:
                            vx = (last_x - prev_x) / dt
                            vy = (last_y - prev_y) / dt
                            pred_x = last_x + vx * gap
                            pred_y = last_y + vy * gap
                            pred_dist = np.sqrt((cx - pred_x) ** 2 + (cy - pred_y) ** 2)
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
        if len(track_points) < self.params.min_track_points:
            print(
                f"[DEBUG] rejected_by=min_track_points points={len(track_points)} "
                f"required={self.params.min_track_points}"
            )
            return None

        times = [p[0] for p in track_points]
        duration = max(times) - min(times)

        if not (self.params.min_duration <= duration <= self.params.max_duration):
            print(f"[DEBUG] rejected_by=duration duration={duration:.3f}")
            return None

        xs = [p[1] for p in track_points]
        ys = [p[2] for p in track_points]
        brightness = [p[3] for p in track_points]

        stationary_ratio = self._calculate_stationary_ratio(xs, ys)
        if stationary_ratio > self.params.max_stationary_ratio:
            print(
                f"[DEBUG] rejected_by=stationary_ratio ratio={stationary_ratio:.2f} "
                f"max={self.params.max_stationary_ratio:.2f}"
            )
            return None

        start_idx = times.index(min(times))
        end_idx = times.index(max(times))
        start_point = (xs[start_idx], ys[start_idx])
        end_point = (xs[end_idx], ys[end_idx])

        with self.mask_lock:
            nuisance_mask = self.nuisance_mask
        if nuisance_mask is not None:
            nuisance_path_overlap_ratio = self._calculate_line_overlap_ratio(
                nuisance_mask,
                start_point,
                end_point,
            )
            if nuisance_path_overlap_ratio > self.params.nuisance_path_overlap_threshold:
                print(
                    f"[DEBUG] rejected_by=nuisance_path_overlap ratio={nuisance_path_overlap_ratio:.2f} "
                    f"max={self.params.nuisance_path_overlap_threshold:.2f}"
                )
                return None

        length = np.sqrt((end_point[0] - start_point[0]) ** 2 +
                         (end_point[1] - start_point[1]) ** 2)

        if not (self.params.min_length <= length <= self.params.max_length):
            print(f"[DEBUG] rejected_by=length length={length:.1f}")
            return None

        speed = length / max(0.001, duration)
        if speed < self.params.min_speed:
            print(f"[DEBUG] rejected_by=speed speed={speed:.1f}")
            return None

        linearity = calculate_linearity(xs, ys)
        if linearity < self.params.min_linearity:
            print(f"[DEBUG] rejected_by=linearity linearity={linearity:.2f}")
            return None

        confidence = calculate_confidence(
            length,
            speed,
            linearity,
            max(brightness),
            duration,
            speed_norm=self.CONF_SPEED_NORM,
            duration_norm=self.CONF_DURATION_NORM,
            duration_bonus_scale=self.CONF_DURATION_SCALE,
            duration_bonus_max=self.CONF_DURATION_MAX,
        )

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

    def update_nuisance_mask(self, new_mask: Optional[np.ndarray]) -> None:
        with self.mask_lock:
            self.nuisance_mask = new_mask

    @staticmethod
    def _calculate_mask_overlap_ratio(candidate_mask: np.ndarray, nuisance_mask: np.ndarray) -> float:
        candidate_area = int(np.count_nonzero(candidate_mask))
        if candidate_area == 0:
            return 0.0
        overlap = int(np.count_nonzero((candidate_mask > 0) & (nuisance_mask > 0)))
        return overlap / candidate_area

    @staticmethod
    def _calculate_stationary_ratio(xs: List[int], ys: List[int], px_threshold: float = 2.0) -> float:
        if len(xs) < 2:
            return 1.0
        stationary = 0
        steps = len(xs) - 1
        for idx in range(1, len(xs)):
            dist = np.hypot(xs[idx] - xs[idx - 1], ys[idx] - ys[idx - 1])
            if dist <= px_threshold:
                stationary += 1
        return stationary / max(1, steps)

    @staticmethod
    def _calculate_line_overlap_ratio(
        nuisance_mask: np.ndarray,
        start_point: Tuple[int, int],
        end_point: Tuple[int, int],
    ) -> float:
        line_mask = np.zeros_like(nuisance_mask, dtype=np.uint8)
        cv2.line(line_mask, start_point, end_point, 255, 2, cv2.LINE_AA)
        line_pixels = int(np.count_nonzero(line_mask))
        if line_pixels == 0:
            return 0.0
        overlap = int(np.count_nonzero((line_mask > 0) & (nuisance_mask > 0)))
        return overlap / line_pixels


class EventMerger:
    """近接イベントを結合して1イベント化"""

    def __init__(self, params: DetectionParams):
        self.params = params
        self.pending: deque[MeteorEvent] = deque()

    def add_event(self, event: MeteorEvent) -> List[MeteorEvent]:
        finalized = []

        if self.pending and self._is_mergeable(self.pending[-1], event):
            self.pending[-1] = self._merge(self.pending[-1], event)
        else:
            self.pending.append(event)

        finalized.extend(self.flush_expired(event.start_time))
        return finalized

    def flush_expired(self, current_time: float) -> List[MeteorEvent]:
        finalized = []
        cutoff = current_time - self.params.merge_max_gap_time
        while self.pending and self.pending[0].end_time < cutoff:
            finalized.append(self.pending.popleft())
        return finalized

    def flush_all(self) -> List[MeteorEvent]:
        finalized = list(self.pending)
        self.pending.clear()
        return finalized

    def _is_mergeable(self, prev: MeteorEvent, new: MeteorEvent) -> bool:
        gap = new.start_time - prev.end_time
        if gap < 0 or gap > self.params.merge_max_gap_time:
            return False

        dist = np.hypot(
            new.start_point[0] - prev.end_point[0],
            new.start_point[1] - prev.end_point[1],
        )
        if dist > self.params.merge_max_distance:
            return False

        prev_speed = prev.length / max(prev.duration, 0.001)
        new_speed = new.length / max(new.duration, 0.001)
        max_speed = max(prev_speed, new_speed, 0.001)
        speed_ratio = abs(prev_speed - new_speed) / max_speed
        return speed_ratio <= self.params.merge_max_speed_ratio

    def _merge(self, prev: MeteorEvent, new: MeteorEvent) -> MeteorEvent:
        return MeteorEvent(
            timestamp=prev.timestamp,
            start_time=prev.start_time,
            end_time=new.end_time,
            start_point=prev.start_point,
            end_point=new.end_point,
            peak_brightness=max(prev.peak_brightness, new.peak_brightness),
            confidence=max(prev.confidence, new.confidence),
            frames=[],
        )


def make_detection_id(camera_name: str, record: dict) -> str:
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


def make_detection_base_name(output_dir: Path, timestamp: datetime, detection_id: str) -> str:
    stem = f"meteor_{timestamp.strftime('%Y%m%d_%H%M%S')}_{detection_id[4:12]}"
    candidate = stem
    suffix = 1
    while any(
        (output_dir / f"{candidate}{name_suffix}").exists()
        for name_suffix in (".mp4", ".mov", "_composite.jpg", "_composite_original.jpg")
    ):
        suffix += 1
        candidate = f"{stem}_{suffix:02d}"
    return candidate


def save_meteor_event(
    event: MeteorEvent,
    ring_buffer: RingBuffer,
    output_dir: Path,
    *,
    fps: float = 30,
    extract_clips: bool = True,
    clip_margin_before: float = 1.0,
    clip_margin_after: float = 1.0,
    composite_after: float = 1.0,
    overlay_text: Optional[str] = None,
    overlay_pos: Tuple[int, int] = (10, 30),
):
    """流星イベントを保存"""
    start = max(0, event.start_time - clip_margin_before)
    end = event.end_time + clip_margin_after
    frames = ring_buffer.get_range(start, end)

    if not frames:
        return None

    record = event.to_dict()
    camera_name = output_dir.name
    detection_id = make_detection_id(camera_name, record)
    base_name = make_detection_base_name(output_dir, event.timestamp, detection_id)

    height, width = frames[0][1].shape[:2]

    clip_fps = estimate_fps_from_frames(frames, fallback_fps=fps)

    clip_path = None
    if extract_clips:
        clip_path = output_dir / f"{base_name}.mp4"
        ok = write_clip_with_fallback(clip_path, frames, fps=clip_fps, size=(width, height))
        if not ok:
            print("[WARN] 動画エンコーダの初期化に失敗しました")
            return None

    composite_end = min(event.end_time + composite_after, end)
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

        if overlay_text:
            cv2.putText(
                marked,
                overlay_text,
                overlay_pos,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

        cv2.imwrite(str(output_dir / f"{base_name}_composite.jpg"), marked)
        cv2.imwrite(str(output_dir / f"{base_name}_composite_original.jpg"), composite)

    record["id"] = detection_id
    record["base_name"] = base_name
    if clip_path is not None:
        record["clip_path"] = clip_path.name
    composite_path = output_dir / f"{base_name}_composite.jpg"
    composite_original_path = output_dir / f"{base_name}_composite_original.jpg"
    if composite_path.exists():
        record["image_path"] = composite_path.name
    if composite_original_path.exists():
        record["composite_original_path"] = composite_original_path.name

    log_path = output_dir / "detections.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if extract_clips and clip_path is not None:
        print(f"  保存: {clip_path.name}")
    else:
        print(f"  保存: {base_name}_composite.jpg")
    return clip_path
