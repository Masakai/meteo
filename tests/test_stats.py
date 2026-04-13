"""tests/test_stats.py - compute_nightly_stats の重複除去ロジックをテスト"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import dashboard_routes as dr


_TZ_STR = "Asia/Tokyo"


def _make_rows(camera, timestamps):
    """(camera, timestamp_str) のリストからDBロウ形式のリストを返す"""
    return [{"id": f"det_{i}", "camera": camera, "timestamp": ts} for i, ts in enumerate(timestamps)]


def _sunset_sunrise(date_str):
    from datetime import date
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(_TZ_STR)
    d = date.fromisoformat(date_str)
    base = datetime(d.year, d.month, d.day, 18, 0, 0, tzinfo=tz)
    return base, base + timedelta(hours=11)


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("LATITUDE", "35.3606")
    monkeypatch.setenv("LONGITUDE", "138.7274")
    monkeypatch.setenv("TIMEZONE", _TZ_STR)


class TestComputeNightlyStats:
    def _run(self, rows_by_window, days=1, cameras=None):
        """helper: astro_utils と detection_store をモックして compute_nightly_stats を実行"""
        camera_display_names = cameras or {"cam_east": "East", "cam_south": "South"}

        call_count = [0]

        def fake_window(target_date, lat, lon, tz):
            return _sunset_sunrise(target_date.isoformat())

        def fake_query(db_path, start_ts, end_ts):
            idx = call_count[0]
            call_count[0] += 1
            return rows_by_window[idx] if idx < len(rows_by_window) else []

        with patch.object(dr, "_get_detection_window_for_date", side_effect=fake_window), \
             patch("detection_store.query_detections_for_stats", side_effect=fake_query):
            result = dr.compute_nightly_stats("fake.db", camera_display_names, days=days)

        return result

    def test_no_detections(self):
        result = self._run([[]])
        assert result["total_events"] == 0
        assert len(result["nights"]) == 1
        assert result["nights"][0]["total"] == 0
        assert result["nights"][0]["duplicates"] == 0

    def test_single_camera_no_duplicate(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_TZ_STR)
        t1 = datetime(2026, 4, 12, 21, 0, 0, tzinfo=tz).isoformat()
        t2 = datetime(2026, 4, 12, 21, 10, 0, tzinfo=tz).isoformat()
        rows = _make_rows("cam_east", [t1, t2])

        result = self._run([rows])
        assert result["nights"][0]["total"] == 2
        assert result["nights"][0]["duplicates"] == 0
        assert result["nights"][0]["by_camera"]["East"] == 2

    def test_same_camera_within_5s_is_duplicate(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_TZ_STR)
        base = datetime(2026, 4, 12, 21, 0, 0, tzinfo=tz)
        t1 = base.isoformat()
        t2 = (base + timedelta(seconds=3)).isoformat()
        rows = _make_rows("cam_east", [t1, t2])

        result = self._run([rows])
        night = result["nights"][0]
        assert night["total"] == 1
        assert night["duplicates"] == 1

    def test_same_camera_exactly_5s_is_duplicate(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_TZ_STR)
        base = datetime(2026, 4, 12, 21, 0, 0, tzinfo=tz)
        t1 = base.isoformat()
        t2 = (base + timedelta(seconds=5)).isoformat()
        rows = _make_rows("cam_east", [t1, t2])

        result = self._run([rows])
        night = result["nights"][0]
        assert night["total"] == 1
        assert night["duplicates"] == 1

    def test_different_cameras_within_5s_is_duplicate(self):
        """異なるカメラでも5秒以内は同一流星→重複扱い"""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_TZ_STR)
        base = datetime(2026, 4, 12, 21, 0, 0, tzinfo=tz)
        rows = [
            {"id": "det_0", "camera": "cam_east", "timestamp": base.isoformat()},
            {"id": "det_1", "camera": "cam_south", "timestamp": (base + timedelta(seconds=2)).isoformat()},
        ]

        result = self._run([rows])
        night = result["nights"][0]
        assert night["total"] == 1
        assert night["duplicates"] == 1

    def test_different_cameras_over_5s_not_duplicate(self):
        """5秒超は別流星"""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_TZ_STR)
        base = datetime(2026, 4, 12, 21, 0, 0, tzinfo=tz)
        rows = [
            {"id": "det_0", "camera": "cam_east", "timestamp": base.isoformat()},
            {"id": "det_1", "camera": "cam_south", "timestamp": (base + timedelta(seconds=6)).isoformat()},
        ]

        result = self._run([rows])
        night = result["nights"][0]
        assert night["total"] == 2
        assert night["duplicates"] == 0
        assert night["by_camera"]["East"] == 1
        assert night["by_camera"]["South"] == 1

    def test_multiple_nights_total_events(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_TZ_STR)
        t1 = datetime(2026, 4, 12, 21, 0, 0, tzinfo=tz).isoformat()
        t2 = datetime(2026, 4, 11, 21, 0, 0, tzinfo=tz).isoformat()
        rows_night1 = _make_rows("cam_east", [t1])
        rows_night2 = _make_rows("cam_south", [t2])

        result = self._run([rows_night1, rows_night2], days=2)
        assert result["total_events"] == 2
        assert len(result["nights"]) == 2

    def test_cameras_list_in_result(self):
        result = self._run([[]])
        assert set(result["cameras"]) == {"East", "South"}

    def test_astro_utils_unavailable(self, monkeypatch):
        """_get_detection_window_for_date が None の場合は nights が空"""
        monkeypatch.setattr(dr, "_get_detection_window_for_date", None)
        camera_display_names = {"cam_east": "East"}
        result = dr.compute_nightly_stats("fake.db", camera_display_names, days=3)
        assert result["nights"] == []
        assert result["total_events"] == 0


class TestComputeHourlyStats:
    def _run(self, rows_by_window, days=1, cameras=None):
        """helper: astro_utils と detection_store をモックして compute_hourly_stats を実行"""
        camera_display_names = cameras or {"cam_east": "East", "cam_south": "South"}

        call_count = [0]

        def fake_window(target_date, lat, lon, tz):
            return _sunset_sunrise(target_date.isoformat())

        def fake_query(db_path, start_ts, end_ts):
            idx = call_count[0]
            call_count[0] += 1
            return rows_by_window[idx] if idx < len(rows_by_window) else []

        with patch.object(dr, "_get_detection_window_for_date", side_effect=fake_window), \
             patch("detection_store.query_detections_for_stats", side_effect=fake_query):
            result = dr.compute_hourly_stats("fake.db", camera_display_names, days=days)

        return result

    def test_no_detections(self):
        """検出なし → 全時間帯が0"""
        result = self._run([[]])
        assert result["hours"] == list(range(24))
        assert "East" in result["by_hour"]
        assert result["by_hour"]["East"] == [0] * 24
        assert result["by_hour"]["South"] == [0] * 24

    def test_single_detection_at_21_jst(self):
        """21時JST検出1件 → by_hour['East'][21] == 1、他は0"""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_TZ_STR)
        t = datetime(2026, 4, 12, 21, 0, 0, tzinfo=tz).isoformat()
        rows = _make_rows("cam_east", [t])

        result = self._run([rows])
        assert result["by_hour"]["East"][21] == 1
        assert sum(result["by_hour"]["East"]) == 1
        assert sum(result["by_hour"]["South"]) == 0

    def test_within_5s_same_camera_deduped(self):
        """5秒以内の同カメラ2件 → 重複除去で1件のみカウント"""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_TZ_STR)
        base = datetime(2026, 4, 12, 21, 30, 0, tzinfo=tz)
        t1 = base.isoformat()
        t2 = (base + timedelta(seconds=3)).isoformat()
        rows = _make_rows("cam_east", [t1, t2])

        result = self._run([rows])
        assert sum(result["by_hour"]["East"]) == 1
        assert result["by_hour"]["East"][21] == 1
