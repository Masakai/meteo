"""
astro_twilight_utils のユニットテスト
"""

import datetime
import pytest

from astro_twilight_utils import get_twilight_window, is_twilight_active

LATITUDE = 35.3606
LONGITUDE = 138.7274
TIMEZONE = "Asia/Tokyo"
TARGET_DATE = datetime.date(2026, 4, 11)


class TestGetTwilightWindow:
    def test_civil_order(self):
        (eve_start, eve_end), (morn_start, morn_end) = get_twilight_window(
            TARGET_DATE, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="civil"
        )
        assert eve_start < eve_end, "夕方薄明: sunset < dusk であること"
        assert morn_start < morn_end, "朝方薄明: dawn < sunrise であること"

    def test_nautical_order(self):
        (eve_start, eve_end), (morn_start, morn_end) = get_twilight_window(
            TARGET_DATE, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="nautical"
        )
        assert eve_start < eve_end, "夕方薄明: sunset < dusk であること"
        assert morn_start < morn_end, "朝方薄明: dawn < sunrise であること"

    def test_astronomical_order(self):
        (eve_start, eve_end), (morn_start, morn_end) = get_twilight_window(
            TARGET_DATE, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="astronomical"
        )
        assert eve_start < eve_end, "夕方薄明: sunset < dusk であること"
        assert morn_start < morn_end, "朝方薄明: dawn < sunrise であること"

    def test_nautical_wider_than_civil(self):
        """nautical 薄明期間は civil より広い"""
        (civil_eve_s, civil_eve_e), (civil_morn_s, civil_morn_e) = get_twilight_window(
            TARGET_DATE, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="civil"
        )
        (naut_eve_s, naut_eve_e), (naut_morn_s, naut_morn_e) = get_twilight_window(
            TARGET_DATE, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="nautical"
        )
        # dusk: nautical の dusk は civil の dusk より遅い（暗くなる）
        assert naut_eve_e > civil_eve_e, "nautical dusk は civil dusk より遅い"
        # dawn: nautical の dawn は civil の dawn より早い（まだ暗い）
        assert naut_morn_s < civil_morn_s, "nautical dawn は civil dawn より早い"

    def test_invalid_twilight_type_raises(self):
        with pytest.raises(ValueError):
            get_twilight_window(
                TARGET_DATE, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="invalid"
            )


class TestIsTwilightActive:
    def test_midday_is_not_twilight(self):
        """正午UTC（日本時間 21:00）は薄明期間外"""
        import unittest.mock as mock
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(TIMEZONE)
        # 日本時間の昼12時（UTC 03:00）は薄明期間外
        midday_jst = datetime.datetime(2026, 4, 11, 12, 0, 0, tzinfo=tz)

        with mock.patch("astro_twilight_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = midday_jst
            mock_dt.date = datetime.date
            mock_dt.timedelta = datetime.timedelta
            result = is_twilight_active(LATITUDE, LONGITUDE, TIMEZONE, "nautical")

        assert result is False, "日本時間の昼12時は薄明期間外であること"

    def test_evening_twilight_midpoint_is_active(self):
        """夕方薄明期間の中間時刻は True を返す"""
        import unittest.mock as mock

        (eve_start, eve_end), _ = get_twilight_window(
            TARGET_DATE, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="nautical"
        )
        midpoint = eve_start + (eve_end - eve_start) / 2

        with mock.patch("astro_twilight_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = midpoint
            mock_dt.date = datetime.date
            mock_dt.timedelta = datetime.timedelta
            result = is_twilight_active(LATITUDE, LONGITUDE, TIMEZONE, "nautical")

        assert result is True, "夕方薄明期間の中間時刻は薄明アクティブであること"

    def test_morning_twilight_midpoint_is_active(self):
        """朝方薄明期間の中間時刻は True を返す"""
        import unittest.mock as mock

        _, (morn_start, morn_end) = get_twilight_window(
            TARGET_DATE, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="nautical"
        )
        midpoint = morn_start + (morn_end - morn_start) / 2

        with mock.patch("astro_twilight_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = midpoint
            mock_dt.date = datetime.date
            mock_dt.timedelta = datetime.timedelta
            result = is_twilight_active(LATITUDE, LONGITUDE, TIMEZONE, "nautical")

        assert result is True, "朝方薄明期間の中間時刻は薄明アクティブであること"

    def test_previous_day_morning_window_is_active(self):
        """前日の朝方薄明ウィンドウ（日またぎ）でも True を返す"""
        import unittest.mock as mock

        # 前日のウィンドウを取得し、その朝方薄明中間時刻を使う
        prev_date = TARGET_DATE - datetime.timedelta(days=1)
        _, (prev_morn_start, prev_morn_end) = get_twilight_window(
            prev_date, LATITUDE, LONGITUDE, TIMEZONE, twilight_type="nautical"
        )
        midpoint = prev_morn_start + (prev_morn_end - prev_morn_start) / 2

        # is_twilight_active 内では today = now.date() を使うため、
        # now の date() が midpoint の日付を返すよう mock する
        with mock.patch("astro_twilight_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = midpoint
            mock_dt.date = datetime.date
            mock_dt.timedelta = datetime.timedelta
            result = is_twilight_active(LATITUDE, LONGITUDE, TIMEZONE, "nautical")

        assert result is True, "前日の朝方薄明ウィンドウ（日またぎ）でも薄明アクティブであること"

    def test_morning_twilight_line112_is_active(self):
        """is_twilight_active の朝方薄明 True 分岐（line 112）を直接カバーする。

        get_twilight_window をモックして、today のウィンドウの morning 区間が
        now と同日に収まるよう設定することで line 112 に到達させる。
        """
        import unittest.mock as mock
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(TIMEZONE)
        # now を 2026-04-12 04:30:00 JST（TARGET_DATE + 1日の早朝）に固定
        # now.date() = 2026-04-12 = "today" として is_twilight_active が使う
        now = datetime.datetime(2026, 4, 12, 4, 30, 0, tzinfo=tz)

        # get_twilight_window(today=2026-04-12) が返す morning window が
        # now を含むようにモックする（今日付で早朝の時刻帯）
        morn_start = datetime.datetime(2026, 4, 12, 4, 0, 0, tzinfo=tz)
        morn_end = datetime.datetime(2026, 4, 12, 5, 0, 0, tzinfo=tz)
        eve_start = datetime.datetime(2026, 4, 12, 18, 0, 0, tzinfo=tz)
        eve_end = datetime.datetime(2026, 4, 12, 19, 0, 0, tzinfo=tz)

        with mock.patch("astro_twilight_utils.datetime") as mock_dt, \
             mock.patch("astro_twilight_utils.get_twilight_window") as mock_gtw:
            mock_dt.datetime.now.return_value = now
            mock_dt.date = datetime.date
            mock_dt.timedelta = datetime.timedelta
            mock_gtw.return_value = ((eve_start, eve_end), (morn_start, morn_end))

            result = is_twilight_active(LATITUDE, LONGITUDE, TIMEZONE, "nautical")

        assert result is True, "朝方薄明ウィンドウ内（line 112）で True を返すこと"

    def test_invalid_twilight_type_raises(self):
        """不正な twilight_type は ValueError を発生させる"""
        with pytest.raises(ValueError):
            is_twilight_active(LATITUDE, LONGITUDE, TIMEZONE, "invalid")
