from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("astral")

import astro_utils


class FixedDatetime(datetime):
    fixed = None

    @classmethod
    def now(cls, tz=None):
        if cls.fixed is None:
            raise RuntimeError("fixed time not set")
        if tz is None:
            return cls.fixed.replace(tzinfo=None)
        return cls.fixed.astimezone(tz)


def test_is_detection_active_midday_false(monkeypatch):
    tz = ZoneInfo("Asia/Tokyo")
    FixedDatetime.fixed = datetime(2024, 1, 15, 12, 0, 0, tzinfo=tz)
    monkeypatch.setattr(astro_utils, "datetime", FixedDatetime)

    active, start, end = astro_utils.is_detection_active(35.6762, 139.6503, "Asia/Tokyo")
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert end > start
    assert active is False


def test_is_detection_active_night_true(monkeypatch):
    tz = ZoneInfo("Asia/Tokyo")
    FixedDatetime.fixed = datetime(2024, 1, 15, 2, 0, 0, tzinfo=tz)
    monkeypatch.setattr(astro_utils, "datetime", FixedDatetime)

    active, start, end = astro_utils.is_detection_active(35.6762, 139.6503, "Asia/Tokyo")
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert end > start
    assert active is True


def test_get_detection_window_for_date_returns_cross_midnight_window():
    start, end = astro_utils.get_detection_window_for_date(
        datetime(2024, 1, 15).date(),
        35.6762,
        139.6503,
        "Asia/Tokyo",
    )
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert start.date().isoformat() == "2024-01-15"
    assert end.date().isoformat() == "2024-01-16"
    assert end > start
