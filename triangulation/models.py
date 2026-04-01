"""三角測量システムのデータモデル"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class CameraCalibration:
    """カメラの方位・仰角・FOV設定"""
    camera_name: str
    azimuth: float          # 度, 0=北, 90=東, 180=南, 270=西
    elevation: float        # 度, 水平線からの角度 (0=水平, 90=天頂)
    roll: float             # 度, 光軸周りの回転 (通常0)
    fov_horizontal: float   # 度, 水平方向の視野角
    fov_vertical: float     # 度, 垂直方向の視野角
    resolution: Tuple[int, int]  # (幅, 高さ), 検出処理時の解像度


@dataclass
class StationConfig:
    """観測拠点の設定"""
    station_id: str
    station_name: str
    latitude: float         # 度
    longitude: float        # 度
    altitude: float         # メートル (WGS84楕円体高)
    triangulation_server_url: str
    api_key: str
    cameras: Dict[str, CameraCalibration] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> StationConfig:
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cameras = {}
        for cam_name, cam_data in data.get("cameras", {}).items():
            cameras[cam_name] = CameraCalibration(
                camera_name=cam_name,
                azimuth=cam_data["azimuth"],
                elevation=cam_data["elevation"],
                roll=cam_data.get("roll", 0.0),
                fov_horizontal=cam_data["fov_horizontal"],
                fov_vertical=cam_data["fov_vertical"],
                resolution=tuple(cam_data["resolution"]),
            )

        return cls(
            station_id=data["station_id"],
            station_name=data["station_name"],
            latitude=data["latitude"],
            longitude=data["longitude"],
            altitude=data["altitude"],
            triangulation_server_url=data.get("triangulation_server_url", ""),
            api_key=data.get("api_key", ""),
            cameras=cameras,
        )


@dataclass
class DetectionReport:
    """拠点からの検出レポート（天球座標変換済み）"""
    station_id: str
    camera_name: str
    timestamp: datetime
    start_az: float         # 度, 始点の方位角
    start_el: float         # 度, 始点の仰角
    end_az: float           # 度, 終点の方位角
    end_el: float           # 度, 終点の仰角
    duration: float         # 秒
    confidence: float
    peak_brightness: float
    detection_id: str
    start_pixel: Tuple[int, int] = (0, 0)
    end_pixel: Tuple[int, int] = (0, 0)

    def to_dict(self) -> dict:
        return {
            "station_id": self.station_id,
            "camera_name": self.camera_name,
            "timestamp": self.timestamp.isoformat(),
            "start_az": round(self.start_az, 4),
            "start_el": round(self.start_el, 4),
            "end_az": round(self.end_az, 4),
            "end_el": round(self.end_el, 4),
            "duration": round(self.duration, 3),
            "confidence": round(self.confidence, 2),
            "peak_brightness": round(self.peak_brightness, 1),
            "detection_id": self.detection_id,
            "start_pixel": list(self.start_pixel),
            "end_pixel": list(self.end_pixel),
        }

    @classmethod
    def from_dict(cls, data: dict) -> DetectionReport:
        return cls(
            station_id=data["station_id"],
            camera_name=data["camera_name"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            start_az=data["start_az"],
            start_el=data["start_el"],
            end_az=data["end_az"],
            end_el=data["end_el"],
            duration=data["duration"],
            confidence=data["confidence"],
            peak_brightness=data["peak_brightness"],
            detection_id=data["detection_id"],
            start_pixel=tuple(data.get("start_pixel", (0, 0))),
            end_pixel=tuple(data.get("end_pixel", (0, 0))),
        )


@dataclass
class TriangulatedMeteor:
    """三角測量で求めた流星の3D軌道"""
    id: str
    timestamp: datetime
    start_lat: float        # 度
    start_lon: float        # 度
    start_alt: float        # km
    end_lat: float          # 度
    end_lon: float          # 度
    end_alt: float          # km
    velocity: Optional[float] = None  # km/s
    miss_distance_start: float = 0.0  # km, 三角測量精度指標
    miss_distance_end: float = 0.0    # km
    detections: List[DetectionReport] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "start_lat": round(self.start_lat, 6),
            "start_lon": round(self.start_lon, 6),
            "start_alt": round(self.start_alt, 2),
            "end_lat": round(self.end_lat, 6),
            "end_lon": round(self.end_lon, 6),
            "end_alt": round(self.end_alt, 2),
            "velocity": round(self.velocity, 1) if self.velocity else None,
            "miss_distance_start": round(self.miss_distance_start, 3),
            "miss_distance_end": round(self.miss_distance_end, 3),
            "detections": [d.to_dict() for d in self.detections],
            "confidence": round(self.confidence, 2),
        }
