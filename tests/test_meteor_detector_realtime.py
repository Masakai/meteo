import numpy as np

from meteor_detector_realtime import estimate_fps_from_frames, sanitize_fps


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
