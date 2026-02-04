#!/usr/bin/env python3
"""
RTSPストリームからリアルタイムで流星を検出するプログラム

使い方:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream

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

VERSION = "1.2.0"
from pathlib import Path
from datetime import datetime
import time
import signal
import sys


@dataclass
class MeteorEvent:
    """検出された流星イベント"""
    timestamp: datetime
    start_time: float  # ストリーム開始からの秒数
    end_time: float
    start_point: Tuple[int, int]
    end_point: Tuple[int, int]
    peak_brightness: float
    confidence: float
    frames: List[Tuple[float, np.ndarray]]  # [(timestamp, frame), ...]

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
    min_length: int = 20
    max_length: int = 5000
    min_duration: float = 0.1  # 秒
    max_duration: float = 10.0  # 秒
    min_speed: float = 50.0  # ピクセル/秒
    min_linearity: float = 0.7
    min_area: int = 5
    max_area: int = 10000
    max_gap_time: float = 0.2  # 秒
    max_distance: float = 80
    exclude_bottom_ratio: float = 1/16


class RingBuffer:
    """リングバッファ（フレーム保持用）"""

    def __init__(self, max_seconds: float, fps: float = 30):
        self.max_frames = int(max_seconds * fps)
        self.buffer: deque = deque(maxlen=self.max_frames)
        self.lock = Lock()

    def add(self, timestamp: float, frame: np.ndarray):
        with self.lock:
            self.buffer.append((timestamp, frame.copy()))

    def get_range(self, start_time: float, end_time: float) -> List[Tuple[float, np.ndarray]]:
        """指定した時間範囲のフレームを取得"""
        with self.lock:
            return [(t, f.copy()) for t, f in self.buffer
                    if start_time <= t <= end_time]

    def get_all(self) -> List[Tuple[float, np.ndarray]]:
        with self.lock:
            return [(t, f.copy()) for t, f in self.buffer]


class RTSPReader:
    """RTSPストリーム読み込み（別スレッド）"""

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
        # 接続待ち
        self.connected.wait(timeout=10)
        return self

    def _read_loop(self):
        while not self.stopped.is_set():
            cap = cv2.VideoCapture(self.url)

            if not cap.isOpened():
                print(f"接続失敗: {self.url}")
                print(f"{self.reconnect_delay}秒後に再接続...")
                time.sleep(self.reconnect_delay)
                continue

            # ストリーム情報を取得
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
                        print("ストリーム切断を検出")
                        break
                    time.sleep(0.01)
                    continue

                consecutive_failures = 0
                timestamp = time.time() - self.start_time

                # キューが満杯なら古いフレームを破棄
                if self.queue.full():
                    try:
                        self.queue.get_nowait()
                    except Empty:
                        pass

                self.queue.put((timestamp, frame))

            cap.release()
            self.connected.clear()

            if not self.stopped.is_set():
                print(f"{self.reconnect_delay}秒後に再接続...")
                time.sleep(self.reconnect_delay)

    def read(self) -> Tuple[bool, float, Optional[np.ndarray]]:
        if self.stopped.is_set():
            return False, 0, None
        try:
            timestamp, frame = self.queue.get(timeout=1.0)
            return True, timestamp, frame
        except Empty:
            return True, 0, None  # タイムアウトだが継続

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

    def __init__(self, params: DetectionParams, fps: float = 30):
        self.params = params
        self.fps = fps
        self.active_tracks: Dict[int, List[Tuple[float, int, int, float]]] = {}
        self.next_track_id = 0
        self.lock = Lock()

    def detect_bright_objects(self, frame: np.ndarray, prev_frame: np.ndarray) -> List[dict]:
        """明るい移動物体を検出"""
        height = frame.shape[0]
        max_y = int(height * (1 - self.params.exclude_bottom_ratio))

        diff = cv2.absdiff(frame, prev_frame)
        _, thresh = cv2.threshold(diff, self.params.diff_threshold, 255, cv2.THRESH_BINARY)
        thresh[max_y:, :] = 0

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

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

            if brightness >= self.params.min_brightness:
                objects.append({
                    "centroid": (cx, cy),
                    "area": area,
                    "brightness": brightness,
                })

        return objects

    def track_objects(self, objects: List[dict], timestamp: float) -> List[MeteorEvent]:
        """物体を追跡し、完了したトラックを流星イベントとして返す"""
        completed_events = []
        used_objects = set()

        with self.lock:
            # 既存トラックとのマッチング
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

            # 終了したトラックを処理
            for track_id in tracks_to_remove:
                event = self._finalize_track(track_id)
                if event:
                    completed_events.append(event)

            # 新規トラック
            for i, obj in enumerate(objects):
                if i not in used_objects:
                    cx, cy = obj["centroid"]
                    self.active_tracks[self.next_track_id] = [
                        (timestamp, cx, cy, obj["brightness"])
                    ]
                    self.next_track_id += 1

        return completed_events

    def _finalize_track(self, track_id: int) -> Optional[MeteorEvent]:
        """トラックを終了して流星判定"""
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
            frames=[],  # 後でバッファから取得
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

    def _calculate_confidence(self, length: float, speed: float,
                             linearity: float, brightness: float,
                             duration: float) -> float:
        length_score = min(1.0, length / 100)
        speed_score = min(1.0, speed / 500)
        linearity_score = linearity
        brightness_score = min(1.0, brightness / 255)
        duration_bonus = min(0.2, duration * 0.1)

        return min(1.0, (
            length_score * 0.25 +
            speed_score * 0.2 +
            linearity_score * 0.25 +
            brightness_score * 0.2 +
            duration_bonus
        ))

    def finalize_all(self) -> List[MeteorEvent]:
        """全てのアクティブトラックを終了"""
        events = []
        with self.lock:
            for track_id in list(self.active_tracks.keys()):
                event = self._finalize_track(track_id)
                if event:
                    events.append(event)
        return events


def save_meteor_event(
    event: MeteorEvent,
    ring_buffer: RingBuffer,
    output_dir: Path,
    margin: float = 2.0,
    fps: float = 30,
):
    """流星イベントを保存"""
    # フレームを取得
    start = max(0, event.start_time - margin)
    end = event.end_time + margin
    frames = ring_buffer.get_range(start, end)

    if not frames:
        print(f"  警告: フレームが取得できませんでした")
        return

    # タイムスタンプからファイル名を生成
    ts = event.timestamp.strftime("%Y%m%d_%H%M%S")
    base_name = f"meteor_{ts}"

    # クリップを保存
    height, width = frames[0][1].shape[:2]
    clip_path = output_dir / f"{base_name}.mp4"
    writer = None
    for fourcc_name in ("avc1", "H264", "mp4v"):
        fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
        writer = cv2.VideoWriter(str(clip_path), fourcc, fps, (width, height))
        if writer.isOpened():
            break
        writer.release()
        writer = None
    if writer is None:
        print("[WARN] 動画エンコーダの初期化に失敗しました")
        return

    for _, frame in frames:
        writer.write(frame)
    writer.release()

    # ピークフレームを保存（合成）
    peak_time = (event.start_time + event.end_time) / 2
    event_frames = ring_buffer.get_range(event.start_time, event.end_time)

    if event_frames:
        # 比較明合成
        composite = event_frames[0][1].astype(np.float32)
        for _, f in event_frames[1:]:
            composite = np.maximum(composite, f.astype(np.float32))
        composite = np.clip(composite, 0, 255).astype(np.uint8)

        # マーク付き
        marked = composite.copy()
        cv2.line(marked, event.start_point, event.end_point, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(marked, event.start_point, 6, (0, 255, 0), 2)
        cv2.circle(marked, event.end_point, 6, (0, 0, 255), 2)

        info_text = f"{event.timestamp.strftime('%H:%M:%S')} | Conf: {event.confidence:.0%}"
        cv2.putText(marked, info_text, (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.imwrite(str(output_dir / f"{base_name}_composite.jpg"), marked)
        cv2.imwrite(str(output_dir / f"{base_name}_composite_original.jpg"), composite)

    # JSONログ
    log_path = output_dir / "detections.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    print(f"  保存: {clip_path.name}")


def process_rtsp_stream(
    url: str,
    output_dir: str = "meteor_detections",
    params: DetectionParams = None,
    process_scale: float = 0.5,
    buffer_seconds: float = 15.0,
    show_preview: bool = False,
    sensitivity: str = "medium",
):
    """RTSPストリームを処理"""
    params = params or DetectionParams()

    # 感度プリセット
    if sensitivity == "low":
        params.diff_threshold = 40
        params.min_brightness = 220
        params.min_length = 30
    elif sensitivity == "high":
        params.diff_threshold = 20
        params.min_brightness = 180
        params.min_length = 15
    elif sensitivity == "fireball":
        params.diff_threshold = 15
        params.min_brightness = 150
        params.min_length = 30
        params.max_duration = 20.0
        params.min_speed = 20.0
        params.min_linearity = 0.6

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"RTSPストリーム: {url}")
    print(f"出力先: {output_path}")
    print(f"感度: {sensitivity}")
    print(f"処理スケール: {process_scale}")
    print(f"バッファ: {buffer_seconds}秒")
    print()

    # ストリーム接続
    reader = RTSPReader(url)
    print("接続中...")
    reader.start()

    if not reader.connected.is_set():
        print("接続に失敗しました")
        return

    width, height = reader.frame_size
    fps = reader.fps
    proc_width = int(width * process_scale)
    proc_height = int(height * process_scale)
    scale_factor = 1.0 / process_scale

    print(f"解像度: {width}x{height} @ {fps:.1f}fps")
    print(f"処理解像度: {proc_width}x{proc_height}")
    print()
    print("検出開始 (Ctrl+C で終了)")
    print("-" * 50)

    # コンポーネント初期化
    ring_buffer = RingBuffer(buffer_seconds, fps)
    detector = RealtimeMeteorDetector(params, fps)

    prev_gray = None
    detection_count = 0
    frame_count = 0
    start_time = time.time()

    # シグナルハンドラ
    stop_flag = Event()

    def signal_handler(sig, frame):
        print("\n終了中...")
        stop_flag.set()

    signal.signal(signal.SIGINT, signal_handler)

    try:
        while not stop_flag.is_set():
            ret, timestamp, frame = reader.read()

            if not ret:
                break

            if frame is None:
                continue

            # バッファに保存
            ring_buffer.add(timestamp, frame)

            # 処理用にリサイズ
            if process_scale != 1.0:
                proc_frame = cv2.resize(frame, (proc_width, proc_height),
                                       interpolation=cv2.INTER_AREA)
            else:
                proc_frame = frame

            gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)

            if prev_gray is not None:
                # 検出
                objects = detector.detect_bright_objects(gray, prev_gray)

                # 座標変換
                if process_scale != 1.0:
                    for obj in objects:
                        cx, cy = obj["centroid"]
                        obj["centroid"] = (int(cx * scale_factor), int(cy * scale_factor))

                # 追跡
                events = detector.track_objects(objects, timestamp)

                # 流星イベントを保存
                for event in events:
                    detection_count += 1
                    print(f"\n[{event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
                    print(f"  長さ: {event.length:.1f}px, 時間: {event.duration:.2f}秒")
                    print(f"  信頼度: {event.confidence:.0%}")
                    save_meteor_event(event, ring_buffer, output_path, fps=fps)

                # プレビュー
                if show_preview:
                    display = frame.copy()

                    # 検出中の物体
                    for obj in objects:
                        cx, cy = obj["centroid"]
                        cv2.circle(display, (cx, cy), 5, (0, 255, 0), 2)

                    # アクティブトラック
                    with detector.lock:
                        for track_points in detector.active_tracks.values():
                            if len(track_points) >= 2:
                                for i in range(1, len(track_points)):
                                    pt1 = (track_points[i-1][1], track_points[i-1][2])
                                    pt2 = (track_points[i][1], track_points[i][2])
                                    cv2.line(display, pt1, pt2, (0, 255, 255), 2)

                    # 情報表示
                    elapsed = time.time() - start_time
                    cv2.putText(display, f"Time: {elapsed:.1f}s | Detections: {detection_count}",
                               (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                    cv2.imshow("RTSP Meteor Detection", display)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

            prev_gray = gray.copy()
            frame_count += 1

            # 定期的な状態表示
            if frame_count % (int(fps) * 60) == 0:  # 1分ごと
                elapsed = time.time() - start_time
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"稼働: {elapsed/60:.1f}分, 検出: {detection_count}個")

    finally:
        # 残りのトラックを処理
        events = detector.finalize_all()
        for event in events:
            detection_count += 1
            print(f"\n[{event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
            save_meteor_event(event, ring_buffer, output_path, fps=fps)

        reader.stop()
        if show_preview:
            cv2.destroyAllWindows()

        elapsed = time.time() - start_time
        print()
        print("=" * 50)
        print(f"終了")
        print(f"稼働時間: {elapsed/60:.1f}分")
        print(f"検出数: {detection_count}個")
        print(f"出力先: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="RTSPストリームからリアルタイム流星検出",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
================================================================================
使用例
================================================================================

  基本的な使い方:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream

  プレビューウィンドウを表示しながら検出:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --preview

  火球（長く明るい流星）の検出に最適化:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --sensitivity fireball

  出力先ディレクトリを指定:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream -o ./my_detections

  処理負荷を軽減（解像度を1/4に縮小して処理）:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --scale 0.25

  長い火球用にバッファを30秒に拡張:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --buffer 30

================================================================================
感度プリセット (--sensitivity)
================================================================================

  low      誤検出を最小限に抑える。明るい流星のみ検出。
           ノイズの多い環境や、確実な検出のみ記録したい場合に推奨。

  medium   バランスの取れた設定（デフォルト）。
           一般的な流星観測に適しています。

  high     暗い流星も検出。感度が高いため誤検出が増える可能性あり。
           暗い空や、微光流星も記録したい場合に推奨。

  fireball 火球検出に最適化。長時間（最大20秒）の明るい流星を検出。
           軌道が多少曲がっていても検出可能。流星群の極大期に推奨。

================================================================================
出力ファイル
================================================================================

  検出された流星ごとに以下のファイルが自動保存されます:

  meteor_YYYYMMDD_HHMMSS.mp4
      流星が写っているクリップ動画（前後2秒のマージン含む）
      マーキングなしの元映像

  meteor_YYYYMMDD_HHMMSS_composite.jpg
      流星の全フレームを比較明合成した画像（軌跡マーク付き）

  meteor_YYYYMMDD_HHMMSS_composite_original.jpg
      合成画像（マーキングなし）

  detections.jsonl
      全検出結果のログ（JSON Lines形式、1行1イベント）
      時刻、座標、信頼度などの詳細情報を記録

================================================================================
終了方法
================================================================================

  Ctrl+C で安全に終了します。
  終了時、処理中の流星トラックも保存されます。

================================================================================
        """
    )

    parser.add_argument("url",
        help="RTSPストリームのURL\n"
             "例: rtsp://192.168.1.100:554/stream\n"
             "    rtsp://user:pass@192.168.1.100:554/ch1")

    parser.add_argument("-o", "--output",
        default="meteor_detections",
        metavar="DIR",
        help="検出結果の出力先ディレクトリ。\n"
             "存在しない場合は自動作成されます。\n"
             "(デフォルト: meteor_detections)")

    parser.add_argument("--preview",
        action="store_true",
        help="検出状況をリアルタイムでプレビュー表示します。\n"
             "検出中の物体は緑色の丸、追跡中の軌跡は黄色の線で表示。\n"
             "プレビューウィンドウで 'q' キーを押すと終了。")

    parser.add_argument("--sensitivity",
        choices=["low", "medium", "high", "fireball"],
        default="medium",
        metavar="LEVEL",
        help="検出感度のプリセット。\n"
             "  low:      誤検出を減らす（明るい流星のみ）\n"
             "  medium:   バランス（デフォルト）\n"
             "  high:     暗い流星も検出\n"
             "  fireball: 火球検出モード（長時間・高輝度）")

    parser.add_argument("--scale",
        type=float,
        default=0.5,
        metavar="RATIO",
        help="処理解像度のスケール（0.1〜1.0）。\n"
             "小さいほど処理が軽くなりますが、暗い流星を見逃す可能性あり。\n"
             "  1.0:  フル解像度（高精度・高負荷）\n"
             "  0.5:  半分の解像度（デフォルト、バランス良好）\n"
             "  0.25: 1/4解像度（低負荷、火球検出向き）\n"
             "(デフォルト: 0.5)")

    parser.add_argument("--buffer",
        type=float,
        default=15.0,
        metavar="SEC",
        help="フレームバッファの保持秒数。\n"
             "流星検出時、この秒数分の過去フレームからクリップを生成します。\n"
             "長い火球を記録する場合は大きめに設定してください。\n"
             "メモリ使用量に影響します（目安: 1080p/30fps で 1秒≒150MB）。\n"
             "(デフォルト: 15秒)")

    parser.add_argument("--exclude-bottom",
        type=float,
        default=1/16,
        metavar="RATIO",
        help="画像下部の検出除外範囲（0〜1）。\n"
             "タイムスタンプやカメラ情報の誤検出を防ぎます。\n"
             "  0:      除外なし\n"
             "  0.0625: 下部1/16を除外（デフォルト）\n"
             "  0.125:  下部1/8を除外\n"
             "(デフォルト: 0.0625 = 1/16)")

    args = parser.parse_args()

    params = DetectionParams()
    params.exclude_bottom_ratio = args.exclude_bottom

    process_rtsp_stream(
        args.url,
        output_dir=args.output,
        params=params,
        process_scale=args.scale,
        buffer_seconds=args.buffer,
        show_preview=args.preview,
        sensitivity=args.sensitivity,
    )


if __name__ == "__main__":
    main()
