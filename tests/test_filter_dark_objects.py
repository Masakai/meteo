import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from meteor_detector_rtsp_web import filter_dark_objects


def test_min_brightness_zero_returns_all():
    objects = [{"brightness": 10}, {"brightness": 50}, {"brightness": 200}]
    result = filter_dark_objects(objects, 0)
    assert result == objects


def test_min_brightness_negative_returns_all():
    objects = [{"brightness": 5}, {"brightness": 255}]
    result = filter_dark_objects(objects, -1)
    assert result == objects


def test_filters_below_threshold():
    objects = [
        {"brightness": 79},
        {"brightness": 80},
        {"brightness": 150},
    ]
    result = filter_dark_objects(objects, 80)
    assert len(result) == 2
    assert all(o["brightness"] >= 80 for o in result)


def test_retains_exactly_at_threshold():
    objects = [{"brightness": 80}]
    result = filter_dark_objects(objects, 80)
    assert result == objects


def test_empty_list():
    result = filter_dark_objects([], 80)
    assert result == []


def test_missing_brightness_key_excluded():
    objects = [{"area": 100}, {"brightness": 90}]
    result = filter_dark_objects(objects, 80)
    assert len(result) == 1
    assert result[0]["brightness"] == 90


def test_all_excluded():
    objects = [{"brightness": 10}, {"brightness": 20}, {"brightness": 30}]
    result = filter_dark_objects(objects, 100)
    assert result == []


def test_just_above_threshold_passes():
    objects = [{"brightness": 81}]
    result = filter_dark_objects(objects, 80)
    assert result == objects
