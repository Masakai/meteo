"""
流星検出の共通ユーティリティ

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple, Union

import cv2
import numpy as np


def calculate_linearity(xs: Sequence[float], ys: Sequence[float]) -> float:
    """直線性を計算（0-1、1が完全な直線）"""
    if len(xs) < 3:
        return 1.0

    xs_arr = np.array(xs)
    ys_arr = np.array(ys)

    points = np.column_stack([xs_arr, ys_arr])
    centroid = np.mean(points, axis=0)
    centered = points - centroid

    cov = np.cov(centered.T)
    eigenvalues = np.linalg.eigvalsh(cov)
    eigenvalues = np.sort(eigenvalues)[::-1]

    if eigenvalues[0] == 0:
        return 0.0

    return eigenvalues[0] / (eigenvalues[0] + eigenvalues[1] + 1e-10)


def calculate_heading_variance(xs: Sequence[float], ys: Sequence[float]) -> float:
    """軌跡の進行方向角度の分散（蛇行度）を計算する。

    連続する軌跡点間の進行方向角度（atan2(dy, dx)）を求め、隣接する角度差
    （ラップアラウンドを[-pi, pi]に正規化）の標準偏差（ラジアン）を返す。
    直線的な軌跡（流星）は角度差が小さく分散も小さい。羽ばたきで進行方向が
    揺れる軌跡（鳥・コウモリ）は角度差の分散が大きくなる。

    点数が3未満（角度差を1つも計算できない）の場合は判定不能として0.0を返す
    （fail-open。呼び出し側はmin_heading_variance_pointsで別途、統計的に
    不安定な少点数域を判定スキップする）。
    """
    if len(xs) < 3:
        return 0.0

    xs_arr = np.asarray(xs, dtype=np.float64)
    ys_arr = np.asarray(ys, dtype=np.float64)

    dx = np.diff(xs_arr)
    dy = np.diff(ys_arr)
    headings = np.arctan2(dy, dx)

    heading_diffs = np.diff(headings)
    # [-pi, pi] にラップアラウンド正規化
    heading_diffs = np.arctan2(np.sin(heading_diffs), np.cos(heading_diffs))

    if heading_diffs.size == 0:
        return 0.0

    return float(np.std(heading_diffs))


def calculate_confidence(
    length: float,
    speed: float,
    linearity: float,
    brightness: float,
    duration: float,
    *,
    length_norm: float = 100.0,
    speed_norm: float = 20.0,
    duration_norm: float = 100.0,
    duration_bonus_scale: float = 0.2,
    duration_bonus_max: float = 0.2,
) -> float:
    """信頼度を計算（0-1）"""
    length_score = min(1.0, length / length_norm)
    speed_score = min(1.0, speed / speed_norm)
    linearity_score = linearity
    brightness_score = min(1.0, brightness / 255)

    duration_bonus = min(duration_bonus_max, duration / duration_norm * duration_bonus_scale)

    confidence = (
        length_score * 0.25 +
        speed_score * 0.2 +
        linearity_score * 0.25 +
        brightness_score * 0.2 +
        duration_bonus
    )

    return min(1.0, confidence)


def open_video_writer(
    output_path: Union[str, Path],
    fps: float,
    size: Tuple[int, int],
    codecs: Iterable[str] = ("avc1", "H264", "mp4v"),
) -> Optional[cv2.VideoWriter]:
    """利用可能なコーデックでVideoWriterを初期化"""
    writer = None
    for fourcc_name in codecs:
        fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, size)
        if writer.isOpened():
            return writer
        writer.release()
        writer = None
    return None
