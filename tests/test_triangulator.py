"""三角測量アルゴリズムのテスト

既知の2拠点・既知の流星位置から方位仰角を逆算し、
三角測量結果が元の位置と一致するか検証する。
"""
import math
from datetime import datetime, timezone

import numpy as np
import pytest

from triangulation.geo_utils import (
    ecef_to_lla,
    enu_to_az_el,
    lla_to_ecef,
)
from triangulation.models import DetectionReport, StationConfig
from triangulation.triangulator import (
    closest_approach,
    triangulate_meteor,
    triangulate_point,
)


def _make_station(station_id: str, lat: float, lon: float, alt: float = 0.0):
    return StationConfig(
        station_id=station_id,
        station_name=station_id,
        latitude=lat,
        longitude=lon,
        altitude=alt,
        triangulation_server_url="",
        api_key="",
    )


def _compute_az_el_from_station_to_target(
    station_lat: float, station_lon: float, station_alt: float,
    target_lat: float, target_lon: float, target_alt: float,
) -> tuple[float, float]:
    """拠点から目標への方位角・仰角を計算"""
    station_ecef = lla_to_ecef(station_lat, station_lon, station_alt)
    target_ecef = lla_to_ecef(target_lat, target_lon, target_alt)

    # ECEF差分ベクトル
    diff = target_ecef - station_ecef

    # ECEF → ENU変換
    from triangulation.geo_utils import enu_rotation_matrix
    R = enu_rotation_matrix(station_lat, station_lon)
    enu = R.T @ diff  # R^T @ ecef_diff = enu

    az, el = enu_to_az_el(enu)
    return az, el


class TestClosestApproach:
    """closest_approach 関数のテスト"""

    def test_intersecting_lines(self):
        """交差する2直線 → miss_distance ≈ 0"""
        p1 = np.array([0.0, 0.0, 0.0])
        d1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([5.0, -5.0, 0.0])
        d2 = np.array([0.0, 1.0, 0.0])

        result = closest_approach(p1, d1, p2, d2)
        assert result is not None
        midpoint, miss = result
        assert miss < 1e-10
        np.testing.assert_allclose(midpoint, [5.0, 0.0, 0.0], atol=1e-10)

    def test_skew_lines(self):
        """ねじれの位置の2直線"""
        p1 = np.array([0.0, 0.0, 0.0])
        d1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([0.0, 0.0, 10.0])
        d2 = np.array([0.0, 1.0, 0.0])

        result = closest_approach(p1, d1, p2, d2)
        assert result is not None
        midpoint, miss = result
        assert abs(miss - 10.0) < 1e-10

    def test_parallel_lines_returns_none(self):
        """平行線 → None"""
        p1 = np.array([0.0, 0.0, 0.0])
        d1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([0.0, 1.0, 0.0])
        d2 = np.array([1.0, 0.0, 0.0])

        result = closest_approach(p1, d1, p2, d2)
        assert result is None

    def test_backward_direction_returns_none(self):
        """拠点の後方にある場合 → None"""
        p1 = np.array([0.0, 0.0, 0.0])
        d1 = np.array([1.0, 0.0, 0.0])  # +X方向
        p2 = np.array([-10.0, 1.0, 0.0])
        d2 = np.array([0.0, -1.0, 0.0])  # -Y方向

        # 交点は (-10, 0, 0) → p1からは -X方向 → t < 0
        result = closest_approach(p1, d1, p2, d2)
        assert result is None


class TestTriangulatePoint:
    """triangulate_point のテスト"""

    def test_known_target(self):
        """既知の目標位置を三角測量で再現"""
        # 2つの拠点（約100km離れた位置）
        station_a = _make_station("A", 35.0, 139.0, 100.0)
        station_b = _make_station("B", 35.0, 140.0, 100.0)

        # 流星位置: 高度100km、2拠点の中間上空付近
        target_lat, target_lon, target_alt_m = 35.3, 139.5, 100_000.0

        # 各拠点から目標への方位角・仰角を計算
        az_a, el_a = _compute_az_el_from_station_to_target(
            35.0, 139.0, 100.0, target_lat, target_lon, target_alt_m
        )
        az_b, el_b = _compute_az_el_from_station_to_target(
            35.0, 140.0, 100.0, target_lat, target_lon, target_alt_m
        )

        result = triangulate_point(station_a, az_a, el_a, station_b, az_b, el_b)
        assert result is not None

        lat, lon, alt_km, miss_km = result
        assert abs(lat - target_lat) < 0.01, f"lat: {lat} vs {target_lat}"
        assert abs(lon - target_lon) < 0.01, f"lon: {lon} vs {target_lon}"
        assert abs(alt_km - 100.0) < 0.5, f"alt: {alt_km} vs 100.0"
        assert miss_km < 0.1, f"miss: {miss_km} km"


class TestTriangulateMeteor:
    """triangulate_meteor のテスト"""

    def test_synthetic_meteor(self):
        """合成データで流星軌道を三角測量"""
        station_a = _make_station("A", 35.0, 139.0, 100.0)
        station_b = _make_station("B", 35.0, 140.0, 100.0)

        # 流星の始点と終点
        start_lat, start_lon, start_alt = 35.3, 139.5, 100_000.0
        end_lat, end_lon, end_alt = 35.25, 139.55, 80_000.0

        # 各拠点からの方位仰角を計算
        s_az_a, s_el_a = _compute_az_el_from_station_to_target(
            35.0, 139.0, 100.0, start_lat, start_lon, start_alt
        )
        e_az_a, e_el_a = _compute_az_el_from_station_to_target(
            35.0, 139.0, 100.0, end_lat, end_lon, end_alt
        )
        s_az_b, s_el_b = _compute_az_el_from_station_to_target(
            35.0, 140.0, 100.0, start_lat, start_lon, start_alt
        )
        e_az_b, e_el_b = _compute_az_el_from_station_to_target(
            35.0, 140.0, 100.0, end_lat, end_lon, end_alt
        )

        now = datetime.now(timezone.utc)
        det_a = DetectionReport(
            station_id="A", camera_name="cam1", timestamp=now,
            start_az=s_az_a, start_el=s_el_a,
            end_az=e_az_a, end_el=e_el_a,
            duration=0.5, confidence=0.8, peak_brightness=200,
            detection_id="det_a_001",
        )
        det_b = DetectionReport(
            station_id="B", camera_name="cam1", timestamp=now,
            start_az=s_az_b, start_el=s_el_b,
            end_az=e_az_b, end_el=e_el_b,
            duration=0.5, confidence=0.7, peak_brightness=180,
            detection_id="det_b_001",
        )

        result = triangulate_meteor(det_a, det_b, station_a, station_b)
        assert result is not None

        # 始点の検証
        assert abs(result.start_lat - start_lat) < 0.01
        assert abs(result.start_lon - start_lon) < 0.01
        assert abs(result.start_alt - 100.0) < 0.5

        # 終点の検証
        assert abs(result.end_lat - end_lat) < 0.01
        assert abs(result.end_lon - end_lon) < 0.01
        assert abs(result.end_alt - 80.0) < 0.5

        # 速度が正の値であること
        assert result.velocity is not None
        assert result.velocity > 0

    def test_ground_level_meteor_rejected(self):
        """地表付近の結果は棄却される"""
        station_a = _make_station("A", 35.0, 139.0, 100.0)
        station_b = _make_station("B", 35.0, 140.0, 100.0)

        # 高度1km（非現実的な流星高度）
        target_lat, target_lon, target_alt = 35.3, 139.5, 1_000.0
        s_az_a, s_el_a = _compute_az_el_from_station_to_target(
            35.0, 139.0, 100.0, target_lat, target_lon, target_alt
        )
        s_az_b, s_el_b = _compute_az_el_from_station_to_target(
            35.0, 140.0, 100.0, target_lat, target_lon, target_alt
        )

        now = datetime.now(timezone.utc)
        det_a = DetectionReport(
            station_id="A", camera_name="cam1", timestamp=now,
            start_az=s_az_a, start_el=s_el_a,
            end_az=s_az_a + 1, end_el=s_el_a - 1,
            duration=0.5, confidence=0.8, peak_brightness=200,
            detection_id="det_low_a",
        )
        det_b = DetectionReport(
            station_id="B", camera_name="cam1", timestamp=now,
            start_az=s_az_b, start_el=s_el_b,
            end_az=s_az_b + 1, end_el=s_el_b - 1,
            duration=0.5, confidence=0.7, peak_brightness=180,
            detection_id="det_low_b",
        )

        result = triangulate_meteor(det_a, det_b, station_a, station_b)
        assert result is None  # 高度範囲外で棄却
