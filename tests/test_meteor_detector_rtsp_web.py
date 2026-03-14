import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import meteor_detector_rtsp_web as web
from meteor_detector_realtime import DetectionParams


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
