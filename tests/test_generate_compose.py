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
    assert "./go2rtc.yaml:/config/go2rtc.yaml:ro" in compose


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
