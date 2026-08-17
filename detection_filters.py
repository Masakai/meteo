"""
detection_filters.py
検出フィルタ・パラメータ変換ユーティリティ。

状態（state）に依存せず、純粋な関数として実装する。
"""

import copy
from collections import deque
from typing import Deque

from meteor_detector_realtime import DetectionParams


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def build_twilight_params(sensitivity: str, min_speed: float, base_params, twilight_max_speed: float = 0.0):
    """薄明感度プリセットに応じた検出パラメータのコピーを返す。

    Args:
        sensitivity: "low" / "medium" / "high" / "faint"
        min_speed: 薄明時の最小速度（pixel/s）
        base_params: コピー元の DetectionParams
        twilight_max_speed: 方式3（薄明期間速度上限フィルタ）。0.0=無効
            （base_paramsのmax_speedをそのまま維持し、薄明時のみの上書きは
            行わない）。0.0超の場合のみ薄明時に限りmax_speedを上書きする。

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
    if twilight_max_speed > 0:
        p.max_speed = twilight_max_speed
    return p


class TwilightRateLimiter:
    """方式4: 薄明期間の確定イベントレートを監視するレート監視クラス。

    EventMergerの既存バースト抑制（burst_window_time秒オーダー、同一フレーム群
    内の空間的散発を検出）とは時間スケールが異なる分オーダーのレート現象
    （camera3の8/17事例: 28分で15件）を対象とする。独立コンポーネントとして
    実装し、EventMergerの到着ログ・ギャップクラスタリングには一切関与しない。

    状態はインスタンスにローカル保持する（プロセス内のみ、永続化しない）。
    """

    def __init__(self, window_sec: float = 300.0, max_events: int = 0):
        self.window_sec = window_sec
        self.max_events = max_events
        self._event_times: Deque[float] = deque()

    def record_event(self, now: float) -> None:
        """薄明期間中に確定したイベントを1件計上する。"""
        self._event_times.append(now)
        self._prune(now)

    def current_rate(self, now: float) -> int:
        """直近window_sec秒以内のイベント件数を返す（観測用）。"""
        self._prune(now)
        return len(self._event_times)

    def should_suppress(self, now: float) -> bool:
        """直近window_sec秒以内のイベント数がmax_eventsを超えていれば真を返す。

        max_events<=0の場合は観測専用モードとして常に偽を返す
        （抑制を発動しない）。
        """
        if self.max_events <= 0:
            return False
        return self.current_rate(now) > self.max_events

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_sec
        while self._event_times and self._event_times[0] < cutoff:
            self._event_times.popleft()


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
