import importlib

import dashboard_config


def test_dashboard_config_reads_stream_settings(monkeypatch):
    monkeypatch.setenv("CAMERA1_NAME", "cam1")
    monkeypatch.setenv("CAMERA1_URL", "http://localhost:8081")
    monkeypatch.setenv("CAMERA1_NAME_DISPLAY", "東")
    monkeypatch.setenv("CAMERA1_STREAM_KIND", "webrtc")
    monkeypatch.setenv("CAMERA1_STREAM_URL", "http://localhost:1984/stream.html?src=camera1&mode=webrtc")

    module = importlib.reload(dashboard_config)
    try:
        assert module.CAMERAS == [
            {
                "name": "cam1",
                "url": "http://localhost:8081",
                "display_name": "東",
                "stream_url": "http://localhost:1984/stream.html?src=camera1&mode=webrtc",
                "stream_kind": "webrtc",
            }
        ]
    finally:
        importlib.reload(dashboard_config)
