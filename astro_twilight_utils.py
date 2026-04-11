#!/usr/bin/env python3
"""
薄明期間判定ユーティリティ

astral ライブラリを使って civil / nautical / astronomical 薄明期間を計算する。

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

import datetime
from typing import Tuple
from astral import LocationInfo
from astral.sun import sun, dawn, dusk
from zoneinfo import ZoneInfo

# twilight_type → depression (degree)
_DEPRESSION = {
    "civil": 6,
    "nautical": 12,
    "astronomical": 18,
}


def get_twilight_window(
    target_date: datetime.date,
    latitude: float,
    longitude: float,
    timezone: str,
    twilight_type: str = "nautical",
) -> Tuple[Tuple[datetime.datetime, datetime.datetime], Tuple[datetime.datetime, datetime.datetime]]:
    """
    指定日の薄明期間を返す。

    戻り値: ((evening_start, evening_end), (morning_start, morning_end))
      夕方薄明: sunset → dusk
      朝方薄明: dawn → sunrise

    Args:
        target_date: 対象日
        latitude: 緯度
        longitude: 経度
        timezone: タイムゾーン文字列
        twilight_type: "civil"(6°) / "nautical"(12°) / "astronomical"(18°)

    Raises:
        ValueError: twilight_type が不正な値の場合
    """
    if twilight_type not in _DEPRESSION:
        raise ValueError(
            f"無効な twilight_type: {twilight_type!r}。"
            f"'civil', 'nautical', 'astronomical' のいずれかを指定してください。"
        )

    depression = _DEPRESSION[twilight_type]
    location = LocationInfo(
        name="Observer",
        region="",
        timezone=timezone,
        latitude=latitude,
        longitude=longitude,
    )
    tz = ZoneInfo(timezone)
    observer = location.observer

    sun_today = sun(observer, date=target_date, tzinfo=tz)
    evening_start = sun_today["sunset"]
    evening_end = dusk(observer, date=target_date, depression=depression, tzinfo=tz)

    next_date = target_date + datetime.timedelta(days=1)
    sun_next = sun(observer, date=next_date, tzinfo=tz)
    morning_start = dawn(observer, date=next_date, depression=depression, tzinfo=tz)
    morning_end = sun_next["sunrise"]

    return (evening_start, evening_end), (morning_start, morning_end)


def is_twilight_active(
    latitude: float,
    longitude: float,
    timezone: str,
    twilight_type: str = "nautical",
) -> bool:
    """
    現在時刻（UTC基準）が薄明期間内かどうかを返す。

    薄明期間は夕方（sunset→dusk）と朝方（dawn→sunrise）の2区間。

    Args:
        latitude: 緯度
        longitude: 経度
        timezone: タイムゾーン文字列
        twilight_type: "civil"(6°) / "nautical"(12°) / "astronomical"(18°)

    Returns:
        現在が薄明期間内であれば True
    """
    tz = ZoneInfo(timezone)
    now = datetime.datetime.now(tz)
    today = now.date()

    (eve_start, eve_end), (morn_start, morn_end) = get_twilight_window(
        today, latitude, longitude, timezone, twilight_type
    )

    if eve_start <= now <= eve_end:
        return True

    # 朝方薄明は翌日データとして計算済みだが、深夜〜翌朝のケースも考慮し
    # 前日のウィンドウも確認する
    if morn_start <= now <= morn_end:
        return True

    yesterday = today - datetime.timedelta(days=1)
    _, (prev_morn_start, prev_morn_end) = get_twilight_window(
        yesterday, latitude, longitude, timezone, twilight_type
    )
    if prev_morn_start <= now <= prev_morn_end:
        return True

    return False
