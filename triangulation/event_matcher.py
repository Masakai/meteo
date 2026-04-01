"""イベントマッチング: 異なる拠点からの同一流星検出を対応付け

時間窓ベースのスライディングウィンドウで検出を保持し、
異なる拠点からの検出を時刻の近さで対応付ける。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from triangulation.models import DetectionReport, StationConfig, TriangulatedMeteor
from triangulation.triangulator import triangulate_meteor

logger = logging.getLogger(__name__)


@dataclass
class MatchedEvent:
    """マッチングされたイベント（2拠点以上の検出の組）"""
    detections: List[DetectionReport]
    triangulated: Optional[TriangulatedMeteor] = None


class EventMatcher:
    """時間窓ベースのイベントマッチャー"""

    def __init__(
        self,
        stations: Dict[str, StationConfig],
        time_window: float = 5.0,
        buffer_duration: float = 30.0,
    ):
        """
        Args:
            stations: station_id → StationConfig のマッピング
            time_window: マッチング時間窓（秒）
            buffer_duration: バッファ保持時間（秒）
        """
        self.stations = stations
        self.time_window = time_window
        self.buffer_duration = buffer_duration
        self.buffer: List[DetectionReport] = []
        self.matched_ids: set = set()  # 既にマッチ済みの detection_id

    def _prune_old(self, now: datetime):
        """古いエントリをバッファから削除"""
        cutoff = now - timedelta(seconds=self.buffer_duration)
        self.buffer = [
            d for d in self.buffer
            if d.timestamp >= cutoff
        ]

    def add_detection(
        self, report: DetectionReport
    ) -> Optional[MatchedEvent]:
        """検出を追加し、マッチするイベントがあれば返す

        Returns:
            MatchedEvent（三角測量結果含む） or None
        """
        if report.detection_id in self.matched_ids:
            return None

        self.buffer.append(report)
        self._prune_old(report.timestamp)

        # 異なる拠点からの時間窓内の候補を検索
        candidates = []
        for d in self.buffer:
            if d.station_id == report.station_id:
                continue
            if d.detection_id in self.matched_ids:
                continue
            dt = abs((d.timestamp - report.timestamp).total_seconds())
            if dt <= self.time_window:
                candidates.append((dt, d))

        if not candidates:
            return None

        # 最も時間が近い候補を選択
        candidates.sort(key=lambda x: x[0])
        best_dt, best_match = candidates[0]

        # 三角測量を試行
        station_a = self.stations.get(report.station_id)
        station_b = self.stations.get(best_match.station_id)

        if station_a is None or station_b is None:
            logger.warning(
                "拠点設定が不足: %s or %s",
                report.station_id, best_match.station_id,
            )
            return None

        result = triangulate_meteor(report, best_match, station_a, station_b)

        if result is None:
            logger.info(
                "三角測量失敗（高度範囲外等）: %s ↔ %s (Δt=%.2fs)",
                report.detection_id, best_match.detection_id, best_dt,
            )
            return None

        # マッチ成功
        self.matched_ids.add(report.detection_id)
        self.matched_ids.add(best_match.detection_id)

        logger.info(
            "マッチ成功: %s ↔ %s (Δt=%.2fs, alt=%.1f-%.1f km, miss=%.2f km)",
            report.detection_id,
            best_match.detection_id,
            best_dt,
            result.start_alt,
            result.end_alt,
            result.miss_distance_start,
        )

        matched = MatchedEvent(
            detections=[report, best_match],
            triangulated=result,
        )
        return matched

    def add_detections(
        self, reports: List[DetectionReport]
    ) -> List[MatchedEvent]:
        """複数の検出を追加し、マッチしたイベントを返す"""
        results = []
        for report in reports:
            match = self.add_detection(report)
            if match is not None:
                results.append(match)
        return results
