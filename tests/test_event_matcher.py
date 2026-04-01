"""イベントマッチャーのテスト"""
from datetime import datetime, timedelta, timezone

import pytest

from triangulation.event_matcher import EventMatcher
from triangulation.models import DetectionReport, StationConfig


def _make_station(station_id: str, lat: float, lon: float) -> StationConfig:
    return StationConfig(
        station_id=station_id,
        station_name=station_id,
        latitude=lat,
        longitude=lon,
        altitude=100.0,
        triangulation_server_url="",
        api_key="",
    )


def _make_report(
    station_id: str, timestamp: datetime, detection_id: str,
    start_az: float = 90.0, start_el: float = 45.0,
    end_az: float = 91.0, end_el: float = 43.0,
) -> DetectionReport:
    return DetectionReport(
        station_id=station_id,
        camera_name="cam1",
        timestamp=timestamp,
        start_az=start_az,
        start_el=start_el,
        end_az=end_az,
        end_el=end_el,
        duration=0.5,
        confidence=0.8,
        peak_brightness=200.0,
        detection_id=detection_id,
    )


class TestEventMatcherBasic:
    """基本的なマッチングテスト"""

    def test_no_match_same_station(self):
        """同一拠点の検出はマッチしない"""
        stations = {
            "A": _make_station("A", 35.0, 139.0),
            "B": _make_station("B", 35.0, 140.0),
        }
        matcher = EventMatcher(stations=stations, time_window=5.0)

        now = datetime.now(timezone.utc)
        r1 = _make_report("A", now, "det1")
        r2 = _make_report("A", now + timedelta(seconds=1), "det2")

        assert matcher.add_detection(r1) is None
        assert matcher.add_detection(r2) is None

    def test_no_match_outside_time_window(self):
        """時間窓外の検出はマッチしない"""
        stations = {
            "A": _make_station("A", 35.0, 139.0),
            "B": _make_station("B", 35.0, 140.0),
        }
        matcher = EventMatcher(stations=stations, time_window=5.0)

        now = datetime.now(timezone.utc)
        r1 = _make_report("A", now, "det1")
        r2 = _make_report("B", now + timedelta(seconds=10), "det2")

        assert matcher.add_detection(r1) is None
        assert matcher.add_detection(r2) is None

    def test_match_within_time_window(self):
        """時間窓内の異なる拠点の検出はマッチする（三角測量結果が妥当な場合）"""
        stations = {
            "A": _make_station("A", 35.0, 139.0),
            "B": _make_station("B", 35.0, 140.0),
        }
        matcher = EventMatcher(stations=stations, time_window=5.0)

        # 高度100km地点への方位仰角を使う（三角測量が成功するデータ）
        from tests.test_triangulator import _compute_az_el_from_station_to_target
        s_az_a, s_el_a = _compute_az_el_from_station_to_target(
            35.0, 139.0, 100.0, 35.3, 139.5, 100_000.0
        )
        e_az_a, e_el_a = _compute_az_el_from_station_to_target(
            35.0, 139.0, 100.0, 35.25, 139.55, 80_000.0
        )
        s_az_b, s_el_b = _compute_az_el_from_station_to_target(
            35.0, 140.0, 100.0, 35.3, 139.5, 100_000.0
        )
        e_az_b, e_el_b = _compute_az_el_from_station_to_target(
            35.0, 140.0, 100.0, 35.25, 139.55, 80_000.0
        )

        now = datetime.now(timezone.utc)
        r1 = _make_report("A", now, "det1",
                          start_az=s_az_a, start_el=s_el_a,
                          end_az=e_az_a, end_el=e_el_a)
        r2 = _make_report("B", now + timedelta(seconds=0.5), "det2",
                          start_az=s_az_b, start_el=s_el_b,
                          end_az=e_az_b, end_el=e_el_b)

        assert matcher.add_detection(r1) is None  # まだ相手がいない
        match = matcher.add_detection(r2)
        assert match is not None
        assert match.triangulated is not None
        assert 60 <= match.triangulated.start_alt <= 120

    def test_duplicate_detection_ignored(self):
        """同じdetection_idの検出は無視される"""
        stations = {
            "A": _make_station("A", 35.0, 139.0),
            "B": _make_station("B", 35.0, 140.0),
        }
        matcher = EventMatcher(stations=stations, time_window=5.0)
        matcher.matched_ids.add("det1")

        now = datetime.now(timezone.utc)
        r1 = _make_report("A", now, "det1")
        assert matcher.add_detection(r1) is None


class TestEventMatcherPruning:
    """バッファプルーニングのテスト"""

    def test_old_entries_pruned(self):
        """古いエントリはバッファから削除される"""
        stations = {"A": _make_station("A", 35.0, 139.0)}
        matcher = EventMatcher(stations=stations, buffer_duration=10.0)

        now = datetime.now(timezone.utc)
        old = _make_report("A", now - timedelta(seconds=20), "old")
        matcher.add_detection(old)
        assert len(matcher.buffer) == 1

        new = _make_report("A", now, "new")
        matcher.add_detection(new)
        # 古いエントリが削除されている
        assert len(matcher.buffer) == 1
        assert matcher.buffer[0].detection_id == "new"
