"""三角測量サーバ: 複数拠点からの検出を受け取り三角測量を実行

Flask アプリケーション。各拠点の station_reporter から
検出レポートを受信し、イベントマッチング + 三角測量を行い、
結果を地図上に表示する。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, jsonify, request

from triangulation.event_matcher import EventMatcher
from triangulation.models import (
    DetectionReport,
    StationConfig,
    TriangulatedMeteor,
)
from triangulation_templates import render_map_page

logger = logging.getLogger(__name__)

app = Flask(__name__)

# グローバル状態
_matcher: Optional[EventMatcher] = None
_stations: Dict[str, StationConfig] = {}
_api_keys: Dict[str, str] = {}  # station_id → api_key
_db_path: str = "triangulation.db"


def init_db(db_path: str):
    """SQLiteデータベースを初期化"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triangulated_meteors (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            start_lat REAL NOT NULL,
            start_lon REAL NOT NULL,
            start_alt REAL NOT NULL,
            end_lat REAL NOT NULL,
            end_lon REAL NOT NULL,
            end_alt REAL NOT NULL,
            velocity REAL,
            miss_distance_start REAL,
            miss_distance_end REAL,
            confidence REAL,
            detections_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detection_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            camera_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            start_az REAL,
            start_el REAL,
            end_az REAL,
            end_el REAL,
            duration REAL,
            confidence REAL,
            peak_brightness REAL,
            detection_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_timestamp
        ON detection_reports(timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_meteors_timestamp
        ON triangulated_meteors(timestamp)
    """)
    conn.commit()
    conn.close()


def save_triangulated(meteor: TriangulatedMeteor):
    """三角測量結果をDBに保存"""
    conn = sqlite3.connect(_db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO triangulated_meteors
            (id, timestamp, start_lat, start_lon, start_alt,
             end_lat, end_lon, end_alt, velocity,
             miss_distance_start, miss_distance_end, confidence,
             detections_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                meteor.id,
                meteor.timestamp.isoformat(),
                meteor.start_lat,
                meteor.start_lon,
                meteor.start_alt,
                meteor.end_lat,
                meteor.end_lon,
                meteor.end_alt,
                meteor.velocity,
                meteor.miss_distance_start,
                meteor.miss_distance_end,
                meteor.confidence,
                json.dumps([d.to_dict() for d in meteor.detections]),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def save_detection_report(report: DetectionReport):
    """検出レポートをDBに保存"""
    conn = sqlite3.connect(_db_path)
    try:
        conn.execute(
            """INSERT INTO detection_reports
            (station_id, camera_name, timestamp,
             start_az, start_el, end_az, end_el,
             duration, confidence, peak_brightness, detection_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.station_id,
                report.camera_name,
                report.timestamp.isoformat(),
                report.start_az,
                report.start_el,
                report.end_az,
                report.end_el,
                report.duration,
                report.confidence,
                report.peak_brightness,
                report.detection_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_triangulated(
    since: Optional[str] = None, limit: int = 100
) -> List[dict]:
    """三角測量結果をDBから読み込み"""
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    try:
        if since:
            rows = conn.execute(
                """SELECT * FROM triangulated_meteors
                WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?""",
                (since, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM triangulated_meteors
                ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()

        results = []
        for row in rows:
            result = dict(row)
            if result.get("detections_json"):
                result["detections"] = json.loads(result["detections_json"])
            del result["detections_json"]
            results.append(result)
        return results
    finally:
        conn.close()


# --- Flask ルート ---


@app.route("/")
def index():
    """地図UIページ"""
    stations_data = []
    for sid, sc in _stations.items():
        stations_data.append({
            "station_id": sc.station_id,
            "station_name": sc.station_name,
            "latitude": sc.latitude,
            "longitude": sc.longitude,
            "cameras": [
                {
                    "camera_name": cam.camera_name,
                    "azimuth": cam.azimuth,
                    "elevation": cam.elevation,
                    "fov_horizontal": cam.fov_horizontal,
                }
                for cam in sc.cameras.values()
            ],
        })
    return render_map_page(stations_data)


@app.route("/api/detections", methods=["POST"])
def receive_detections():
    """拠点からの検出レポートを受信"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    station_id = data.get("station_id", "")
    api_key = data.get("api_key", "")

    # API キー認証
    expected_key = _api_keys.get(station_id)
    if expected_key and api_key != expected_key:
        return jsonify({"error": "Invalid API key"}), 403

    detections_raw = data.get("detections", [])
    reports = []
    for d in detections_raw:
        try:
            d["station_id"] = station_id
            report = DetectionReport.from_dict(d)
            reports.append(report)
            save_detection_report(report)
        except (KeyError, ValueError) as e:
            logger.warning("不正なレポートデータ: %s", e)

    # イベントマッチング
    matched = _matcher.add_detections(reports)
    triangulated_count = 0
    for match in matched:
        if match.triangulated:
            save_triangulated(match.triangulated)
            triangulated_count += 1

    return jsonify({
        "status": "ok",
        "received": len(reports),
        "triangulated": triangulated_count,
    })


@app.route("/api/triangulated")
def get_triangulated():
    """三角測量結果を取得"""
    since = request.args.get("since")
    limit = min(int(request.args.get("limit", 100)), 500)
    results = load_triangulated(since=since, limit=limit)
    return jsonify(results)


@app.route("/api/stations")
def get_stations():
    """登録済み拠点の一覧"""
    result = []
    for sid, sc in _stations.items():
        result.append({
            "station_id": sc.station_id,
            "station_name": sc.station_name,
            "camera_count": len(sc.cameras),
        })
    return jsonify(result)


@app.route("/api/stats")
def get_stats():
    """統計情報"""
    conn = sqlite3.connect(_db_path)
    try:
        total_reports = conn.execute(
            "SELECT COUNT(*) FROM detection_reports"
        ).fetchone()[0]
        total_triangulated = conn.execute(
            "SELECT COUNT(*) FROM triangulated_meteors"
        ).fetchone()[0]
        return jsonify({
            "total_reports": total_reports,
            "total_triangulated": total_triangulated,
            "stations": len(_stations),
        })
    finally:
        conn.close()


def load_stations_config(config_dir: str) -> Dict[str, StationConfig]:
    """拠点設定ファイルを読み込み"""
    stations = {}
    config_path = Path(config_dir)

    if config_path.is_file():
        # 単一ファイルの場合
        sc = StationConfig.from_file(config_path)
        stations[sc.station_id] = sc
    elif config_path.is_dir():
        # ディレクトリ内の全JSONを読み込み
        for f in config_path.glob("*.json"):
            try:
                sc = StationConfig.from_file(f)
                stations[sc.station_id] = sc
            except Exception as e:
                logger.error("拠点設定読み込みエラー (%s): %s", f, e)
    return stations


def create_app(stations_config: str = "stations/", db_path: str = "triangulation.db"):
    """アプリケーション初期化"""
    global _matcher, _stations, _api_keys, _db_path

    _db_path = db_path
    init_db(_db_path)

    _stations = load_stations_config(stations_config)
    _api_keys = {sid: sc.api_key for sid, sc in _stations.items() if sc.api_key}
    _matcher = EventMatcher(stations=_stations)

    logger.info(
        "三角測量サーバ初期化完了: %d拠点登録", len(_stations)
    )
    return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    stations_config = os.environ.get("STATIONS_CONFIG", "stations/")
    db_path = os.environ.get("DB_PATH", "triangulation.db")
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8090"))

    application = create_app(stations_config, db_path)
    application.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
