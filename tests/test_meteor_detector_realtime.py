import numpy as np
from datetime import datetime

from meteor_detector_realtime import (
    estimate_fps_from_frames,
    make_detection_base_name,
    make_detection_id,
    probe_rtsp_endpoint,
    sanitize_fps,
)


def test_sanitize_fps_returns_default_for_invalid_values():
    assert sanitize_fps(0, default=25.0) == 25.0
    assert sanitize_fps(-10, default=25.0) == 25.0
    assert sanitize_fps(1000, default=25.0) == 25.0
    assert sanitize_fps(None, default=25.0) == 25.0


def test_estimate_fps_from_frames_20fps():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    # 0.05s間隔 -> 20fps
    frames = [(0.00, frame), (0.05, frame), (0.10, frame), (0.15, frame), (0.20, frame)]
    fps = estimate_fps_from_frames(frames, fallback_fps=30.0)
    assert abs(fps - 20.0) < 0.5


def test_estimate_fps_from_frames_15fps():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    # 0.0667s間隔 -> 約15fps
    frames = [(0.00, frame), (0.0667, frame), (0.1334, frame), (0.2001, frame)]
    fps = estimate_fps_from_frames(frames, fallback_fps=30.0)
    assert abs(fps - 15.0) < 0.5


def test_estimate_fps_from_frames_rejects_fps_far_above_negotiated():
    # 2026-08-16に本番greeng4で観測された事象の再現。接続時fps=20.0のカメラで
    # camera1/meteor_20260816_032802_79d9e49b.mp4 が108fpsで書き出されていた。
    # 約9.3ms間隔はsanitize_fps()の有効帯(1.0〜120.0)の内側のため既存の上限では
    # 弾けず、fallback_fps(20.0)との比率でのみ検出できる。
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frames = [(i / 108.0, frame) for i in range(20)]
    fps = estimate_fps_from_frames(frames, fallback_fps=20.0)
    assert fps == 20.0


def test_estimate_fps_from_frames_rejects_fps_within_sanitize_range():
    # 同上、camera2/meteor_20260816_030601_7f6b0f81.mp4 の117fpsケース。
    # 120.0未満のためsanitize_fps()を素通りする値であることが本テストの要点。
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frames = [(i / 117.0, frame) for i in range(20)]
    fps = estimate_fps_from_frames(frames, fallback_fps=20.0)
    assert fps == 20.0


def test_estimate_fps_from_frames_allows_normal_variation_within_ratio():
    # Tapo C120は夜間IRモードで実効fpsが接続時ネゴシエーション値(20.0)より
    # 下がることがある。10fps程度への低下は異常値ではないため推定値をそのまま使う。
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frames = [(0.00, frame), (0.10, frame), (0.20, frame), (0.30, frame)]
    fps = estimate_fps_from_frames(frames, fallback_fps=20.0)
    assert abs(fps - 10.0) < 0.5


def test_estimate_fps_from_frames_allows_fps_just_below_ratio_limit():
    # 許容倍率1.5の境界。fallback_fps=20.0に対し29.0fpsは閾値30.0未満のため
    # 推定値をそのまま採用する（境界判定は > のため30.0ちょうどはクランプされる）。
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frames = [(i / 29.0, frame) for i in range(20)]
    fps = estimate_fps_from_frames(frames, fallback_fps=20.0)
    assert abs(fps - 29.0) < 0.5


def test_probe_rtsp_endpoint_reports_tcp_ok(monkeypatch):
    class _DummySocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("meteor_detector_realtime.socket.create_connection", lambda addr, timeout=0: _DummySocket())
    result = probe_rtsp_endpoint("rtsp://user:pass@10.0.1.11/live")
    assert "probe=tcp_ok" in result
    assert "host=10.0.1.11" in result
    assert "port=554" in result


def test_probe_rtsp_endpoint_reports_tcp_error(monkeypatch):
    def _raise(addr, timeout=0):
        raise TimeoutError("timed out")

    monkeypatch.setattr("meteor_detector_realtime.socket.create_connection", _raise)
    result = probe_rtsp_endpoint("rtsp://user:pass@10.0.1.11:8554/live")
    assert "probe=tcp_error" in result
    assert "port=8554" in result
    assert "TimeoutError" in result


def test_make_detection_id_is_stable():
    record = {
        "timestamp": "2026-02-07T22:00:00.123456",
        "start_time": 1.0,
        "end_time": 1.4,
        "start_point": [10, 20],
        "end_point": [40, 50],
    }
    detection_id = make_detection_id("camera1", record)
    assert detection_id.startswith("det_")
    assert detection_id == make_detection_id("camera1", record)


def test_make_detection_base_name_avoids_existing_collision(tmp_path):
    detection_id = "det_1234567890abcdef1234"
    first = make_detection_base_name(tmp_path, datetime(2026, 2, 7, 22, 0, 0), detection_id)
    assert first == "meteor_20260207_220000_12345678"

    (tmp_path / f"{first}.mp4").write_bytes(b"x")
    second = make_detection_base_name(tmp_path, datetime(2026, 2, 7, 22, 0, 0), detection_id)
    assert second == "meteor_20260207_220000_12345678_02"
