"""Mask generation utilities for exclusion and nuisance regions."""

from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np


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
    _, labels = cv2.connectedComponents(sky_mask)
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
                exclusion[y_max + 1 :, x] = 255

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

    _, labels = cv2.connectedComponents(sky_mask)
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
                exclusion[y_max + 1 :, x] = 255

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


def build_nuisance_mask_from_night(
    night_image_path: str,
    proc_size: Tuple[int, int],
    dilate_px: int = 3,
    save_path: Optional[Path] = None,
) -> Optional[np.ndarray]:
    """夜間基準画像から、電線などの細い静的線分をノイズ帯として抽出"""
    img = cv2.imread(night_image_path)
    if img is None:
        print(f"[WARN] ノイズ帯画像を読み込めません: {night_image_path}")
        return None

    proc_w, proc_h = proc_size
    resized = cv2.resize(img, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(denoised, 40, 120)

    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=30,
        minLineLength=max(20, proc_w // 15),
        maxLineGap=6,
    )

    nuisance = np.zeros((proc_h, proc_w), dtype=np.uint8)
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            length = float(np.hypot(x2 - x1, y2 - y1))
            if length < 15:
                continue
            cv2.line(nuisance, (x1, y1), (x2, y2), 255, 1, cv2.LINE_AA)

    if dilate_px > 0:
        k = max(1, int(dilate_px))
        dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        nuisance = cv2.dilate(nuisance, dilate_kernel)

    if save_path:
        try:
            cv2.imwrite(str(save_path), nuisance)
        except Exception:
            print(f"[WARN] ノイズ帯マスク保存に失敗: {save_path}")

    return nuisance
