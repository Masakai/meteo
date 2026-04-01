"""ピクセル座標から天球座標（方位角・仰角）への変換

ピンホールカメラモデル（直線射影）を使用。
カメラの光軸中心の方位・仰角・ロール + FOVから、
任意のピクセル位置に対応する天球上の方向を計算する。
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from triangulation.models import CameraCalibration


def _rotation_x(angle_rad: float) -> np.ndarray:
    """X軸周りの回転行列"""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([
        [1, 0,  0],
        [0, c, -s],
        [0, s,  c],
    ])


def _rotation_y(angle_rad: float) -> np.ndarray:
    """Y軸周りの回転行列"""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([
        [ c, 0, s],
        [ 0, 1, 0],
        [-s, 0, c],
    ])


def _rotation_z(angle_rad: float) -> np.ndarray:
    """Z軸周りの回転行列"""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([
        [c, -s, 0],
        [s,  c, 0],
        [0,  0, 1],
    ])


def pixel_to_sky(
    px: float,
    py: float,
    calibration: CameraCalibration,
) -> Tuple[float, float]:
    """ピクセル座標 → 天球座標（方位角, 仰角）

    ピンホールカメラモデル（直線射影 / rectilinear projection）を使用。

    カメラ座標系:
        Z軸 = 光軸方向（前方）
        X軸 = 右方向
        Y軸 = 上方向

    Args:
        px: ピクセルX座標 (0=左端)
        py: ピクセルY座標 (0=上端)
        calibration: カメラキャリブレーション設定

    Returns:
        (azimuth, elevation): 方位角(度, 0=北, 90=東), 仰角(度)
    """
    width, height = calibration.resolution

    # 1. ピクセルを正規化座標に変換 [-1, 1]
    nx = (px - width / 2.0) / (width / 2.0)    # 右が正
    ny = (height / 2.0 - py) / (height / 2.0)   # 上が正

    # 2. FOVから焦点距離（正規化単位）を計算
    fx = 1.0 / math.tan(math.radians(calibration.fov_horizontal / 2.0))
    fy = 1.0 / math.tan(math.radians(calibration.fov_vertical / 2.0))

    # 3. カメラ座標系での方向ベクトル (X=右, Y=上, Z=前)
    cam_dir = np.array([nx, ny, fx])  # fxとfyは近似的に同じ想定、ここではfxを使用
    # アスペクト比が非正方ピクセルの場合の補正
    cam_dir = np.array([nx / fx, ny / fy, 1.0])
    cam_dir = cam_dir / np.linalg.norm(cam_dir)

    # 4. ロール回転（Z軸＝光軸周り）
    R_roll = _rotation_z(math.radians(calibration.roll))

    # 5. 仰角回転（X軸周り、カメラを上に向ける）
    R_elev = _rotation_x(math.radians(calibration.elevation))

    # 6. 方位角回転（Y軸周り、ENUのUp軸周り）
    #    方位角0=北(+N方向), 90=東(+E方向)
    #    カメラ初期方向をZ=北に設定し、方位角で回転
    R_az = _rotation_y(-math.radians(calibration.azimuth))
    # 注: Y軸=Upとして、方位角は北から東へ時計回り
    # enu座標系: X=East, Y=North, Z=Up
    # カメラ初期: X=右=East, Y=上=Up, Z=前=North
    # → カメラ座標からENU座標への変換が必要

    # カメラ座標系 → ENU座標系のマッピング:
    # カメラX(右) → 初期状態で東(E) → azimuthで回転
    # カメラY(上) → 初期状態で上(Up)  → elevationで回転
    # カメラZ(前) → 初期状態で北(N) → azimuth/elevationで回転

    # ステップ: cam → roll補正 → 仰角回転 → 方位回転 → ENU
    # まずカメラ座標(X=右,Y=上,Z=前)をENU初期(E,N,Up)にマッピング
    # cam(X,Y,Z) → enu初期(E,N,Up): X→E, Z→N, Y→Up
    cam_to_enu_init = np.array([
        [1, 0, 0],  # E = cam_X
        [0, 0, 1],  # N = cam_Z
        [0, 1, 0],  # Up = cam_Y
    ])

    # 合成変換: cam → roll → cam_to_enu → elev回転(East軸=X軸) → az回転(Up軸=Z軸)
    # 仰角: East軸(X)周りに回転（Nを上に傾ける）
    el_rad = math.radians(calibration.elevation)
    cos_el, sin_el = math.cos(el_rad), math.sin(el_rad)
    R_elev_enu = np.array([
        [1,      0,       0],
        [0,  cos_el, -sin_el],
        [0,  sin_el,  cos_el],
    ])

    # 方位角: Up軸(Z)周りに時計回り回転（北から東へ）
    # 標準の回転行列は反時計回りなので符号を反転
    az_rad = math.radians(calibration.azimuth)
    cos_az, sin_az = math.cos(az_rad), math.sin(az_rad)
    R_az_enu = np.array([
        [ cos_az, sin_az, 0],
        [-sin_az, cos_az, 0],
        [ 0,      0,      1],
    ])

    # 合成
    enu_dir = R_az_enu @ R_elev_enu @ cam_to_enu_init @ R_roll @ cam_dir

    # 7. ENU方向ベクトルから方位角・仰角を算出
    east, north, up = enu_dir[0], enu_dir[1], enu_dir[2]

    azimuth = math.degrees(math.atan2(east, north)) % 360.0
    elevation = math.degrees(
        math.asin(np.clip(up / np.linalg.norm(enu_dir), -1.0, 1.0))
    )

    return azimuth, elevation
