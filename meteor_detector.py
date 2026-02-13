#!/usr/bin/env python3
"""
MP4動画から流星を検出するプログラム

流星の特徴:
- 線状の明るい軌跡
- 短時間（数フレーム〜数秒）で出現・消滅
- 直線的な高速移動

使い方:
    python meteor_detector.py input.mp4 --output output.mp4

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

import argparse
import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from collections import deque
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from queue import Queue
import time
from datetime import datetime, timedelta

VERSION = "1.7.0"
from astro_utils import get_detection_window, is_detection_active
from meteor_detector_common import calculate_linearity, calculate_confidence, open_video_writer
from meteor_detector_realtime import (
    DetectionParams as RealtimeDetectionParams,
    EventMerger,
    RealtimeMeteorDetector,
    RingBuffer,
    save_meteor_event,
)
from meteor_detector_rtsp_web import build_exclusion_mask


@dataclass
class MeteorCandidate:
    """流星候補"""
    start_frame: int
    end_frame: int
    start_point: Tuple[int, int]
    end_point: Tuple[int, int]
    peak_brightness: float
    trajectory: List[Tuple[int, int, int]]  # [(frame, x, y), ...]
    confidence: float = 0.0

    @property
    def duration_frames(self) -> int:
        return self.end_frame - self.start_frame + 1

    @property
    def length(self) -> float:
        dx = self.end_point[0] - self.start_point[0]
        dy = self.end_point[1] - self.start_point[1]
        return np.sqrt(dx**2 + dy**2)

    @property
    def speed(self) -> float:
        if self.duration_frames > 0:
            return self.length / self.duration_frames
        return 0

    def to_dict(self) -> dict:
        return {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "start_point": self.start_point,
            "end_point": self.end_point,
            "duration_frames": self.duration_frames,
            "length_pixels": round(self.length, 1),
            "speed_pixels_per_frame": round(self.speed, 2),
            "peak_brightness": round(self.peak_brightness, 1),
            "confidence": round(self.confidence, 2),
        }


@dataclass
class DetectionParams:
    """検出パラメータ"""
    # 差分検出
    diff_threshold: int = 30          # フレーム差分の閾値
    min_brightness: int = 200         # 最小輝度

    # 流星の特徴
    min_length: int = 20              # 最小長さ（ピクセル）
    max_length: int = 5000            # 最大長さ（画面横断も対応）
    min_duration: int = 2             # 最小継続フレーム数
    max_duration: int = 300           # 最大継続フレーム数（10秒@30fps、火球対応）
    min_speed: float = 3.0            # 最小速度（ピクセル/フレーム、遅い火球も対応）

    # 直線性
    min_linearity: float = 0.7        # 最小直線性（0-1、火球は若干曲がることも）

    # ノイズ除去
    min_area: int = 5                 # 最小面積
    max_area: int = 10000             # 最大面積（明るい火球対応）

    # 追跡
    max_gap_frames: int = 5           # 追跡の最大ギャップ（明滅対応）
    max_distance: float = 80          # 追跡の最大距離

    # 検出除外範囲
    exclude_bottom_ratio: float = 1/16  # 下部の除外範囲（0-1）


def clone_detection_params(params: DetectionParams) -> DetectionParams:
    """DetectionParamsを複製"""
    return DetectionParams(**vars(params))


def apply_sensitivity_preset(params: DetectionParams, sensitivity: str) -> None:
    """感度プリセットを適用"""
    if sensitivity == "low":
        params.diff_threshold = 40
        params.min_brightness = 220
        params.min_length = 30
        params.min_speed = 8.0
    elif sensitivity == "high":
        params.diff_threshold = 20
        params.min_brightness = 180
        params.min_length = 15
        params.min_speed = 3.0
    elif sensitivity == "fireball":
        # 火球検出モード: 長時間・長距離・明るい流星に最適化
        params.diff_threshold = 15        # 低い閾値で検出しやすく
        params.min_brightness = 150       # 暗めでも検出
        params.min_length = 30            # ある程度の長さは必要
        params.max_length = 10000         # 画面全体を横断してもOK
        params.min_duration = 3           # 最低3フレーム
        params.max_duration = 600         # 20秒@30fps まで対応
        params.min_speed = 1.0            # 遅い火球も検出
        params.min_linearity = 0.6        # 多少曲がってもOK
        params.max_area = 20000           # 大きな光点も対応
        params.max_gap_frames = 10        # 明滅にも対応
        params.max_distance = 150         # 速い火球の追跡にも対応


def build_seek_candidates(base: DetectionParams, max_trials: int) -> List[DetectionParams]:
    """seekモード用に段階的に緩和した候補を生成"""
    max_trials = max(1, max_trials)
    candidates: List[DetectionParams] = []
    seen = set()

    # 0段階目は現在の設定をそのまま使う。段階が進むほど検出条件を緩和する。
    for level in range(max_trials):
        trial = clone_detection_params(base)
        relax = min(level, 6)

        if relax >= 1:
            trial.diff_threshold = max(5, int(round(base.diff_threshold - 5)))
            trial.min_brightness = max(80, int(round(base.min_brightness - 10)))
        if relax >= 2:
            trial.min_length = max(8, int(round(base.min_length - 5)))
            trial.min_speed = max(0.5, base.min_speed * 0.8)
        if relax >= 3:
            trial.diff_threshold = max(5, int(round(base.diff_threshold - 10)))
            trial.min_brightness = max(60, int(round(base.min_brightness - 20)))
            trial.min_linearity = max(0.5, base.min_linearity - 0.05)
            trial.max_gap_frames = max(base.max_gap_frames, base.max_gap_frames + 2)
            trial.max_distance = max(base.max_distance, base.max_distance + 20)
        if relax >= 4:
            trial.min_length = max(5, int(round(base.min_length - 10)))
            trial.min_speed = max(0.3, base.min_speed * 0.6)
            trial.min_area = max(3, int(round(base.min_area - 2)))
        if relax >= 5:
            trial.diff_threshold = max(5, int(round(base.diff_threshold - 15)))
            trial.min_brightness = max(40, int(round(base.min_brightness - 35)))
            trial.min_linearity = max(0.45, base.min_linearity - 0.1)
            trial.max_gap_frames = max(base.max_gap_frames, base.max_gap_frames + 5)
            trial.max_distance = max(base.max_distance, base.max_distance + 50)
        if relax >= 6:
            trial.diff_threshold = max(5, int(round(base.diff_threshold - 20)))
            trial.min_brightness = max(30, int(round(base.min_brightness - 50)))
            trial.min_speed = max(0.2, base.min_speed * 0.4)
            trial.min_linearity = max(0.4, base.min_linearity - 0.15)
            trial.max_gap_frames = max(base.max_gap_frames, base.max_gap_frames + 8)
            trial.max_distance = max(base.max_distance, base.max_distance + 80)
            trial.max_duration = max(base.max_duration, int(round(base.max_duration * 1.5)))
            trial.max_area = max(base.max_area, int(round(base.max_area * 1.5)))

        key = (
            trial.diff_threshold,
            trial.min_brightness,
            trial.min_length,
            round(trial.min_speed, 4),
            round(trial.min_linearity, 4),
            trial.min_area,
            trial.max_area,
            trial.max_gap_frames,
            round(trial.max_distance, 4),
            trial.max_duration,
        )
        if key not in seen:
            seen.add(key)
            candidates.append(trial)

    return candidates


def seek_detection_params(
    input_path: str,
    base_params: DetectionParams,
    *,
    max_trials: int,
    process_scale: float,
    frame_skip: int,
    use_threading: bool,
) -> Tuple[DetectionParams, List[MeteorCandidate]]:
    """流星が検出できるまでパラメータを探索"""
    candidates = build_seek_candidates(base_params, max_trials=max_trials)
    print(f"seekモード: 最大{len(candidates)}回の探索を実行します")

    best_params = clone_detection_params(base_params)
    for idx, trial_params in enumerate(candidates, start=1):
        print(
            f"\n[seek {idx}/{len(candidates)}] "
            f"diff={trial_params.diff_threshold}, "
            f"brightness={trial_params.min_brightness}, "
            f"length={trial_params.min_length}, "
            f"speed={trial_params.min_speed:.2f}, "
            f"linearity={trial_params.min_linearity:.2f}"
        )
        meteors = process_video(
            input_path,
            output_path=None,
            params=trial_params,
            show_preview=False,
            save_json=False,
            save_images=False,
            image_output_dir=None,
            process_scale=process_scale,
            frame_skip=frame_skip,
            use_threading=use_threading,
        )
        best_params = trial_params
        if meteors:
            print(f"\nseek成功: {idx}回目で{len(meteors)}件検出")
            return trial_params, meteors

    print("\nseek失敗: 指定回数内では検出できませんでした。最終試行のパラメータを採用します。")
    return best_params, []


class FrameBuffer:
    """フレームバッファ（ノイズ除去用）"""

    def __init__(self, size: int = 5):
        self.size = size
        self.frames: deque = deque(maxlen=size)

    def add(self, frame: np.ndarray):
        self.frames.append(frame.copy())

    def get_median(self) -> Optional[np.ndarray]:
        if len(self.frames) < self.size:
            return None
        return np.median(np.array(self.frames), axis=0).astype(np.uint8)

    def is_ready(self) -> bool:
        return len(self.frames) >= self.size


class FrameReader:
    """非同期フレーム読み込み（マルチスレッド）"""

    def __init__(self, video_path: str, queue_size: int = 128):
        self.cap = cv2.VideoCapture(video_path)
        self.queue = Queue(maxsize=queue_size)
        self.stopped = False
        self.thread = None

    def start(self):
        self.thread = Thread(target=self._read_frames, daemon=True)
        self.thread.start()
        return self

    def _read_frames(self):
        frame_num = 0
        while not self.stopped:
            if not self.queue.full():
                ret, frame = self.cap.read()
                if not ret:
                    self.stopped = True
                    break
                self.queue.put((frame_num, frame))
                frame_num += 1
            else:
                time.sleep(0.001)

    def read(self) -> Tuple[bool, int, Optional[np.ndarray]]:
        if self.stopped and self.queue.empty():
            return False, -1, None
        if self.queue.empty():
            return True, -1, None  # まだ読み込み中
        frame_num, frame = self.queue.get()
        return True, frame_num, frame

    def stop(self):
        self.stopped = True
        if self.thread:
            self.thread.join(timeout=1.0)
        self.cap.release()

    @property
    def fps(self):
        return self.cap.get(cv2.CAP_PROP_FPS)

    @property
    def frame_count(self):
        return int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

    @property
    def frame_size(self):
        return (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))


class MeteorDetector:
    """流星検出器"""

    def __init__(self, params: DetectionParams = None):
        self.params = params or DetectionParams()
        self.frame_buffer = FrameBuffer(size=5)
        self.background = None
        self.active_tracks: Dict[int, List[Tuple[int, int, int, float]]] = {}
        self.next_track_id = 0
        self.detected_meteors: List[MeteorCandidate] = []

    def update_background(self, frame: np.ndarray, alpha: float = 0.01):
        """背景モデルを更新"""
        if self.background is None:
            self.background = frame.astype(np.float32)
        else:
            cv2.accumulateWeighted(frame, self.background, alpha)

    def detect_bright_objects(self, frame: np.ndarray, prev_frame: np.ndarray,
                              exclude_bottom_ratio: float = 1/16) -> List[dict]:
        """
        明るい移動物体を検出

        Args:
            frame: 現在のフレーム
            prev_frame: 前のフレーム
            exclude_bottom_ratio: 下部の除外範囲（0-1、デフォルト1/16）

        Returns:
            検出された物体のリスト [{centroid, area, bbox, brightness}, ...]
        """
        height = frame.shape[0]
        max_y = int(height * (1 - exclude_bottom_ratio))  # 検出範囲の下限Y座標

        # フレーム差分
        diff = cv2.absdiff(frame, prev_frame)

        # 閾値処理
        _, thresh = cv2.threshold(diff, self.params.diff_threshold, 255, cv2.THRESH_BINARY)

        # 下部をマスク（除外）
        thresh[max_y:, :] = 0

        # モルフォロジー処理でノイズ除去
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        # 輪郭検出
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        objects = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if not (self.params.min_area <= area <= self.params.max_area):
                continue

            # 重心
            M = cv2.moments(contour)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])

            # 下部除外範囲内ならスキップ
            if cy >= max_y:
                continue

            # バウンディングボックス
            x, y, w, h = cv2.boundingRect(contour)

            # 明るさ
            mask = np.zeros(frame.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            brightness = cv2.mean(frame, mask=mask)[0]

            if brightness >= self.params.min_brightness:
                objects.append({
                    "centroid": (cx, cy),
                    "area": area,
                    "bbox": (x, y, w, h),
                    "brightness": brightness,
                    "contour": contour,
                })

        return objects

    def track_objects(self, objects: List[dict], frame_num: int):
        """
        物体を追跡

        新しい物体は新規トラックとして登録し、
        既存のトラックに近い物体はそのトラックに追加する
        """
        used_objects = set()

        # 既存トラックとのマッチング
        tracks_to_remove = []
        for track_id, track_points in self.active_tracks.items():
            if not track_points:
                continue

            last_frame, last_x, last_y, _ = track_points[-1]
            gap = frame_num - last_frame

            if gap > self.params.max_gap_frames:
                # トラック終了
                tracks_to_remove.append(track_id)
                continue

            # 最も近い物体を探す
            best_match = None
            best_dist = float('inf')

            for i, obj in enumerate(objects):
                if i in used_objects:
                    continue

                cx, cy = obj["centroid"]
                dist = np.sqrt((cx - last_x)**2 + (cy - last_y)**2)

                # 予測位置との比較（速度がある場合）
                if len(track_points) >= 2:
                    prev_frame, prev_x, prev_y, _ = track_points[-2]
                    vx = (last_x - prev_x) / max(1, last_frame - prev_frame)
                    vy = (last_y - prev_y) / max(1, last_frame - prev_frame)
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
                track_points.append((frame_num, cx, cy, obj["brightness"]))
                used_objects.add(best_match)

        # 終了したトラックを処理
        for track_id in tracks_to_remove:
            self._finalize_track(track_id)

        # 新規トラックを作成
        for i, obj in enumerate(objects):
            if i not in used_objects:
                cx, cy = obj["centroid"]
                self.active_tracks[self.next_track_id] = [
                    (frame_num, cx, cy, obj["brightness"])
                ]
                self.next_track_id += 1

    def _finalize_track(self, track_id: int):
        """トラックを終了して流星判定"""
        if track_id not in self.active_tracks:
            return

        track_points = self.active_tracks.pop(track_id)

        if len(track_points) < self.params.min_duration:
            return

        # 流星の特徴を評価
        frames = [p[0] for p in track_points]
        xs = [p[1] for p in track_points]
        ys = [p[2] for p in track_points]
        brightness = [p[3] for p in track_points]

        start_frame = min(frames)
        end_frame = max(frames)
        duration = end_frame - start_frame + 1

        if duration > self.params.max_duration:
            return

        # 始点と終点
        start_idx = frames.index(start_frame)
        end_idx = frames.index(end_frame)
        start_point = (xs[start_idx], ys[start_idx])
        end_point = (xs[end_idx], ys[end_idx])

        # 長さ
        length = np.sqrt((end_point[0] - start_point[0])**2 +
                        (end_point[1] - start_point[1])**2)

        if not (self.params.min_length <= length <= self.params.max_length):
            return

        # 速度
        speed = length / max(1, duration)
        if speed < self.params.min_speed:
            return

        # 直線性を評価（線形回帰の決定係数）
        linearity = calculate_linearity(xs, ys)
        if linearity < self.params.min_linearity:
            return

        # 信頼度を計算
        confidence = calculate_confidence(length, speed, linearity, max(brightness), duration)

        # 流星候補として登録
        meteor = MeteorCandidate(
            start_frame=start_frame,
            end_frame=end_frame,
            start_point=start_point,
            end_point=end_point,
            peak_brightness=max(brightness),
            trajectory=[(f, x, y) for f, x, y, _ in track_points],
            confidence=confidence,
        )
        self.detected_meteors.append(meteor)

    def finalize_all_tracks(self):
        """全てのアクティブトラックを終了"""
        for track_id in list(self.active_tracks.keys()):
            self._finalize_track(track_id)


def process_video(
    input_path: str,
    output_path: Optional[str] = None,
    params: DetectionParams = None,
    show_preview: bool = False,
    save_json: bool = True,
    save_images: bool = True,
    image_output_dir: Optional[str] = None,
    process_scale: float = 1.0,
    frame_skip: int = 1,
    use_threading: bool = True,
    latitude: float = 35.3606,
    longitude: float = 138.7274,
    timezone: str = "Asia/Tokyo",
    enable_time_window: bool = False,
) -> List[MeteorCandidate]:
    """
    動画を処理して流星を検出

    Args:
        input_path: 入力動画パス
        output_path: 出力動画パス（Noneなら保存しない）
        params: 検出パラメータ
        show_preview: プレビューを表示するか
        save_json: 検出結果をJSONで保存するか
        save_images: 流星画像をJPGで保存するか
        image_output_dir: 画像出力ディレクトリ（Noneなら入力と同じ場所）
        process_scale: 処理解像度スケール（0.5なら半分のサイズで処理、高速化）
        frame_skip: フレームスキップ（2なら1フレームおきに処理、高速化）
        use_threading: マルチスレッド読み込みを使用するか
        latitude: 緯度
        longitude: 経度
        timezone: タイムゾーン
        enable_time_window: 天文薄暮期間のみ検出を有効化するか

    Returns:
        検出された流星のリスト
    """
    params = params or DetectionParams()
    detector = MeteorDetector(params)

    # 動画を開く（スレッド版 or 通常版）
    if use_threading:
        reader = FrameReader(input_path)
        reader.start()
        width, height = reader.frame_size
        fps = reader.fps
        total_frames = reader.frame_count
    else:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError(f"動画を開けません: {input_path}")
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # 処理解像度
    proc_width = int(width * process_scale)
    proc_height = int(height * process_scale)
    scale_factor = 1.0 / process_scale  # 座標変換用

    print(f"動画情報: {width}x{height}, {fps:.1f}fps, {total_frames}フレーム")
    if process_scale != 1.0:
        print(f"処理解像度: {proc_width}x{proc_height} (scale={process_scale})")
    if frame_skip > 1:
        print(f"フレームスキップ: {frame_skip} (実効fps={fps/frame_skip:.1f})")
    if use_threading:
        print(f"マルチスレッド読み込み: 有効")

    # 天文薄暮期間の判定
    if enable_time_window:
        is_active, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
        print(f"検出期間: {detection_start.strftime('%Y-%m-%d %H:%M:%S')} - {detection_end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"検出状態: {'有効' if is_active else '無効（ストリーム表示のみ）'}")
    else:
        is_active = True
        detection_start = None
        detection_end = None
        print(f"検出期間: 常時有効")

    print(f"処理中...")

    # 画像出力ディレクトリの準備
    if save_images:
        if image_output_dir:
            img_dir = Path(image_output_dir)
        else:
            img_dir = Path(input_path).parent / f"{Path(input_path).stem}_meteors"
        img_dir.mkdir(parents=True, exist_ok=True)
        print(f"画像出力先: {img_dir}")

    # 出力動画の準備
    writer = None
    if output_path:
        writer = open_video_writer(output_path, fps, (width, height))
        if writer is None:
            print("[WARN] 動画エンコーダの初期化に失敗しました")
            return

    # 前フレーム
    prev_gray = None
    frame_num = 0
    processed_frames = 0
    start_time = time.time()

    while True:
        # フレーム読み込み
        if use_threading:
            ret, read_frame_num, frame = reader.read()
            if not ret and frame is None:
                break
            if frame is None:  # キュー待ち
                time.sleep(0.001)
                continue
            frame_num = read_frame_num
        else:
            ret, frame = cap.read()
            if not ret:
                break

        # フレームスキップ
        if frame_skip > 1 and frame_num % frame_skip != 0:
            frame_num += 1 if not use_threading else 0
            continue

        # 処理用にリサイズ
        if process_scale != 1.0:
            proc_frame = cv2.resize(frame, (proc_width, proc_height), interpolation=cv2.INTER_AREA)
        else:
            proc_frame = frame

        # グレースケールに変換
        gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)

        if prev_gray is not None:
            # 天文薄暮期間のチェック（有効な場合のみ）
            if enable_time_window:
                if detection_start is None or detection_end is None:
                    is_active, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
                else:
                    now = datetime.now(detection_start.tzinfo)
                    if now > detection_end:
                        is_active, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
                    else:
                        is_active = detection_start <= now <= detection_end

            # 検出処理（検出期間内の場合のみ）
            if is_active:
                # 明るい移動物体を検出
                objects = detector.detect_bright_objects(gray, prev_gray,
                                                         exclude_bottom_ratio=params.exclude_bottom_ratio)

                # 座標をオリジナルスケールに変換
                if process_scale != 1.0:
                    for obj in objects:
                        cx, cy = obj["centroid"]
                        obj["centroid"] = (int(cx * scale_factor), int(cy * scale_factor))
                        x, y, w, h = obj["bbox"]
                        obj["bbox"] = (int(x * scale_factor), int(y * scale_factor),
                                      int(w * scale_factor), int(h * scale_factor))

                # 追跡
                detector.track_objects(objects, frame_num)
            else:
                objects = []

            processed_frames += 1

            # 描画（出力用）
            if output_path or show_preview:
                display_frame = frame.copy()

                # 現在検出中の物体を描画
                for obj in objects:
                    cx, cy = obj["centroid"]
                    cv2.circle(display_frame, (cx, cy), 5, (0, 255, 0), 2)

                # アクティブなトラックを描画
                for track_id, track_points in detector.active_tracks.items():
                    if len(track_points) >= 2:
                        for i in range(1, len(track_points)):
                            pt1 = (track_points[i-1][1], track_points[i-1][2])
                            pt2 = (track_points[i][1], track_points[i][2])
                            cv2.line(display_frame, pt1, pt2, (0, 255, 255), 2)

                # 確定した流星を描画
                for meteor in detector.detected_meteors:
                    # フレーム範囲内なら描画
                    if meteor.start_frame <= frame_num <= meteor.end_frame + 30:
                        cv2.line(display_frame, meteor.start_point, meteor.end_point,
                                (0, 0, 255), 2)
                        cv2.putText(display_frame,
                                   f"METEOR ({meteor.confidence:.0%})",
                                   (meteor.start_point[0], meteor.start_point[1] - 10),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                # 情報表示
                cv2.putText(display_frame,
                           f"Frame: {frame_num}/{total_frames}",
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(display_frame,
                           f"Detected: {len(detector.detected_meteors)}",
                           (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                if writer:
                    writer.write(display_frame)

                if show_preview:
                    cv2.imshow("Meteor Detection", display_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        break

        prev_gray = gray.copy()
        if not use_threading:
            frame_num += 1

        # 進捗表示
        if processed_frames % 100 == 0 and processed_frames > 0:
            elapsed = time.time() - start_time
            fps_actual = processed_frames / elapsed if elapsed > 0 else 0
            progress = frame_num / total_frames * 100
            print(f"  {progress:.1f}% ({frame_num}/{total_frames}) - {fps_actual:.1f} fps")

    # 残りのトラックを処理
    detector.finalize_all_tracks()

    # クリーンアップ
    if use_threading:
        reader.stop()
    else:
        cap.release()
    if writer:
        writer.release()
    if show_preview:
        cv2.destroyAllWindows()

    # 処理時間表示
    total_time = time.time() - start_time
    avg_fps = processed_frames / total_time if total_time > 0 else 0
    print(f"\n処理時間: {total_time:.1f}秒 (平均 {avg_fps:.1f} fps)")

    # 結果表示
    print(f"\n検出完了!")
    print(f"検出された流星: {len(detector.detected_meteors)}個")

    for i, meteor in enumerate(detector.detected_meteors):
        print(f"\n流星 #{i+1}:")
        print(f"  フレーム: {meteor.start_frame} - {meteor.end_frame} ({meteor.duration_frames}フレーム)")
        print(f"  長さ: {meteor.length:.1f} ピクセル")
        print(f"  速度: {meteor.speed:.1f} ピクセル/フレーム")
        print(f"  最大輝度: {meteor.peak_brightness:.1f}")
        print(f"  信頼度: {meteor.confidence:.0%}")

    # 流星画像を保存
    if save_images and detector.detected_meteors:
        print(f"\n流星画像を保存中...")
        # 動画を再度開いて該当フレームを取得
        cap2 = cv2.VideoCapture(input_path)

        for i, meteor in enumerate(detector.detected_meteors):
            # ピークフレーム（中間フレーム）を取得
            peak_frame = (meteor.start_frame + meteor.end_frame) // 2
            cap2.set(cv2.CAP_PROP_POS_FRAMES, peak_frame)
            ret, frame = cap2.read()

            if ret:
                # 流星の軌跡を描画
                marked_frame = frame.copy()
                cv2.line(marked_frame, meteor.start_point, meteor.end_point,
                        (0, 255, 255), 2, cv2.LINE_AA)
                cv2.circle(marked_frame, meteor.start_point, 6, (0, 255, 0), 2)
                cv2.circle(marked_frame, meteor.end_point, 6, (0, 0, 255), 2)

                # 情報テキスト
                info_text = f"Meteor #{i+1} | Frame {meteor.start_frame}-{meteor.end_frame} | Conf: {meteor.confidence:.0%}"
                cv2.putText(marked_frame, info_text, (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                # 保存（マーク付き）
                img_path = img_dir / f"meteor_{i+1:03d}_frame{peak_frame:06d}.jpg"
                cv2.imwrite(str(img_path), marked_frame)

                # 元画像も保存（マークなし）
                img_path_orig = img_dir / f"meteor_{i+1:03d}_frame{peak_frame:06d}_original.jpg"
                cv2.imwrite(str(img_path_orig), frame)

                print(f"  保存: {img_path.name}")

            # 複数フレームを合成した画像を作成
            if meteor.duration_frames > 1:
                composite = None
                base_frame = None

                # 流星の全フレームを取得して合成
                for frame_idx in range(meteor.start_frame, meteor.end_frame + 1):
                    cap2.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                    ret, f = cap2.read()
                    if not ret:
                        continue

                    if composite is None:
                        composite = f.astype(np.float32)
                        base_frame = f.copy()
                    else:
                        # 明るい部分を合成（比較明合成）
                        composite = np.maximum(composite, f.astype(np.float32))

                if composite is not None:
                    composite_img = np.clip(composite, 0, 255).astype(np.uint8)

                    # マーク付き合成画像
                    marked_composite = composite_img.copy()
                    cv2.line(marked_composite, meteor.start_point, meteor.end_point,
                            (0, 255, 255), 2, cv2.LINE_AA)
                    cv2.circle(marked_composite, meteor.start_point, 6, (0, 255, 0), 2)
                    cv2.circle(marked_composite, meteor.end_point, 6, (0, 0, 255), 2)

                    # 情報テキスト
                    info_text = f"Meteor #{i+1} | Frame {meteor.start_frame}-{meteor.end_frame} ({meteor.duration_frames}frames) | Conf: {meteor.confidence:.0%}"
                    cv2.putText(marked_composite, info_text, (10, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                    # 合成画像を保存
                    composite_path = img_dir / f"meteor_{i+1:03d}_composite.jpg"
                    cv2.imwrite(str(composite_path), marked_composite)

                    # マークなし合成画像も保存
                    composite_orig_path = img_dir / f"meteor_{i+1:03d}_composite_original.jpg"
                    cv2.imwrite(str(composite_orig_path), composite_img)

                    print(f"  保存: {composite_path.name} (合成)")

        cap2.release()

    # JSON保存
    if save_json and detector.detected_meteors:
        json_path = Path(input_path).with_suffix('.meteors.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                "video": input_path,
                "fps": fps,
                "total_frames": total_frames,
                "meteors": [m.to_dict() for m in detector.detected_meteors]
            }, f, indent=2, ensure_ascii=False)
        print(f"\n検出結果を保存: {json_path}")

    if output_path:
        print(f"出力動画: {output_path}")

    return detector.detected_meteors


def extract_meteor_clips(
    input_path: str,
    meteors: List[MeteorCandidate],
    output_dir: str = "meteor_clips",
    margin_before: int = 30,
    margin_after: int = 60,
):
    """
    流星が写っている部分を切り出して保存

    Args:
        input_path: 入力動画パス
        meteors: 検出された流星リスト
        output_dir: 出力ディレクトリ
        margin_before: 前のマージン（フレーム数、デフォルト30=1秒）
        margin_after: 後のマージン（フレーム数、デフォルト60=2秒）
    """
    if not meteors:
        print("流星が検出されていません")
        return

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(input_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    for i, meteor in enumerate(meteors):
        start = max(0, meteor.start_frame - margin_before)
        end = min(total_frames - 1, meteor.end_frame + margin_after)

        output_path = Path(output_dir) / f"meteor_{i+1:03d}.mov"
        writer = open_video_writer(output_path, fps, (width, height))
        if writer is None:
            print("[WARN] 動画エンコーダの初期化に失敗しました")
            continue

        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        for frame_num in range(start, end + 1):
            ret, frame = cap.read()
            if not ret:
                break

            writer.write(frame)

        writer.release()
        print(f"保存: {output_path}")

    cap.release()


def create_composite_image(
    input_path: str,
    meteors: List[MeteorCandidate],
    output_path: str = "meteor_composite.jpg",
):
    """
    流星が写っているフレームを合成した画像を作成

    Args:
        input_path: 入力動画パス
        meteors: 検出された流星リスト
        output_path: 出力画像パス
    """
    if not meteors:
        print("流星が検出されていません")
        return

    cap = cv2.VideoCapture(input_path)

    # ベースフレーム（最初のフレーム）
    ret, base_frame = cap.read()
    if not ret:
        return

    composite = base_frame.astype(np.float32)

    # 各流星のピークフレームを合成
    for meteor in meteors:
        peak_frame = (meteor.start_frame + meteor.end_frame) // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, peak_frame)
        ret, frame = cap.read()
        if ret:
            # 明るい部分を合成
            composite = np.maximum(composite, frame.astype(np.float32))

    cap.release()


def process_video_realtime(
    input_path: str,
    *,
    output_dir: str = "meteor_detections",
    params: RealtimeDetectionParams | None = None,
    process_scale: float = 0.5,
    buffer_seconds: float = 15.0,
    sensitivity: str = "medium",
    extract_clips: bool = True,
    exclude_bottom_ratio: float = 1 / 16,
    mask_image: str | None = None,
    mask_from_day: str | None = None,
    mask_dilate: int = 20,
    mask_save: str | None = None,
) -> None:
    """リアルタイム検出ロジックでファイルを再検出（Web版と同等の再現用）"""
    params = params or RealtimeDetectionParams()
    params.exclude_bottom_ratio = exclude_bottom_ratio

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

    params.min_brightness_tracking = max(1, int(params.min_brightness * 0.8))

    required_buffer = params.max_duration + 2.0
    effective_buffer_seconds = min(buffer_seconds, required_buffer)
    if effective_buffer_seconds != buffer_seconds:
        print(f"バッファ秒数を{effective_buffer_seconds:.1f}秒に調整（検出前後1秒 + 最大検出時間）")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"[ERROR] 動画を開けません: {input_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"入力動画: {input_path}")
    print(f"解像度: {width}x{height}, fps: {fps:.2f}")
    print(f"出力先: {output_path}")
    print("検出開始 (リアルタイム検出ロジック)")
    print("-" * 50)

    ring_buffer = RingBuffer(effective_buffer_seconds, fps=fps)
    exclusion_mask = None
    proc_width = int(width * process_scale)
    proc_height = int(height * process_scale)

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
            save_path=Path(mask_save) if mask_save else None,
        )
        if exclusion_mask is not None:
            print(f"マスク適用: {mask_from_day}")

    detector = RealtimeMeteorDetector(params, fps, exclusion_mask=exclusion_mask)
    merger = EventMerger(params)

    prev_gray = None
    frame_count = 0
    detection_count = 0

    scale_factor = 1.0 / process_scale if process_scale != 0 else 1.0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp = frame_count / fps
        ring_buffer.add(timestamp, frame)

        if process_scale != 1.0:
            proc_frame = cv2.resize(frame, (proc_width, proc_height), interpolation=cv2.INTER_AREA)
        else:
            proc_frame = frame

        gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)

        if prev_gray is not None:
            tracking_mode = len(detector.active_tracks) > 0
            objects = detector.detect_bright_objects(gray, prev_gray, tracking_mode=tracking_mode)

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
                    save_meteor_event(
                        merged_event,
                        ring_buffer,
                        output_path,
                        fps=fps,
                        extract_clips=extract_clips,
                        clip_margin_before=1.0,
                        clip_margin_after=1.0,
                        composite_after=1.0,
                    )

            expired_events = merger.flush_expired(timestamp)
            for expired_event in expired_events:
                detection_count += 1
                print(f"\n[{expired_event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
                print(f"  長さ: {expired_event.length:.1f}px, 時間: {expired_event.duration:.2f}秒")
                save_meteor_event(
                    expired_event,
                    ring_buffer,
                    output_path,
                    fps=fps,
                    extract_clips=extract_clips,
                    clip_margin_before=1.0,
                    clip_margin_after=1.0,
                    composite_after=1.0,
                )

        prev_gray = gray.copy()
        frame_count += 1

    # 終了処理
    for event in detector.finalize_all():
        merged_events = merger.add_event(event)
        for merged_event in merged_events:
            detection_count += 1
            save_meteor_event(
                merged_event,
                ring_buffer,
                output_path,
                fps=fps,
                extract_clips=extract_clips,
                clip_margin_before=1.0,
                clip_margin_after=1.0,
                composite_after=1.0,
            )

    for event in merger.flush_all():
        detection_count += 1
        save_meteor_event(
            event,
            ring_buffer,
            output_path,
            fps=fps,
            extract_clips=extract_clips,
            clip_margin_before=1.0,
            clip_margin_after=1.0,
            composite_after=1.0,
        )

    cap.release()
    print(f"\n終了 - 検出数: {detection_count}個")


def main():
    parser = argparse.ArgumentParser(
        description="MP4動画から流星を検出",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 基本的な使い方
  python meteor_detector.py input.mp4

  # 出力動画を生成
  python meteor_detector.py input.mp4 --output detected.mp4

  # プレビュー表示
  python meteor_detector.py input.mp4 --preview

  # 検出感度を調整
  python meteor_detector.py input.mp4 --sensitivity high

  # 火球検出モード（長時間・長距離の明るい流星）
  python meteor_detector.py input.mp4 --sensitivity fireball

  # seekモード（検出できるまで段階的にパラメータ探索）
  python meteor_detector.py input.mp4 --seek --seek-max-trials 8

  # 流星クリップを切り出し
  python meteor_detector.py input.mp4 --extract-clips

  # 合成画像を作成
  python meteor_detector.py input.mp4 --composite

感度プリセット:
  low      - 誤検出を減らす（明るい流星のみ）
  medium   - バランス（デフォルト）
  high     - 暗い流星も検出
  fireball - 火球検出（長時間・長距離・明滅対応）

高速化オプション:
  --fast           - 高速モード（解像度半分 + 1フレームおき）
  --scale 0.5      - 処理解像度を半分に（約4倍速）
  --skip 2         - 1フレームおきに処理（約2倍速）
  --no-threading   - マルチスレッド無効化（デバッグ用）
        """
    )

    parser.add_argument("input", help="入力動画ファイル")
    parser.add_argument("-o", "--output", help="出力動画ファイル")
    parser.add_argument("--preview", action="store_true",
                       help="プレビューを表示")
    parser.add_argument("--sensitivity", choices=["low", "medium", "high", "fireball"],
                       default="medium", help="検出感度 (default: medium, fireball=火球検出モード)")
    parser.add_argument("--seek", action="store_true",
                       help="検出できるまで段階的にパラメータを探索してから本処理を実行")
    parser.add_argument("--seek-max-trials", type=int, default=6,
                       help="seekモードの最大試行回数 (default: 6)")
    parser.add_argument("--extract-clips", dest="extract_clips", action="store_true", default=True,
                       help="流星クリップを切り出して保存 (デフォルト: 有効)")
    parser.add_argument("--no-clips", dest="extract_clips", action="store_false",
                       help="流星クリップを保存しない")
    parser.add_argument("--realtime", action="store_true",
                       help="Web版と同じリアルタイム検出ロジックで再検出する")
    parser.add_argument("--output-dir", default="meteor_detections",
                       help="リアルタイム再検出時の出力ディレクトリ (default: meteor_detections)")
    parser.add_argument("--buffer", type=float, default=15.0,
                       help="リアルタイム再検出時のバッファ秒数 (default: 15.0)")
    parser.add_argument("--mask-image", help="作成済みの除外マスク画像を使用（リアルタイム再検出）")
    parser.add_argument("--mask-from-day", help="昼間画像から検出除外マスクを生成（リアルタイム再検出）")
    parser.add_argument("--mask-dilate", type=int, default=20,
                       help="除外マスクの拡張ピクセル数（リアルタイム再検出）")
    parser.add_argument("--mask-save", help="生成した除外マスク画像の保存先（リアルタイム再検出）")
    parser.add_argument("--composite", action="store_true",
                       help="合成画像を作成")
    parser.add_argument("--no-json", action="store_true",
                       help="JSON出力を無効化")
    parser.add_argument("--no-images", action="store_true",
                       help="流星画像のJPG出力を無効化")
    parser.add_argument("--image-dir",
                       help="流星画像の出力ディレクトリ")
    parser.add_argument("--exclude-bottom", type=float, default=1/16,
                       help="下部の除外範囲（0-1、デフォルト: 1/16）")

    # 高速化オプション
    parser.add_argument("--scale", type=float, default=0.5,
                       help="処理解像度スケール（0.5で半分、高速化、デフォルト: 0.5）")
    parser.add_argument("--skip", type=int, default=1,
                       help="フレームスキップ（2で1フレームおき、高速化、デフォルト: 1）")
    parser.add_argument("--fast", action="store_true",
                       help="高速モード（--scale 0.5 --skip 2 と同等）")
    parser.add_argument("--no-threading", action="store_true",
                       help="マルチスレッド読み込みを無効化")

    # 詳細パラメータ
    parser.add_argument("--diff-threshold", type=int,
                       help="フレーム差分の閾値 (default: 30)")
    parser.add_argument("--min-brightness", type=int,
                       help="最小輝度 (default: 200)")
    parser.add_argument("--min-length", type=int,
                       help="最小長さ (default: 20)")
    parser.add_argument("--min-speed", type=float,
                       help="最小速度 (default: 5.0)")

    args = parser.parse_args()

    # パラメータ設定
    params = DetectionParams()

    # 感度プリセット
    apply_sensitivity_preset(params, args.sensitivity)

    # 個別パラメータ上書き
    if args.diff_threshold:
        params.diff_threshold = args.diff_threshold
    if args.min_brightness:
        params.min_brightness = args.min_brightness
    if args.min_length:
        params.min_length = args.min_length
    if args.min_speed:
        params.min_speed = args.min_speed
    params.exclude_bottom_ratio = args.exclude_bottom

    # 高速化オプション
    process_scale = args.scale
    frame_skip = args.skip
    if args.fast:
        process_scale = 0.5
        frame_skip = 2

    # 処理実行
    if args.realtime:
        if args.seek:
            print("[WARN] --seek は通常検出モード専用です。--realtime では無視されます。")
        process_video_realtime(
            args.input,
            output_dir=args.output_dir,
            process_scale=process_scale,
            buffer_seconds=args.buffer,
            sensitivity=args.sensitivity,
            extract_clips=args.extract_clips,
            exclude_bottom_ratio=args.exclude_bottom,
            mask_image=args.mask_image.strip() if args.mask_image else None,
            mask_from_day=args.mask_from_day.strip() if args.mask_from_day else None,
            mask_dilate=args.mask_dilate,
            mask_save=args.mask_save.strip() if args.mask_save else None,
        )
        return

    if args.seek:
        params, _ = seek_detection_params(
            args.input,
            params,
            max_trials=args.seek_max_trials,
            process_scale=process_scale,
            frame_skip=frame_skip,
            use_threading=not args.no_threading,
        )

    meteors = process_video(
        args.input,
        output_path=args.output,
        params=params,
        show_preview=args.preview,
        save_json=not args.no_json,
        save_images=not args.no_images,
        image_output_dir=args.image_dir,
        process_scale=process_scale,
        frame_skip=frame_skip,
        use_threading=not args.no_threading,
    )

    # オプション処理
    if args.extract_clips and meteors:
        extract_meteor_clips(args.input, meteors)

    if args.composite and meteors:
        composite_path = Path(args.input).with_suffix('.composite.jpg')
        create_composite_image(args.input, meteors, str(composite_path))


if __name__ == "__main__":
    main()
