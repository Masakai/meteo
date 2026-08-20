import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection_filters import apply_sensitivity_preset, build_twilight_params
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
