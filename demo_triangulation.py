"""三角測量サーバのデモ用スクリプト

サンプルデータを投入してサーバを起動する。
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# デモ用の拠点設定を作成
stations_dir = Path("demo_stations")
stations_dir.mkdir(exist_ok=True)

JST = timezone(timedelta(hours=9))

station_a = {
    "station_id": "fuji-north",
    "station_name": "富士北麓観測所",
    "latitude": 35.4500,
    "longitude": 138.7600,
    "altitude": 1000.0,
    "triangulation_server_url": "http://localhost:8090",
    "api_key": "demo-key-a",
    "cameras": {
        "camera1_east": {
            "azimuth": 90.0,
            "elevation": 45.0,
            "roll": 0.0,
            "fov_horizontal": 90.0,
            "fov_vertical": 60.0,
            "resolution": [960, 540]
        },
        "camera2_south": {
            "azimuth": 180.0,
            "elevation": 45.0,
            "roll": 0.0,
            "fov_horizontal": 90.0,
            "fov_vertical": 60.0,
            "resolution": [960, 540]
        }
    }
}

station_b = {
    "station_id": "hakone",
    "station_name": "箱根観測所",
    "latitude": 35.2326,
    "longitude": 139.1070,
    "altitude": 800.0,
    "triangulation_server_url": "http://localhost:8090",
    "api_key": "demo-key-b",
    "cameras": {
        "camera1_north": {
            "azimuth": 350.0,
            "elevation": 50.0,
            "roll": 0.0,
            "fov_horizontal": 90.0,
            "fov_vertical": 60.0,
            "resolution": [960, 540]
        }
    }
}

station_c = {
    "station_id": "chichibu",
    "station_name": "秩父観測所",
    "latitude": 35.9917,
    "longitude": 139.0856,
    "altitude": 300.0,
    "triangulation_server_url": "http://localhost:8090",
    "api_key": "demo-key-c",
    "cameras": {
        "camera1_south": {
            "azimuth": 200.0,
            "elevation": 40.0,
            "roll": 0.0,
            "fov_horizontal": 90.0,
            "fov_vertical": 60.0,
            "resolution": [960, 540]
        }
    }
}

# 拠点設定ファイルを書き出し
for name, data in [("fuji-north.json", station_a), ("hakone.json", station_b), ("chichibu.json", station_c)]:
    with open(stations_dir / name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# サーバを初期化してデモデータを投入
os.environ["STATIONS_CONFIG"] = str(stations_dir)
os.environ["DB_PATH"] = "demo_triangulation.db"
os.environ["PORT"] = "8090"

# 既存DBを削除して新規作成
db_path = Path("demo_triangulation.db")
if db_path.exists():
    db_path.unlink()

from triangulation_server import create_app, init_db, save_triangulated, _db_path
from triangulation.models import DetectionReport, TriangulatedMeteor

app = create_app(str(stations_dir), str(db_path))

# デモ用の三角測量済み流星データを投入
demo_meteors = [
    TriangulatedMeteor(
        id="tri_demo_001",
        timestamp=datetime(2026, 3, 31, 22, 15, 30, tzinfo=JST),
        start_lat=35.45,
        start_lon=139.00,
        start_alt=105.3,
        end_lat=35.38,
        end_lon=139.08,
        end_alt=82.1,
        velocity=35.2,
        miss_distance_start=0.42,
        miss_distance_end=0.65,
        detections=[
            DetectionReport(
                station_id="fuji-north", camera_name="camera1_east",
                timestamp=datetime(2026, 3, 31, 22, 15, 30, tzinfo=JST),
                start_az=85.3, start_el=62.1, end_az=88.7, end_el=55.4,
                duration=0.48, confidence=0.85, peak_brightness=220.0,
                detection_id="det_fn_001",
            ),
            DetectionReport(
                station_id="hakone", camera_name="camera1_north",
                timestamp=datetime(2026, 3, 31, 22, 15, 30, 200000, tzinfo=JST),
                start_az=342.1, start_el=58.3, end_az=345.5, end_el=51.2,
                duration=0.45, confidence=0.78, peak_brightness=195.0,
                detection_id="det_hk_001",
            ),
        ],
        confidence=0.82,
    ),
    TriangulatedMeteor(
        id="tri_demo_002",
        timestamp=datetime(2026, 3, 31, 23, 42, 11, tzinfo=JST),
        start_lat=35.62,
        start_lon=138.85,
        start_alt=112.7,
        end_lat=35.50,
        end_lon=138.95,
        end_alt=75.3,
        velocity=52.8,
        miss_distance_start=1.21,
        miss_distance_end=1.85,
        detections=[
            DetectionReport(
                station_id="fuji-north", camera_name="camera1_east",
                timestamp=datetime(2026, 3, 31, 23, 42, 11, tzinfo=JST),
                start_az=45.2, start_el=70.5, end_az=52.1, end_el=58.3,
                duration=0.71, confidence=0.72, peak_brightness=180.0,
                detection_id="det_fn_002",
            ),
            DetectionReport(
                station_id="chichibu", camera_name="camera1_south",
                timestamp=datetime(2026, 3, 31, 23, 42, 11, 500000, tzinfo=JST),
                start_az=195.8, start_el=55.2, end_az=200.3, end_el=42.7,
                duration=0.68, confidence=0.65, peak_brightness=165.0,
                detection_id="det_cc_002",
            ),
        ],
        confidence=0.58,
    ),
    TriangulatedMeteor(
        id="tri_demo_003",
        timestamp=datetime(2026, 4, 1, 1, 8, 45, tzinfo=JST),
        start_lat=35.35,
        start_lon=139.20,
        start_alt=98.5,
        end_lat=35.30,
        end_lon=139.15,
        end_alt=88.2,
        velocity=22.1,
        miss_distance_start=0.18,
        miss_distance_end=0.25,
        detections=[
            DetectionReport(
                station_id="fuji-north", camera_name="camera2_south",
                timestamp=datetime(2026, 4, 1, 1, 8, 45, tzinfo=JST),
                start_az=135.5, start_el=48.2, end_az=138.1, end_el=45.8,
                duration=0.33, confidence=0.92, peak_brightness=245.0,
                detection_id="det_fn_003",
            ),
            DetectionReport(
                station_id="hakone", camera_name="camera1_north",
                timestamp=datetime(2026, 4, 1, 1, 8, 45, 100000, tzinfo=JST),
                start_az=15.3, start_el=52.7, end_az=12.8, end_el=50.1,
                duration=0.35, confidence=0.88, peak_brightness=238.0,
                detection_id="det_hk_003",
            ),
        ],
        confidence=0.91,
    ),
    TriangulatedMeteor(
        id="tri_demo_004",
        timestamp=datetime(2026, 4, 1, 2, 33, 18, tzinfo=JST),
        start_lat=35.55,
        start_lon=139.30,
        start_alt=115.0,
        end_lat=35.42,
        end_lon=139.22,
        end_alt=70.5,
        velocity=68.4,
        miss_distance_start=0.85,
        miss_distance_end=1.10,
        detections=[
            DetectionReport(
                station_id="hakone", camera_name="camera1_north",
                timestamp=datetime(2026, 4, 1, 2, 33, 18, tzinfo=JST),
                start_az=25.0, start_el=65.0, end_az=30.0, end_el=50.0,
                duration=0.65, confidence=0.80, peak_brightness=210.0,
                detection_id="det_hk_004",
            ),
            DetectionReport(
                station_id="chichibu", camera_name="camera1_south",
                timestamp=datetime(2026, 4, 1, 2, 33, 18, 300000, tzinfo=JST),
                start_az=175.0, start_el=60.0, end_az=180.0, end_el=45.0,
                duration=0.62, confidence=0.75, peak_brightness=200.0,
                detection_id="det_cc_004",
            ),
        ],
        confidence=0.72,
    ),
    TriangulatedMeteor(
        id="tri_demo_005",
        timestamp=datetime(2026, 4, 1, 3, 15, 55, tzinfo=JST),
        start_lat=35.28,
        start_lon=138.92,
        start_alt=108.0,
        end_lat=35.22,
        end_lon=138.88,
        end_alt=92.0,
        velocity=28.5,
        miss_distance_start=0.55,
        miss_distance_end=0.72,
        detections=[
            DetectionReport(
                station_id="fuji-north", camera_name="camera2_south",
                timestamp=datetime(2026, 4, 1, 3, 15, 55, tzinfo=JST),
                start_az=165.0, start_el=55.0, end_az=168.0, end_el=50.0,
                duration=0.55, confidence=0.70, peak_brightness=175.0,
                detection_id="det_fn_005",
            ),
            DetectionReport(
                station_id="hakone", camera_name="camera1_north",
                timestamp=datetime(2026, 4, 1, 3, 15, 55, 400000, tzinfo=JST),
                start_az=310.0, start_el=50.0, end_az=307.0, end_el=46.0,
                duration=0.52, confidence=0.68, peak_brightness=170.0,
                detection_id="det_hk_005",
            ),
        ],
        confidence=0.65,
    ),
]

for meteor in demo_meteors:
    save_triangulated(meteor)

print(f"デモデータ投入完了: {len(demo_meteors)}件の三角測量済み流星")
print(f"サーバ起動: http://localhost:8090/")

app.run(host="0.0.0.0", port=8090, debug=False)
