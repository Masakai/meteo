"""
detection_state.py
検出システムのグローバル状態を DetectionState dataclass に集約する。

各モジュールは `from detection_state import state` で同一インスタンスを参照する。
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np


@dataclass(eq=False)
class DetectionState:
    # フレーム関連
    current_frame: Optional[np.ndarray] = None
    current_frame_lock: threading.Lock = field(default_factory=threading.Lock)
    current_frame_seq: int = 0
    current_stream_jpeg: Optional[bytes] = None
    current_stream_jpeg_seq: int = 0

    # 検出カウンタ・時刻
    detection_count: int = 0
    start_time_global: Optional[float] = None
    last_frame_time: float = 0

    # カメラ識別
    camera_name: str = ""
    camera_display_name: str = ""
    current_camera_name: str = ""  # 保存先・永続化用の識別子。display名は使わない

    # ストリーム設定
    stream_timeout: float = 10.0
    current_rtsp_url: str = ""

    # 検出状態フラグ
    is_detecting_now: bool = False
    current_detection_window_enabled: bool = False
    current_detection_window_active: bool = True
    current_detection_window_start: str = ""
    current_detection_window_end: str = ""
    current_detection_status: str = "INITIALIZING"
    current_detection_enabled: bool = True

    # 検出器オブジェクト
    current_detector: object = None

    # プロセッシング設定
    current_proc_size: tuple = (0, 0)
    current_mask_dilate: int = 20
    current_mask_save: Optional[object] = None
    current_nuisance_dilate: int = 3
    current_clip_margin_before: float = 1.0
    current_clip_margin_after: float = 1.0

    # 出力ディレクトリ
    current_output_dir: Optional[str] = None

    # 制御フラグ
    current_stop_flag: Optional[object] = None
    current_runtime_fps: float = 0.0
    current_runtime_overrides_paths: List[Path] = field(default_factory=list)

    # 保留中マスク
    current_pending_exclusion_mask: Optional[np.ndarray] = None
    current_pending_mask_save_path: Optional[Path] = None
    current_pending_mask_lock: threading.Lock = field(default_factory=threading.Lock)

    # 録画関連
    current_recording_lock: threading.RLock = field(default_factory=threading.RLock)
    current_recording_job: Optional[dict] = None

    # 薄明関連
    current_twilight_active: bool = False
    current_twilight_detection_mode: str = "reduce"
    current_twilight_type: str = "nautical"

    # 設定情報（ダッシュボード表示用）
    current_settings: dict = field(default_factory=lambda: {
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
    })


# モジュールレベルシングルトン
state = DetectionState()


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
