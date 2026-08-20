import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import meteor_detector_rtsp_web as web
from meteor_detector_realtime import DetectionParams
from detection_filters import build_twilight_params


def test_storage_camera_name_is_safe_identifier():
    assert web._storage_camera_name("camera1_10.0.1.25") == "camera1_10_0_1_25"


def test_storage_camera_name_does_not_use_display_name(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMERA_NAME_DISPLAY", "東側カメラ")
    paths = web._runtime_override_paths(str(tmp_path / "camera1"), "camera1_10.0.1.25")
    assert paths[0].name == "camera1_10_0_1_25.json"
    assert "東側" not in paths[0].name


def test_faint_preset_uses_lighter_runtime_defaults(monkeypatch):
    monkeypatch.delenv("CAMERA_NAME_DISPLAY", raising=False)
    monkeypatch.setattr(web, "RTSPReader", lambda url: None)

    params = DetectionParams()

    def _stop_before_io(*args, **kwargs):
        raise RuntimeError("stop")

    monkeypatch.setattr(Path, "mkdir", _stop_before_io)

    try:
        web.process_rtsp_stream("rtsp://example", output_dir="out", params=params, sensitivity="faint", cam_name="cam1")
    except RuntimeError as e:
        assert str(e) == "stop"

    assert params.min_brightness == 150
    assert params.min_area == 5
    assert params.max_distance == 90


class TestBuildTwilightParams:
    def _base(self):
        return DetectionParams()

    def test_low_sensitivity(self):
        p = build_twilight_params("low", 200.0, self._base())
        assert p.diff_threshold == 40
        assert p.min_brightness == 220
        assert p.min_speed == 200.0

    def test_medium_sensitivity(self):
        p = build_twilight_params("medium", 150.0, self._base())
        assert p.diff_threshold == 30
        assert p.min_brightness == 210
        assert p.min_speed == 150.0

    def test_high_sensitivity(self):
        p = build_twilight_params("high", 100.0, self._base())
        assert p.diff_threshold == 20
        assert p.min_brightness == 180
        assert p.min_speed == 100.0

    def test_faint_sensitivity_uses_fixed_min_speed(self):
        p = build_twilight_params("faint", 999.0, self._base())
        assert p.diff_threshold == 16
        assert p.min_brightness == 150
        assert p.min_length == 10
        assert p.min_duration == 0.06
        assert p.min_speed == 10.0
        assert p.min_linearity == 0.55
        assert p.min_track_points == 3
        assert p.min_area == 5
        assert p.max_distance == 90

    def test_does_not_mutate_base_params(self):
        base = self._base()
        original_diff = base.diff_threshold
        build_twilight_params("low", 200.0, base)
        assert base.diff_threshold == original_diff
