"""WGS84測地系の座標変換ユーティリティ

座標系:
- LLA: 緯度(度), 経度(度), 高度(m) -- WGS84楕円体
- ECEF: 地球中心直交座標 (m)
- ENU: 東(East), 北(North), 上(Up) -- ローカル接平面座標
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

# WGS84楕円体パラメータ
WGS84_A = 6_378_137.0          # 長半径 (m)
WGS84_F = 1.0 / 298.257223563  # 扁平率
WGS84_B = WGS84_A * (1.0 - WGS84_F)  # 短半径
WGS84_E2 = 2.0 * WGS84_F - WGS84_F ** 2  # 第一離心率の二乗


def lla_to_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> np.ndarray:
    """緯度経度高度 → ECEF座標 (m)"""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)

    N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat ** 2)

    x = (N + alt_m) * cos_lat * cos_lon
    y = (N + alt_m) * cos_lat * sin_lon
    z = (N * (1.0 - WGS84_E2) + alt_m) * sin_lat

    return np.array([x, y, z])


def ecef_to_lla(x: float, y: float, z: float) -> Tuple[float, float, float]:
    """ECEF座標 → 緯度(度), 経度(度), 高度(m)

    Bowring法による反復計算（通常2-3回で収束）
    """
    lon = math.atan2(y, x)
    p = math.sqrt(x ** 2 + y ** 2)

    # 初期推定
    lat = math.atan2(z, p * (1.0 - WGS84_E2))

    for _ in range(10):
        sin_lat = math.sin(lat)
        N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat ** 2)
        lat_new = math.atan2(z + WGS84_E2 * N * sin_lat, p)
        if abs(lat_new - lat) < 1e-12:
            break
        lat = lat_new

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat ** 2)

    if abs(cos_lat) > 1e-10:
        alt = p / cos_lat - N
    else:
        alt = abs(z) - WGS84_B

    return math.degrees(lat), math.degrees(lon), alt


def enu_rotation_matrix(lat_deg: float, lon_deg: float) -> np.ndarray:
    """ENU→ECEF変換の回転行列 (3x3)

    ENU座標系の基底ベクトルをECEFで表現する行列。
    v_ecef = R @ v_enu
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)

    # 列ベクトル: East, North, Up のECEF表現
    return np.array([
        [-sin_lon,          -sin_lat * cos_lon, cos_lat * cos_lon],
        [ cos_lon,          -sin_lat * sin_lon, cos_lat * sin_lon],
        [ 0.0,               cos_lat,           sin_lat          ],
    ])


def az_el_to_enu(az_deg: float, el_deg: float) -> np.ndarray:
    """方位角・仰角 → ENU単位方向ベクトル

    az_deg: 方位角 (度), 0=北, 90=東
    el_deg: 仰角 (度), 0=水平, 90=天頂
    """
    az = math.radians(az_deg)
    el = math.radians(el_deg)

    cos_el = math.cos(el)
    east = math.sin(az) * cos_el
    north = math.cos(az) * cos_el
    up = math.sin(el)

    return np.array([east, north, up])


def enu_to_az_el(enu: np.ndarray) -> Tuple[float, float]:
    """ENU単位方向ベクトル → 方位角(度), 仰角(度)"""
    east, north, up = enu[0], enu[1], enu[2]

    az = math.degrees(math.atan2(east, north)) % 360.0
    el = math.degrees(math.asin(np.clip(up / np.linalg.norm(enu), -1.0, 1.0)))

    return az, el


def enu_to_ecef_direction(
    enu_dir: np.ndarray, ref_lat_deg: float, ref_lon_deg: float
) -> np.ndarray:
    """ENU方向ベクトルをECEF方向ベクトルに変換（位置ではなく方向のみ）"""
    R = enu_rotation_matrix(ref_lat_deg, ref_lon_deg)
    return R @ enu_dir


def observation_line_ecef(
    station_lat: float,
    station_lon: float,
    station_alt: float,
    az_deg: float,
    el_deg: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """観測線をECEF座標系で返す

    Returns:
        (origin, direction): 拠点のECEF位置, 観測方向のECEF単位ベクトル
    """
    origin = lla_to_ecef(station_lat, station_lon, station_alt)
    enu_dir = az_el_to_enu(az_deg, el_deg)
    ecef_dir = enu_to_ecef_direction(enu_dir, station_lat, station_lon)
    ecef_dir = ecef_dir / np.linalg.norm(ecef_dir)
    return origin, ecef_dir
