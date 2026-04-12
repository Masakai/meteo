"""
detection_filters.py
検出フィルタ・パラメータ変換ユーティリティ。

状態（state）に依存せず、純粋な関数として実装する。
"""

import copy

from meteor_detector_realtime import DetectionParams


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def build_twilight_params(sensitivity: str, min_speed: float, base_params):
    """薄明感度プリセットに応じた検出パラメータのコピーを返す。

    Args:
        sensitivity: "low" / "medium" / "high" / "faint"
        min_speed: 薄明時の最小速度（pixel/s）
        base_params: コピー元の DetectionParams

    Returns:
        プリセットを適用した DetectionParams のコピー
    """
    p = copy.copy(base_params)
    if sensitivity == "low":
        p.diff_threshold = 40
        p.min_brightness = 220
        p.min_speed = min_speed
    elif sensitivity == "medium":
        p.diff_threshold = 30
        p.min_brightness = 210
        p.min_speed = min_speed
    elif sensitivity == "high":
        p.diff_threshold = 20
        p.min_brightness = 180
        p.min_speed = min_speed
    elif sensitivity == "faint":
        p.diff_threshold = 16
        p.min_brightness = 150
        p.min_length = 10
        p.min_duration = 0.06
        p.min_speed = 10.0
        p.min_linearity = 0.55
        p.min_track_points = 3
        p.min_area = 5
        p.max_distance = 90
    return p


def filter_dark_objects(objects: list, min_brightness: float) -> list:
    """輝度が閾値未満のオブジェクト（鳥シルエット等の暗い物体）を除外する。

    detect_bright_objects() が返す objects の brightness キー（現フレームの
    輪郭内平均輝度）を使用。流星は発光体なので高輝度、鳥は暗いシルエットなので低輝度。

    Args:
        objects: detect_bright_objects() の戻り値
        min_brightness: これ未満の brightness を持つ候補を除外する閾値 (0-255)

    Returns:
        フィルタ後の objects リスト
    """
    if min_brightness <= 0:
        return objects
    return [o for o in objects if o.get("brightness", 0) >= min_brightness]


def apply_sensitivity_preset(params: DetectionParams, sensitivity: str) -> DetectionParams:
    """sensitivityプリセット（high/low/faint/fireball）をparamsに適用する。
    元の params を変更せず、更新済みの params を返す。
    """
    p = copy.copy(params)
    if sensitivity == "low":
        p.diff_threshold = 40
        p.min_brightness = 220
    elif sensitivity == "high":
        p.diff_threshold = 20
        p.min_brightness = 180
    elif sensitivity == "faint":
        p.diff_threshold = 16
        p.min_brightness = 150
        p.min_length = 10
        p.min_duration = 0.06
        p.min_speed = 10.0
        p.min_linearity = 0.55
        p.min_track_points = 3
        p.min_area = 5
        p.max_distance = 90
    elif sensitivity == "fireball":
        p.diff_threshold = 15
        p.min_brightness = 150
        p.max_duration = 20.0
        p.min_speed = 20.0
        p.min_linearity = 0.6
    return p
