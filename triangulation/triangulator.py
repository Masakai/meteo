"""三角測量: 2つの観測線から流星の3D位置を算出

2つの拠点からの観測線（方位角・仰角で定義）の
最近接点（closest point of approach）を求め、
その中点を流星の推定位置とする。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

from triangulation.geo_utils import (
    ecef_to_lla,
    observation_line_ecef,
)
from triangulation.models import DetectionReport, StationConfig, TriangulatedMeteor


# 妥当な流星高度の範囲 (km)
MIN_ALTITUDE_KM = 40.0
MAX_ALTITUDE_KM = 200.0


def closest_approach(
    p1: np.ndarray, d1: np.ndarray,
    p2: np.ndarray, d2: np.ndarray,
) -> Optional[Tuple[np.ndarray, float]]:
    """2本のスキューラインの最近接点を求める

    Line 1: p1 + t * d1
    Line 2: p2 + s * d2

    Returns:
        (midpoint, miss_distance) or None if lines are parallel
        midpoint: 最近接2点の中点 (ECEF, m)
        miss_distance: 最近接距離 (m)
    """
    w0 = p1 - p2
    a = np.dot(d1, d1)
    b = np.dot(d1, d2)
    c = np.dot(d2, d2)
    d = np.dot(d1, w0)
    e = np.dot(d2, w0)

    denom = a * c - b * b
    if abs(denom) < 1e-10:
        return None  # ほぼ平行

    t = (b * e - c * d) / denom
    s = (a * e - b * d) / denom

    # 観測方向は前方のみ有効
    if t < 0 or s < 0:
        return None

    point1 = p1 + t * d1
    point2 = p2 + s * d2
    midpoint = (point1 + point2) / 2.0
    miss_distance = np.linalg.norm(point1 - point2)

    return midpoint, miss_distance


def triangulate_point(
    station_a: StationConfig,
    az_a: float, el_a: float,
    station_b: StationConfig,
    az_b: float, el_b: float,
) -> Optional[Tuple[float, float, float, float]]:
    """2拠点の観測方向から1点の3D位置を三角測量

    Returns:
        (lat, lon, alt_km, miss_km) or None
    """
    p1, d1 = observation_line_ecef(
        station_a.latitude, station_a.longitude, station_a.altitude,
        az_a, el_a,
    )
    p2, d2 = observation_line_ecef(
        station_b.latitude, station_b.longitude, station_b.altitude,
        az_b, el_b,
    )

    result = closest_approach(p1, d1, p2, d2)
    if result is None:
        return None

    midpoint, miss_distance = result
    lat, lon, alt_m = ecef_to_lla(midpoint[0], midpoint[1], midpoint[2])
    alt_km = alt_m / 1000.0
    miss_km = miss_distance / 1000.0

    return lat, lon, alt_km, miss_km


def triangulate_meteor(
    det_a: DetectionReport,
    det_b: DetectionReport,
    station_a: StationConfig,
    station_b: StationConfig,
) -> Optional[TriangulatedMeteor]:
    """2拠点の検出レポートから流星の3D軌道を三角測量

    始点と終点それぞれについて三角測量を行い、
    高度が妥当な範囲内であれば TriangulatedMeteor を返す。
    """
    # 始点の三角測量
    start_result = triangulate_point(
        station_a, det_a.start_az, det_a.start_el,
        station_b, det_b.start_az, det_b.start_el,
    )
    if start_result is None:
        return None

    start_lat, start_lon, start_alt, miss_start = start_result

    # 終点の三角測量
    end_result = triangulate_point(
        station_a, det_a.end_az, det_a.end_el,
        station_b, det_b.end_az, det_b.end_el,
    )
    if end_result is None:
        return None

    end_lat, end_lon, end_alt, miss_end = end_result

    # 高度の妥当性チェック
    if not (MIN_ALTITUDE_KM <= start_alt <= MAX_ALTITUDE_KM):
        return None
    if not (MIN_ALTITUDE_KM <= end_alt <= MAX_ALTITUDE_KM):
        return None

    # 速度計算 (km/s)
    velocity = None
    avg_duration = (det_a.duration + det_b.duration) / 2.0
    if avg_duration > 0:
        # 始点と終点のECEF距離
        from triangulation.geo_utils import lla_to_ecef
        start_ecef = lla_to_ecef(start_lat, start_lon, start_alt * 1000)
        end_ecef = lla_to_ecef(end_lat, end_lon, end_alt * 1000)
        distance_km = np.linalg.norm(end_ecef - start_ecef) / 1000.0
        velocity = distance_km / avg_duration

    # 信頼度: miss_distance と元の検出信頼度から算出
    avg_confidence = (det_a.confidence + det_b.confidence) / 2.0
    # miss_distanceが小さいほど高信頼度（5km以下で最大ボーナス）
    miss_factor = max(0, 1.0 - (miss_start + miss_end) / 10.0)
    confidence = avg_confidence * 0.6 + miss_factor * 0.4

    # 一意なID生成
    id_source = f"{det_a.detection_id}_{det_b.detection_id}"
    meteor_id = "tri_" + hashlib.sha1(id_source.encode(), usedforsecurity=False).hexdigest()[:16]

    # タイムスタンプは2つの検出の平均
    avg_ts = det_a.timestamp.timestamp() + (
        det_b.timestamp.timestamp() - det_a.timestamp.timestamp()
    ) / 2.0

    return TriangulatedMeteor(
        id=meteor_id,
        timestamp=datetime.fromtimestamp(avg_ts, tz=det_a.timestamp.tzinfo),
        start_lat=start_lat,
        start_lon=start_lon,
        start_alt=start_alt,
        end_lat=end_lat,
        end_lon=end_lon,
        end_alt=end_alt,
        velocity=velocity,
        miss_distance_start=miss_start,
        miss_distance_end=miss_end,
        detections=[det_a, det_b],
        confidence=confidence,
    )
