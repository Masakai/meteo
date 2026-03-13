from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_compose import generate_dashboard, parse_streamers_line


def test_parse_streamers_line_url_only():
    parsed = parse_streamers_line("rtsp://user:pass@10.0.1.25/live")
    assert parsed == {
        "url": "rtsp://user:pass@10.0.1.25/live",
        "mask_path": "",
        "display_name": "",
    }


def test_parse_streamers_line_url_and_mask():
    parsed = parse_streamers_line("rtsp://user:pass@10.0.1.25/live|camera1.jpg")
    assert parsed == {
        "url": "rtsp://user:pass@10.0.1.25/live",
        "mask_path": "camera1.jpg",
        "display_name": "",
    }


def test_parse_streamers_line_url_and_display_name():
    parsed = parse_streamers_line("rtsp://user:pass@10.0.1.25/live||玄関カメラ")
    assert parsed == {
        "url": "rtsp://user:pass@10.0.1.25/live",
        "mask_path": "",
        "display_name": "玄関カメラ",
    }


def test_parse_streamers_line_url_mask_and_display_name():
    parsed = parse_streamers_line("rtsp://user:pass@10.0.1.25/live|camera1.jpg|玄関カメラ")
    assert parsed == {
        "url": "rtsp://user:pass@10.0.1.25/live",
        "mask_path": "camera1.jpg",
        "display_name": "玄関カメラ",
    }


def test_generate_dashboard_mounts_meteor_calendar_json():
    dashboard = generate_dashboard(
        cameras=[{"name": "camera1", "display_name": "玄関"}],
        base_port=8080,
        settings={},
    )
    assert "./imo_meteor_calender.json:/app/imo_meteor_calender.json:ro" in dashboard
