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
