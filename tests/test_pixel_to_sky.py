"""pixel_to_sky のテスト"""
import math

import pytest

from triangulation.models import CameraCalibration
from triangulation.pixel_to_sky import pixel_to_sky


def _make_calibration(
    az=90.0, el=45.0, roll=0.0, fov_h=90.0, fov_v=60.0, w=960, h=540
) -> CameraCalibration:
    return CameraCalibration(
        camera_name="test",
        azimuth=az,
        elevation=el,
        roll=roll,
        fov_horizontal=fov_h,
        fov_vertical=fov_v,
        resolution=(w, h),
    )


class TestPixelToSkyCenter:
    """画像中心ピクセルがカメラの指向方位・仰角に一致するか"""

    @pytest.mark.parametrize(
        "az, el",
        [
            (0.0, 0.0),     # 北・水平
            (90.0, 45.0),   # 東・45度
            (180.0, 30.0),  # 南・30度
            (270.0, 60.0),  # 西・60度
            (45.0, 75.0),   # 北東・75度
        ],
    )
    def test_center_pixel_maps_to_camera_direction(self, az, el):
        cal = _make_calibration(az=az, el=el)
        cx, cy = cal.resolution[0] / 2.0, cal.resolution[1] / 2.0

        result_az, result_el = pixel_to_sky(cx, cy, cal)

        assert abs(result_az - az) < 0.1, f"方位: {az} → {result_az}"
        assert abs(result_el - el) < 0.1, f"仰角: {el} → {result_el}"


class TestPixelToSkyEdges:
    """画像端のピクセルが正しいオフセットを持つか"""

    def test_right_edge_increases_azimuth(self):
        """右端ピクセルは方位角が増加（東寄り）"""
        cal = _make_calibration(az=90.0, el=0.0, fov_h=90.0)
        w, h = cal.resolution
        # 中心
        az_center, _ = pixel_to_sky(w / 2.0, h / 2.0, cal)
        # 右端
        az_right, _ = pixel_to_sky(w - 1, h / 2.0, cal)
        # 右端は方位角が大きい（東方向=90度から増加）
        assert az_right > az_center, f"右端 {az_right} <= 中心 {az_center}"

    def test_top_edge_increases_elevation(self):
        """上端ピクセルは仰角が増加"""
        cal = _make_calibration(az=90.0, el=30.0, fov_v=60.0)
        w, h = cal.resolution
        # 中心
        _, el_center = pixel_to_sky(w / 2.0, h / 2.0, cal)
        # 上端
        _, el_top = pixel_to_sky(w / 2.0, 0, cal)
        assert el_top > el_center, f"上端 {el_top} <= 中心 {el_center}"

    def test_fov_coverage(self):
        """左端と右端の方位角差がFOVとほぼ一致（水平向きの場合）"""
        cal = _make_calibration(az=180.0, el=0.0, fov_h=60.0, fov_v=40.0)
        w, h = cal.resolution
        az_left, _ = pixel_to_sky(0, h / 2.0, cal)
        az_right, _ = pixel_to_sky(w, h / 2.0, cal)
        fov_measured = az_right - az_left
        assert abs(fov_measured - 60.0) < 1.0, f"FOV: {fov_measured} vs 60.0"


class TestPixelToSkySymmetry:
    """対称性テスト"""

    def test_horizontal_symmetry(self):
        """左右対称: 中心からの等距離ピクセルは方位角の偏差が等しい"""
        cal = _make_calibration(az=180.0, el=30.0)
        w, h = cal.resolution
        cx = w / 2.0

        az_center, _ = pixel_to_sky(cx, h / 2.0, cal)
        az_left, el_left = pixel_to_sky(cx - 100, h / 2.0, cal)
        az_right, el_right = pixel_to_sky(cx + 100, h / 2.0, cal)

        offset_left = abs(az_left - az_center)
        offset_right = abs(az_right - az_center)
        assert abs(offset_left - offset_right) < 0.1

    def test_vertical_symmetry(self):
        """上下対称: 中心からの等距離ピクセルは仰角の偏差が等しい"""
        cal = _make_calibration(az=90.0, el=45.0)
        w, h = cal.resolution
        cy = h / 2.0

        _, el_center = pixel_to_sky(w / 2.0, cy, cal)
        _, el_up = pixel_to_sky(w / 2.0, cy - 100, cal)
        _, el_down = pixel_to_sky(w / 2.0, cy + 100, cal)

        offset_up = abs(el_up - el_center)
        offset_down = abs(el_down - el_center)
        assert abs(offset_up - offset_down) < 0.5


class TestPixelToSkyRoll:
    """ロール回転のテスト"""

    def test_zero_roll_center_unchanged(self):
        """ロール=0 では中心は変わらない"""
        cal0 = _make_calibration(az=90.0, el=45.0, roll=0.0)
        cal30 = _make_calibration(az=90.0, el=45.0, roll=30.0)
        w, h = cal0.resolution

        az0, el0 = pixel_to_sky(w / 2.0, h / 2.0, cal0)
        az30, el30 = pixel_to_sky(w / 2.0, h / 2.0, cal30)

        assert abs(az0 - az30) < 0.1
        assert abs(el0 - el30) < 0.1
