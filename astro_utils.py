#!/usr/bin/env python3
"""
天文計算ユーティリティ
検出時間帯（天文薄暮期間）の計算

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

from datetime import date, datetime, timedelta
from typing import Tuple
from astral import LocationInfo
from astral.sun import sun
from zoneinfo import ZoneInfo


def get_detection_window_for_date(
    target_date: date,
    latitude: float = 35.3606,
    longitude: float = 138.7274,
    timezone: str = "Asia/Tokyo",
) -> Tuple[datetime, datetime]:
    """
    指定日の夜間検出ウィンドウ（日没〜翌日の日出）を取得

    Args:
        target_date: 基準日
        latitude: 緯度
        longitude: 経度
        timezone: タイムゾーン

    Returns:
        (検出開始時刻, 検出終了時刻) のタプル
    """
    location = LocationInfo(
        name="Observer",
        region="",
        timezone=timezone,
        latitude=latitude,
        longitude=longitude
    )
    tz = ZoneInfo(timezone)
    sun_today = sun(location.observer, date=target_date, tzinfo=tz)
    sun_tomorrow = sun(location.observer, date=target_date + timedelta(days=1), tzinfo=tz)
    return sun_today["sunset"], sun_tomorrow["sunrise"]


def get_detection_window(latitude: float = 35.3606, longitude: float = 138.7274,
                         timezone: str = "Asia/Tokyo") -> Tuple[datetime, datetime]:
    """
    天文薄暮期間（前日の日の入りから翌日の日出まで）を取得

    Args:
        latitude: 緯度
        longitude: 経度
        timezone: タイムゾーン

    Returns:
        (検出開始時刻, 検出終了時刻) のタプル
    """
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    today = now.date()

    # 天文薄暮（astronomical twilight）の判定
    # 太陽の高度が-18度以下の時間帯 = 天文薄暮終了後の完全な夜
    # 検出期間は前日の日没（sunset）から翌日の日出（sunrise）まで

    # 今日の日出で終了（まだ過ぎていない場合）
    yesterday = today - timedelta(days=1)
    if now < get_detection_window_for_date(today, latitude, longitude, timezone)[1]:
        detection_start, detection_end = get_detection_window_for_date(
            yesterday, latitude, longitude, timezone
        )
    else:
        # 今日の日出が過ぎている場合は、今日の日没から明日の日出まで
        detection_start, detection_end = get_detection_window_for_date(
            today, latitude, longitude, timezone
        )

    return detection_start, detection_end


def is_detection_active(latitude: float = 35.3606, longitude: float = 138.7274,
                        timezone: str = "Asia/Tokyo") -> Tuple[bool, datetime, datetime]:
    """
    現在が検出期間内かどうかを判定

    Args:
        latitude: 緯度
        longitude: 経度
        timezone: タイムゾーン

    Returns:
        (検出期間内か, 検出開始時刻, 検出終了時刻) のタプル
    """
    start, end = get_detection_window(latitude, longitude, timezone)
    now = datetime.now(start.tzinfo)  # タイムゾーンを合わせる
    is_active = start <= now <= end
    return is_active, start, end
