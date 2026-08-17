import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection_filters import apply_sensitivity_preset, build_twilight_params, TwilightRateLimiter
from meteor_detector_realtime import DetectionParams


def test_apply_sensitivity_preset_returns_copy():
    params = DetectionParams()
    result = apply_sensitivity_preset(params, "high")
    assert result is not params


def test_apply_sensitivity_preset_high_values():
    params = DetectionParams()
    result = apply_sensitivity_preset(params, "high")
    assert result.diff_threshold == 20
    assert result.min_brightness == 180


def test_build_twilight_params_returns_copy():
    params = DetectionParams()
    result = build_twilight_params("medium", 30.0, params)
    assert result is not params


def test_build_twilight_params_medium():
    params = DetectionParams()
    result = build_twilight_params("medium", 30.0, params)
    assert result.diff_threshold == 30
    assert result.min_brightness == 210
    assert result.min_speed == 30.0


def test_build_twilight_params_low():
    params = DetectionParams()
    result = build_twilight_params("low", 50.0, params)
    assert result.diff_threshold == 40
    assert result.min_brightness == 220
    assert result.min_speed == 50.0


def test_build_twilight_params_twilight_max_speed_default_does_not_override():
    # twilight_max_speed省略時（既定0.0）はbase_paramsのmax_speedを維持する。
    params = DetectionParams(max_speed=42.0)
    result = build_twilight_params("low", 50.0, params)
    assert result.max_speed == 42.0


def test_build_twilight_params_twilight_max_speed_overrides_when_positive():
    params = DetectionParams(max_speed=0.0)
    result = build_twilight_params("low", 50.0, params, twilight_max_speed=300.0)
    assert result.max_speed == 300.0


def test_twilight_rate_limiter_counts_events_within_window():
    limiter = TwilightRateLimiter(window_sec=300.0, max_events=0)
    limiter.record_event(0.0)
    limiter.record_event(100.0)
    limiter.record_event(200.0)
    assert limiter.current_rate(250.0) == 3


def test_twilight_rate_limiter_excludes_events_outside_window():
    limiter = TwilightRateLimiter(window_sec=300.0, max_events=0)
    limiter.record_event(0.0)
    limiter.record_event(100.0)
    # 300秒より前の記録は刈られる
    assert limiter.current_rate(400.0) == 1


def test_twilight_rate_limiter_should_suppress_threshold_boundary():
    limiter = TwilightRateLimiter(window_sec=300.0, max_events=3)
    for t in (0.0, 10.0, 20.0):
        limiter.record_event(t)
    # ちょうど3件（閾値と同数）は抑制しない
    assert limiter.should_suppress(30.0) is False
    limiter.record_event(30.0)
    # 4件目で閾値を超える
    assert limiter.should_suppress(30.0) is True


def test_twilight_rate_limiter_observation_mode_never_suppresses():
    # max_events<=0は観測専用モード。大量にイベントを積んでも抑制しない。
    limiter = TwilightRateLimiter(window_sec=300.0, max_events=0)
    for i in range(100):
        limiter.record_event(float(i))
    assert limiter.should_suppress(100.0) is False
