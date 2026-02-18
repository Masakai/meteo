import numpy as np

from meteor_detector_realtime import DetectionParams, RealtimeMeteorDetector


def _base_params() -> DetectionParams:
    params = DetectionParams()
    params.diff_threshold = 10
    params.min_brightness = 50
    params.min_brightness_tracking = 50
    params.min_area = 1
    params.max_area = 1000
    params.min_duration = 0.05
    params.max_duration = 5.0
    params.min_speed = 0.1
    params.min_linearity = 0.1
    params.min_length = 1
    params.max_length = 500
    return params


def test_detect_bright_objects_rejects_small_nuisance_overlap():
    params = _base_params()
    params.small_area_threshold = 100
    params.nuisance_overlap_threshold = 0.60

    nuisance_mask = np.zeros((100, 100), dtype=np.uint8)
    nuisance_mask[18:23, 10:90] = 255
    detector = RealtimeMeteorDetector(params, nuisance_mask=nuisance_mask)

    prev = np.zeros((100, 100), dtype=np.uint8)
    frame = prev.copy()
    frame[19:22, 38:42] = 255  # ノイズ帯上の小さい局所反射
    frame[68:72, 58:62] = 255  # ノイズ帯外の候補

    objects = detector.detect_bright_objects(frame, prev)
    assert len(objects) == 1
    assert objects[0]["centroid"][1] > 40


def test_finalize_track_rejects_by_stationary_ratio():
    params = _base_params()
    params.min_track_points = 4
    params.max_stationary_ratio = 0.40

    detector = RealtimeMeteorDetector(params)
    detector.active_tracks[0] = [
        (0.0, 50, 50, 200.0),
        (0.1, 50, 50, 200.0),
        (0.2, 51, 50, 200.0),
        (0.3, 51, 50, 200.0),
    ]

    assert detector._finalize_track(0) is None


def test_finalize_track_without_nuisance_mask_keeps_regression_behavior():
    params = _base_params()
    params.min_track_points = 4
    params.max_stationary_ratio = 0.95
    params.min_linearity = 0.8

    detector = RealtimeMeteorDetector(params)
    detector.active_tracks[0] = [
        (0.0, 10, 10, 220.0),
        (0.1, 13, 13, 225.0),
        (0.2, 16, 16, 230.0),
        (0.3, 19, 19, 235.0),
    ]

    event = detector._finalize_track(0)
    assert event is not None
    assert event.length > 0


def test_finalize_track_rejects_by_nuisance_path_overlap():
    params = _base_params()
    params.min_track_points = 4
    params.max_stationary_ratio = 0.95
    params.nuisance_path_overlap_threshold = 0.70

    nuisance_mask = np.zeros((120, 120), dtype=np.uint8)
    nuisance_mask[58:63, 10:110] = 255
    detector = RealtimeMeteorDetector(params, nuisance_mask=nuisance_mask)
    detector.active_tracks[0] = [
        (0.0, 20, 60, 220.0),
        (0.1, 35, 60, 230.0),
        (0.2, 50, 60, 240.0),
        (0.3, 65, 60, 245.0),
    ]

    assert detector._finalize_track(0) is None

