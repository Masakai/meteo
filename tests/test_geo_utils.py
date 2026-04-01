"""geo_utils の座標変換テスト"""
import math

import numpy as np
import pytest

from triangulation.geo_utils import (
    WGS84_A,
    az_el_to_enu,
    ecef_to_lla,
    enu_rotation_matrix,
    enu_to_az_el,
    enu_to_ecef_direction,
    lla_to_ecef,
    observation_line_ecef,
)


class TestLlaEcefRoundTrip:
    """LLA ↔ ECEF 変換のラウンドトリップテスト"""

    @pytest.mark.parametrize(
        "lat, lon, alt",
        [
            (0.0, 0.0, 0.0),           # 赤道・本初子午線
            (35.3606, 138.7274, 2400),  # 富士山付近
            (90.0, 0.0, 0.0),          # 北極
            (-33.8688, 151.2093, 50),   # シドニー
            (0.0, 180.0, 100000),       # 高高度
        ],
    )
    def test_round_trip(self, lat, lon, alt):
        ecef = lla_to_ecef(lat, lon, alt)
        lat2, lon2, alt2 = ecef_to_lla(ecef[0], ecef[1], ecef[2])

        assert abs(lat2 - lat) < 1e-8, f"lat: {lat} → {lat2}"
        assert abs(lon2 - lon) < 1e-8, f"lon: {lon} → {lon2}"
        assert abs(alt2 - alt) < 1e-3, f"alt: {alt} → {alt2}"

    def test_equator_prime_meridian(self):
        """赤道・本初子午線上の高度0はECEFのX軸上"""
        ecef = lla_to_ecef(0.0, 0.0, 0.0)
        assert abs(ecef[0] - WGS84_A) < 1.0
        assert abs(ecef[1]) < 1.0
        assert abs(ecef[2]) < 1.0

    def test_north_pole(self):
        """北極はECEFのZ軸上"""
        ecef = lla_to_ecef(90.0, 0.0, 0.0)
        assert abs(ecef[0]) < 1.0
        assert abs(ecef[1]) < 1.0
        assert ecef[2] > 6_350_000  # 短半径付近


class TestAzElEnu:
    """方位角・仰角 ↔ ENU 変換テスト"""

    def test_north_horizontal(self):
        """北・水平 → ENU(0, 1, 0)"""
        enu = az_el_to_enu(0.0, 0.0)
        np.testing.assert_allclose(enu, [0, 1, 0], atol=1e-10)

    def test_east_horizontal(self):
        """東・水平 → ENU(1, 0, 0)"""
        enu = az_el_to_enu(90.0, 0.0)
        np.testing.assert_allclose(enu, [1, 0, 0], atol=1e-10)

    def test_zenith(self):
        """天頂 → ENU(0, 0, 1)"""
        enu = az_el_to_enu(0.0, 90.0)
        np.testing.assert_allclose(enu, [0, 0, 1], atol=1e-10)

    def test_south_horizontal(self):
        """南・水平 → ENU(0, -1, 0)"""
        enu = az_el_to_enu(180.0, 0.0)
        np.testing.assert_allclose(enu, [0, -1, 0], atol=1e-10)

    def test_round_trip(self):
        """az_el → ENU → az_el のラウンドトリップ"""
        for az in [0, 45, 90, 135, 180, 225, 270, 315]:
            for el in [0, 15, 30, 45, 60, 75]:
                enu = az_el_to_enu(az, el)
                az2, el2 = enu_to_az_el(enu)
                assert abs(az2 - az) < 1e-8, f"az: {az} → {az2}"
                assert abs(el2 - el) < 1e-8, f"el: {el} → {el2}"


class TestEnuEcef:
    """ENU→ECEF方向変換テスト"""

    def test_up_at_equator_prime_meridian(self):
        """赤道・本初子午線でUp方向 → ECEF X方向"""
        R = enu_rotation_matrix(0.0, 0.0)
        up_enu = np.array([0, 0, 1])
        up_ecef = R @ up_enu
        # 赤道・本初子午線でのUp = ECEF X方向
        np.testing.assert_allclose(up_ecef, [1, 0, 0], atol=1e-10)

    def test_north_at_equator_prime_meridian(self):
        """赤道・本初子午線でNorth方向 → ECEF -Z方向付近"""
        R = enu_rotation_matrix(0.0, 0.0)
        north_enu = np.array([0, 1, 0])
        north_ecef = R @ north_enu
        # 赤道でのNorthは極方向 = +Z
        np.testing.assert_allclose(north_ecef, [0, 0, 1], atol=1e-10)

    def test_east_at_equator_prime_meridian(self):
        """赤道・本初子午線でEast方向 → ECEF Y方向"""
        R = enu_rotation_matrix(0.0, 0.0)
        east_enu = np.array([1, 0, 0])
        east_ecef = R @ east_enu
        np.testing.assert_allclose(east_ecef, [0, 1, 0], atol=1e-10)


class TestObservationLine:
    """観測線のテスト"""

    def test_observation_line_direction_unit_vector(self):
        """観測方向が単位ベクトルであること"""
        _, direction = observation_line_ecef(35.0, 139.0, 100.0, 90.0, 45.0)
        assert abs(np.linalg.norm(direction) - 1.0) < 1e-10

    def test_zenith_observation_points_away_from_earth(self):
        """天頂方向の観測は地球中心から離れる方向"""
        origin, direction = observation_line_ecef(35.0, 139.0, 100.0, 0.0, 90.0)
        # 天頂方向は origin と同じ方向（地球中心から外向き）
        origin_unit = origin / np.linalg.norm(origin)
        dot = np.dot(origin_unit, direction)
        assert dot > 0.99, f"天頂方向の内積: {dot}"
