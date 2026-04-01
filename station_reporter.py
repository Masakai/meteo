"""拠点レポーター: 検出結果を天球座標に変換し三角測量サーバへ送信

各拠点でサイドカーとして動作し、detections/ ディレクトリの
JSONL ファイルを監視して新規検出を三角測量サーバに POST する。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

from triangulation.models import DetectionReport, StationConfig
from triangulation.pixel_to_sky import pixel_to_sky

logger = logging.getLogger(__name__)


class JsonlTailer:
    """JSONL ファイルの末尾を監視し、新規行を返す"""

    def __init__(self, path: Path):
        self.path = path
        self._offset = 0
        if path.exists():
            self._offset = path.stat().st_size

    def read_new_lines(self) -> List[dict]:
        if not self.path.exists():
            return []

        lines = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                f.seek(self._offset)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            lines.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning("不正なJSONL行をスキップ: %s", line[:100])
                self._offset = f.tell()
        except OSError as e:
            logger.error("JSONL読み取りエラー: %s", e)

        return lines


class StationReporter:
    """拠点からの検出レポートを三角測量サーバに送信"""

    def __init__(
        self,
        station_config: StationConfig,
        detections_dir: str = "/output",
        poll_interval: float = 5.0,
        max_retry: int = 3,
    ):
        self.config = station_config
        self.detections_dir = Path(detections_dir)
        self.poll_interval = poll_interval
        self.max_retry = max_retry
        self.tailers: Dict[str, JsonlTailer] = {}
        self._sent_ids: set = set()  # 重複送信防止

    def _discover_jsonl_files(self) -> Dict[str, Path]:
        """detections/ 配下のJSONLファイルを発見"""
        result = {}
        if not self.detections_dir.exists():
            return result

        for camera_dir in self.detections_dir.iterdir():
            if not camera_dir.is_dir():
                continue
            jsonl = camera_dir / "detections.jsonl"
            if jsonl.exists():
                result[camera_dir.name] = jsonl

        return result

    def _convert_detection(
        self, camera_name: str, raw: dict
    ) -> Optional[DetectionReport]:
        """生の検出データを天球座標付きレポートに変換"""
        cal = self.config.cameras.get(camera_name)
        if cal is None:
            logger.debug("カメラ %s のキャリブレーション未設定、スキップ", camera_name)
            return None

        start_px = raw.get("start_point")
        end_px = raw.get("end_point")
        if not start_px or not end_px:
            return None

        try:
            start_az, start_el = pixel_to_sky(start_px[0], start_px[1], cal)
            end_az, end_el = pixel_to_sky(end_px[0], end_px[1], cal)
        except Exception as e:
            logger.error("天球座標変換エラー: %s", e)
            return None

        timestamp_str = raw.get("timestamp", "")
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            logger.warning("無効なタイムスタンプ: %s", timestamp_str)
            return None

        detection_id = raw.get("id", "")
        if not detection_id:
            # IDが無い場合はタイムスタンプとカメラ名から生成
            detection_id = f"{camera_name}_{timestamp_str}"

        return DetectionReport(
            station_id=self.config.station_id,
            camera_name=camera_name,
            timestamp=timestamp,
            start_az=start_az,
            start_el=start_el,
            end_az=end_az,
            end_el=end_el,
            duration=raw.get("duration", 0.0),
            confidence=raw.get("confidence", 0.0),
            peak_brightness=raw.get("peak_brightness", 0.0),
            detection_id=detection_id,
            start_pixel=tuple(start_px),
            end_pixel=tuple(end_px),
        )

    def _send_reports(self, reports: List[DetectionReport]) -> bool:
        """三角測量サーバにレポートを送信"""
        if not reports:
            return True

        url = self.config.triangulation_server_url.rstrip("/") + "/api/detections"
        payload = {
            "station_id": self.config.station_id,
            "api_key": self.config.api_key,
            "detections": [r.to_dict() for r in reports],
        }

        for attempt in range(self.max_retry):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    logger.info(
                        "%d件のレポートを送信完了", len(reports)
                    )
                    return True
                logger.warning(
                    "サーバ応答エラー (HTTP %d): %s",
                    resp.status_code, resp.text[:200],
                )
            except requests.RequestException as e:
                logger.warning(
                    "送信エラー (試行 %d/%d): %s",
                    attempt + 1, self.max_retry, e,
                )
            if attempt < self.max_retry - 1:
                time.sleep(2 ** attempt)

        logger.error("レポート送信失敗（全リトライ消費）")
        return False

    def poll_once(self) -> int:
        """1回のポーリング: 新規検出を読み取り、変換して送信"""
        jsonl_files = self._discover_jsonl_files()

        # 新規ファイルのtailer作成
        for camera_name, path in jsonl_files.items():
            if camera_name not in self.tailers:
                self.tailers[camera_name] = JsonlTailer(path)

        reports = []
        for camera_name, tailer in self.tailers.items():
            new_lines = tailer.read_new_lines()
            for raw in new_lines:
                det_id = raw.get("id", "")
                if det_id in self._sent_ids:
                    continue

                report = self._convert_detection(camera_name, raw)
                if report:
                    reports.append(report)
                    if det_id:
                        self._sent_ids.add(det_id)

        if reports:
            self._send_reports(reports)

        # 古いIDをクリーンアップ（メモリ節約）
        if len(self._sent_ids) > 10000:
            self._sent_ids = set(list(self._sent_ids)[-5000:])

        return len(reports)

    def run(self):
        """メインループ"""
        logger.info(
            "拠点レポーター起動: station=%s, server=%s",
            self.config.station_id,
            self.config.triangulation_server_url,
        )

        while True:
            try:
                self.poll_once()
            except Exception as e:
                logger.error("ポーリングエラー: %s", e, exc_info=True)

            time.sleep(self.poll_interval)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = os.environ.get("STATION_CONFIG", "/app/station.json")
    detections_dir = os.environ.get("DETECTIONS_DIR", "/output")
    poll_interval = float(os.environ.get("POLL_INTERVAL", "5"))

    if not Path(config_path).exists():
        logger.error("拠点設定ファイルが見つかりません: %s", config_path)
        sys.exit(1)

    config = StationConfig.from_file(config_path)
    reporter = StationReporter(
        station_config=config,
        detections_dir=detections_dir,
        poll_interval=poll_interval,
    )
    reporter.run()


if __name__ == "__main__":
    main()
