import pytest
import generate_compose as gc
from generate_compose import generate_compose, generate_go2rtc_config


def test_generate_compose_includes_webrtc_dashboard_and_go2rtc(tmp_path):
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live||東側\n", encoding="utf-8")

    compose = generate_compose(
        str(streamers),
        {
            "sensitivity": "medium",
            "scale": "0.5",
            "buffer": "15",
            "exclude_bottom": "0.0625",
            "extract_clips": "true",
            "latitude": "35.0",
            "longitude": "139.0",
            "enable_time_window": "true",
            "mask_output_dir": "masks",
            "mask_dilate": "20",
            "mask_save": "",
            "streaming_mode": "webrtc",
            "go2rtc_api_port": 1984,
            "go2rtc_webrtc_port": 8555,
            "go2rtc_config_path": "./go2rtc.yaml",
            "go2rtc_candidate_host": "10.0.1.59",
        },
        base_port=8080,
    )

    assert "meteor-go2rtc" in compose
    assert "CAMERA1_STREAM_KIND=webrtc" in compose
    assert "CAMERA1_STREAM_URL=http://localhost:1984/stream.html?src=camera1&mode=webrtc&mode=mse&mode=hls&mode=mjpeg&background=false" in compose
    assert "./go2rtc.yaml:/config/go2rtc.yaml" in compose


def test_generate_go2rtc_config_uses_camera_sources():
    config = generate_go2rtc_config(
        [
            {"url": "rtsp://user:pass@192.168.0.11/live"},
            {"url": "rtsp://user:pass@192.168.0.12/live"},
        ],
        {"go2rtc_candidate_host": "10.0.1.59", "go2rtc_webrtc_port": 8555},
    )
    assert 'origin: "*"' in config
    assert "webrtc:" in config
    assert "    - 10.0.1.59:8555" in config
    assert "camera1:" in config
    assert "camera2:" in config
    assert "rtsp://user:pass@192.168.0.11/live" in config
    assert "rtsp://user:pass@192.168.0.12/live" in config


def test_generate_compose_defaults_streaming_mode_to_webrtc(tmp_path):
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live\n", encoding="utf-8")

    compose = generate_compose(
        str(streamers),
        {
            "sensitivity": "medium",
            "scale": "0.5",
            "buffer": "15",
            "exclude_bottom": "0.0625",
            "extract_clips": "true",
            "latitude": "35.0",
            "longitude": "139.0",
            "enable_time_window": "true",
            "mask_output_dir": "masks",
            "mask_dilate": "20",
            "mask_save": "",
            "go2rtc_api_port": 1984,
            "go2rtc_webrtc_port": 8555,
            "go2rtc_config_path": "./go2rtc.yaml",
            "go2rtc_candidate_host": "10.0.1.59",
        },
        base_port=8080,
    )

    assert "meteor-go2rtc" in compose
    assert "CAMERA1_STREAM_KIND=webrtc" in compose


_BASE_SETTINGS = {
    "sensitivity": "medium",
    "scale": "0.5",
    "buffer": "15",
    "exclude_bottom": "0.0625",
    "extract_clips": "true",
    "latitude": "35.0",
    "longitude": "139.0",
    "enable_time_window": "true",
    "mask_output_dir": "masks",
    "mask_dilate": "20",
    "mask_save": "",
    "streaming_mode": "webrtc",
    "go2rtc_api_port": 1984,
    "go2rtc_webrtc_port": 8555,
    "go2rtc_config_path": "./go2rtc.yaml",
    "go2rtc_candidate_host": "10.0.1.59",
}


def test_generate_compose_exits_when_mask_set_and_cv2_unavailable(tmp_path, monkeypatch):
    """マスク指定 + cv2 なしの場合は sys.exit(1) で中止する"""
    mask_file = tmp_path / "mask.jpg"
    mask_file.write_bytes(b"")

    streamers = tmp_path / "streamers"
    streamers.write_text(f"rtsp://user:pass@192.168.0.11/live|{mask_file}|East\n", encoding="utf-8")

    monkeypatch.setattr(gc, "cv2", None)

    with pytest.raises(SystemExit) as exc_info:
        generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)

    assert exc_info.value.code == 1


def test_generate_compose_no_exit_when_no_mask_and_cv2_unavailable(tmp_path, monkeypatch):
    """マスク未指定なら cv2 がなくても中止しない"""
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live||East\n", encoding="utf-8")

    monkeypatch.setattr(gc, "cv2", None)

    compose = generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)
    assert "meteor-camera1" in compose


def test_generate_compose_invalid_url_masks_password(tmp_path, capsys):
    """無効URLの警告出力でパスワードが *** に置換されること"""
    streamers = tmp_path / "streamers"
    # http:// スキームは parse_rtsp_url が無効と判定するため警告ブランチに入る
    streamers.write_text("http://user:secretpass@host/path\n", encoding="utf-8")

    with pytest.raises(ValueError):
        generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)

    captured = capsys.readouterr()
    assert "secretpass" not in captured.out
    assert "***" in captured.out
