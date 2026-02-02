#!/usr/bin/env python3
"""
天文計算ユーティリティ
検出時間帯（天文薄暮期間）の計算

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

from datetime import datetime, timedelta
from typing import Tuple
from astral import LocationInfo
from astral.sun import sun
from zoneinfo import ZoneInfo


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
    location = LocationInfo(
        name="Observer",
        region="",
        timezone=timezone,
        latitude=latitude,
        longitude=longitude
    )

    # 指定されたタイムゾーンで現在時刻を取得
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    today = now.date()

    # 今日の太陽情報を取得（UTC）
    sun_today = sun(location.observer, date=today, tzinfo=tz)
    sun_yesterday = sun(location.observer, date=today - timedelta(days=1), tzinfo=tz)
    sun_tomorrow = sun(location.observer, date=today + timedelta(days=1), tzinfo=tz)

    # 天文薄暮（astronomical twilight）の判定
    # 太陽の高度が-18度以下の時間帯 = 天文薄暮終了後の完全な夜
    # 検出期間は前日の日没（sunset）から翌日の日出（sunrise）まで

    # 前日の日没から開始
    detection_start = sun_yesterday["sunset"]
    # 今日の日出で終了（まだ過ぎていない場合）
    if now < sun_today["sunrise"]:
        detection_end = sun_today["sunrise"]
    else:
        # 今日の日出が過ぎている場合は、今日の日没から明日の日出まで
        detection_start = sun_today["sunset"]
        detection_end = sun_tomorrow["sunrise"]

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
