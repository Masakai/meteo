import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import pytest

import meteor_detector_rtsp_web as web
from meteor_detector_realtime import DetectionParams, MeteorEvent, RingBuffer
from detection_filters import build_twilight_params


def test_storage_camera_name_is_safe_identifier():
    assert web._storage_camera_name("camera1_10.0.1.25") == "camera1_10_0_1_25"


def test_storage_camera_name_does_not_use_display_name(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMERA_NAME_DISPLAY", "東側カメラ")
    paths = web._runtime_override_paths(str(tmp_path / "camera1"), "camera1_10.0.1.25")
    assert paths[0].name == "camera1_10_0_1_25.json"
    assert "東側" not in paths[0].name


def test_faint_preset_uses_lighter_runtime_defaults(monkeypatch):
    monkeypatch.delenv("CAMERA_NAME_DISPLAY", raising=False)
    monkeypatch.setattr(web, "RTSPReader", lambda url: None)

    params = DetectionParams()

    def _stop_before_io(*args, **kwargs):
        raise RuntimeError("stop")

    monkeypatch.setattr(Path, "mkdir", _stop_before_io)

    try:
        web.process_rtsp_stream("rtsp://example", output_dir="out", params=params, sensitivity="faint", cam_name="cam1")
    except RuntimeError as e:
        assert str(e) == "stop"

    assert params.min_brightness == 150
    assert params.min_area == 5
    assert params.max_distance == 90


class TestBuildTwilightParams:
    def _base(self):
        return DetectionParams()

    def test_low_sensitivity(self):
        p = build_twilight_params("low", 200.0, self._base())
        assert p.diff_threshold == 40
        assert p.min_brightness == 220
        assert p.min_speed == 200.0

    def test_medium_sensitivity(self):
        p = build_twilight_params("medium", 150.0, self._base())
        assert p.diff_threshold == 30
        assert p.min_brightness == 210
        assert p.min_speed == 150.0

    def test_high_sensitivity(self):
        p = build_twilight_params("high", 100.0, self._base())
        assert p.diff_threshold == 20
        assert p.min_brightness == 180
        assert p.min_speed == 100.0

    def test_faint_sensitivity_uses_fixed_min_speed(self):
        p = build_twilight_params("faint", 999.0, self._base())
        assert p.diff_threshold == 16
        assert p.min_brightness == 150
        assert p.min_length == 10
        assert p.min_duration == 0.06
        assert p.min_speed == 10.0
        assert p.min_linearity == 0.55
        assert p.min_track_points == 3
        assert p.min_area == 5
        assert p.max_distance == 90

    def test_does_not_mutate_base_params(self):
        base = self._base()
        original_diff = base.diff_threshold
        build_twilight_params("low", 200.0, base)
        assert base.diff_threshold == original_diff


def _make_event(start_point=(10, 10), end_point=(50, 50), start_time=1.0, end_time=1.5):
    return MeteorEvent(
        timestamp=datetime(2026, 8, 17, 4, 0, 0),
        start_time=start_time,
        end_time=end_time,
        start_point=start_point,
        end_point=end_point,
        peak_brightness=220.0,
        confidence=0.8,
        frames=[],
    )


class TestCheckContrailAfterglow:
    """既定タイムライン: baseline=0.4, start_time=0.9, end_time=1.0, after=3.0
    (window=2.0)。tolerance=max(window*0.25, 0.05)=0.5のため、baseline=0.4は
    start_time=0.9から0.5秒差でギリギリ許容範囲に収まる。
    """

    def _ring_buffer_with_frames(self, frames):
        rb = RingBuffer(max_seconds=10.0, fps=20)
        for t, frame in frames:
            rb.add(t, frame)
        return rb

    # 既定sample_points=5、経路(10,10)-(90,90)におけるサンプル点そのもの。
    PATH_SAMPLE_POINTS = [(10, 10), (30, 30), (50, 50), (70, 70), (90, 90)]

    def _frame_with_trail(
        self, background, trail_value, shape=(100, 100), dtype=np.uint8,
        star_points=None, star_value=None,
    ):
        """背景を持つ非一様フレームを作る。経路(10,10)-(90,90)に沿って
        trail_valueの線分を描く。trail_value=Noneなら経路も背景と同じ値のまま
        （流星痕が完全に消滅した状態）にする。star_points/star_valueを指定すると
        恒星・ホットピクセルを模した固定の高輝度円（半径3px）を各点に追加する。
        星は流星痕より先に描画し、trail_value指定時は経路の線分で上書きする
        （実際の恒星は流星の発光より暗いことが多く、beforeフレームで恒星が
        流星痕に隠れる状態を再現するため。順序を逆にすると恒星が流星痕の上に
        乗ってしまい、before側の観測輝度が不当に高くなり検証にならない）。
        """
        frame = np.full(shape, background, dtype=dtype)
        if star_points is not None:
            star_color = (star_value,) * shape[2] if len(shape) == 3 else star_value
            for sp in star_points:
                cv2.circle(frame, sp, 3, star_color, -1)
        if trail_value is not None:
            color = (trail_value,) * shape[2] if len(shape) == 3 else trail_value
            cv2.line(frame, (10, 10), (90, 90), color, 3)
        return frame

    def _baseline_frame(self, background, shape=(100, 100), dtype=np.uint8, star_points=None, star_value=None):
        """イベント開始前のベースラインフレーム。流星は写っておらず、恒星等の
        静止高輝度がある場合のみstar_points/star_valueで指定する。
        """
        return self._frame_with_trail(
            background, trail_value=None, shape=shape, dtype=dtype,
            star_points=star_points, star_value=star_value,
        )

    @pytest.mark.parametrize("background", [5, 40, 80, 100, 120, 150])
    def test_vanished_trail_is_not_flagged_regardless_of_background(self, background):
        # 経路上に流星痕（輝度255）があるbeforeフレームに対し、afterフレームでは
        # 痕が完全に消滅し背景のみが残る（流星らしい一瞬の発光）。背景輝度が
        # 薄明期間相当（100〜150）まで明るくても、背景を差し引いた超過輝度が
        # ほぼ0になるため棄却されないことを確認する（指摘1の再発防止）。
        frame_base = self._baseline_frame(background)
        frame_before = self._frame_with_trail(background, trail_value=255)
        frame_after = self._frame_with_trail(background, trail_value=None)
        ring_buffer = self._ring_buffer_with_frames([
            (0.4, frame_base),
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False

    @pytest.mark.parametrize("background", [5, 80, 150])
    def test_identical_static_frames_are_not_flagged(self, background):
        # 前後フレームが完全に同一の静止シーン（何も起きていない）の場合、
        # 経路上に流星由来の輝度超過がそもそも存在しないため判定不能として
        # スキップされ、residual_hitsに一切加算されない（fail-openの根幹）。
        frame_base = self._baseline_frame(background)
        frame = np.full((100, 100), background, dtype=np.uint8)
        ring_buffer = self._ring_buffer_with_frames([
            (0.4, frame_base),
            (0.9, frame),
            (3.0, frame.copy()),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False

    @pytest.mark.parametrize("background", [5, 80, 150])
    def test_residual_brightness_independent_of_background_is_flagged_as_contrail(self, background):
        # 経路上に背景から独立した高輝度が終了直後もほぼ変わらず残っている
        # （飛行機雲らしい残光）場合は、背景輝度に関わらず真を返す。
        frame_base = self._baseline_frame(background)
        frame_before = self._frame_with_trail(background, trail_value=255)
        frame_after = self._frame_with_trail(background, trail_value=250)
        ring_buffer = self._ring_buffer_with_frames([
            (0.4, frame_base),
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is True

    @pytest.mark.parametrize(
        "background,star_value",
        [(5, 89), (5, 150), (80, 139), (80, 190), (150, 190), (150, 250)],
    )
    def test_static_star_in_patch_is_not_flagged_when_meteor_vanishes(self, background, star_value):
        # 新規指摘B（第2回レビュー）: 経路パッチ内部に恒星・ホットピクセルを
        # 模した静止した高輝度源がある場合でも、流星自体が完全に消滅していれば
        # 「残光あり」と誤判定してはならない。レビューの実測（経路上5サンプル点
        # すべてに静止輝点を置き、その上に流星痕を重畳）を再現する。パラメータは
        # レビューの実測値（背景5で絶対輝度89、背景80で139、r=0.3の推奨レンジ
        # 下限で誤棄却が始まる境界値）を含めてスイープする。
        star_points = self.PATH_SAMPLE_POINTS
        frame_base = self._baseline_frame(background, star_points=star_points, star_value=star_value)
        frame_before = self._frame_with_trail(
            background, trail_value=255, star_points=star_points, star_value=star_value,
        )
        frame_after = self._frame_with_trail(
            background, trail_value=None, star_points=star_points, star_value=star_value,
        )
        ring_buffer = self._ring_buffer_with_frames([
            (0.4, frame_base),
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        for ratio in (0.3, 0.5, 0.7):
            result = web.check_contrail_afterglow(
                ring_buffer, event, DetectionParams(), window=2.0, residual_brightness_ratio=ratio,
            )
            assert result is False, f"ratio={ratio}, background={background}, star_value={star_value}"

    def test_static_star_does_not_mask_real_afterglow(self):
        # 新規指摘Bの是正が過剰補正になっていないことの確認。経路上に静止した
        # 恒星（5サンプル点すべて）があっても、本物の残光（背景からも
        # ベースラインからも独立してafterに輝度が新たに残る）は引き続き
        # 「残光あり」と判定されなければならない。
        background = 80
        star_points = self.PATH_SAMPLE_POINTS
        star_value = 190
        frame_base = self._baseline_frame(background, star_points=star_points, star_value=star_value)
        frame_before = self._frame_with_trail(
            background, trail_value=255, star_points=star_points, star_value=star_value,
        )
        frame_after = self._frame_with_trail(
            background, trail_value=250, star_points=star_points, star_value=star_value,
        )
        ring_buffer = self._ring_buffer_with_frames([
            (0.4, frame_base),
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is True

    def test_single_informative_sample_fails_open(self):
        # 経路上5点(既定sample_points)のうち中央の1点のみ、単発ノイズで
        # min_excess_brightnessをクリアする残光っぽい値を持ち、他の4点は
        # 判定不能（超過輝度が閾値未満）とする。判定可能なサンプル点数
        # （valid_samples）が過半数(3点)に満たない場合、1点のノイズだけで
        # 比が跳ね上がり誤棄却しないよう、判定不能としてfail-openで通すことを
        # 確認する。
        background = 80
        frame_base = self._baseline_frame(background)
        frame_before = np.full((100, 100), background, dtype=np.uint8)
        frame_after = np.full((100, 100), background, dtype=np.uint8)
        cv2.circle(frame_before, (50, 50), 2, 255, -1)
        cv2.circle(frame_after, (50, 50), 2, 250, -1)
        ring_buffer = self._ring_buffer_with_frames([
            (0.4, frame_base),
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False

    def test_missing_frames_fail_open(self):
        # RingBufferにフレームが無い（評価不能）場合はフィルタを適用せず通す。
        ring_buffer = RingBuffer(max_seconds=10.0, fps=20)
        event = _make_event(start_time=100.0, end_time=100.5)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False

    def test_missing_baseline_frame_fails_open(self):
        # イベント開始前のベースラインフレームがRingBufferに残っていない
        # （ストリーム開始直後、または実効バッファ長が足りない等）場合、
        # 静止成分の除去ができないため評価不能としてfail-openで通す。
        # ここではbefore/afterのみ用意し、start_time(0.9)より前のフレームは
        # 一切RingBufferに存在しない。
        frame_before = np.full((100, 100), 200, dtype=np.uint8)
        frame_after = np.full((100, 100), 190, dtype=np.uint8)  # 残光ありに見える値
        ring_buffer = self._ring_buffer_with_frames([
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False

    def test_out_of_frame_path_fail_open(self):
        # start_point/end_pointがフレーム範囲外（評価不能）の場合はフィルタを
        # 適用せず通す。
        frame_base = np.full((50, 50), 200, dtype=np.uint8)
        frame_before = np.full((50, 50), 200, dtype=np.uint8)
        frame_after = np.full((50, 50), 190, dtype=np.uint8)
        ring_buffer = self._ring_buffer_with_frames([
            (0.4, frame_base),
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(-100, -100), end_point=(-50, -50), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False

    def test_after_frame_too_far_from_window_target_fails_open(self):
        # RingBufferがwindow秒後まで到達していない（ストリーム終端付近等）
        # 場合、直後のフレームをwindow秒後の輝度と誤って比較しないよう、
        # 許容誤差を超えるずれは評価不能としてfail-openで通す。
        # ここではafter側の実フレームがend_time直後(1.1)にしかなく、
        # 要求時刻(end_time+window=3.0)から1.9秒ずれている。ベースライン
        # フレームは意図的に用意せず、after側の許容誤差ガードが
        # baseline_entryのNoneガードより先に効くことを確認する
        # （両ガードとも同じFalseを返すため、after側の許容誤差ガードを
        # 単独で踏むケースとして意味を持たせている）。
        frame_before = np.full((100, 100), 200, dtype=np.uint8)
        frame_after = np.full((100, 100), 190, dtype=np.uint8)  # 残光ありに見える値
        ring_buffer = self._ring_buffer_with_frames([
            (0.9, frame_before),
            (1.1, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False

    def test_bgr_frame_shape_is_supported(self):
        # 本番のRingBufferは(H, W, 3)のBGRフレームを保持する。チャンネル次元が
        # あっても背景差し引きの輝度比較が壊れないことを、背景を持つ非一様
        # フレーム（経路上に背景から独立した残光がある）で確認する。
        frame_base = self._baseline_frame(80, shape=(100, 100, 3))
        frame_before = self._frame_with_trail(80, trail_value=255, shape=(100, 100, 3))
        frame_after = self._frame_with_trail(80, trail_value=250, shape=(100, 100, 3))
        ring_buffer = self._ring_buffer_with_frames([
            (0.4, frame_base),
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is True

    def test_nearest_baseline_before_start_time_is_selected_over_older_candidate(self):
        # 第3回レビュー指摘E-1（変異M2対策）。ベースライン候補が複数ある場合、
        # event.start_time直前の候補が選ばれなければならない。より古い候補
        # （0.2秒、星なし＝背景のみ）と、start_time直前の候補（0.88秒、静止した
        # 恒星あり）で内容を変え、正しい候補（0.88秒）が選ばれれば静止成分が
        # 相殺されて棄却されない（False）ことを確認する。もし誤って古い候補
        # （星なし）を選ぶと、恒星の輝度が相殺されず指摘B相当の誤棄却（True）が
        # 再現する。
        #
        # なお「target_timeをevent.end_timeに差し替える」変異は、baseline候補が
        # すべてt < event.start_time < event.end_timeを満たす場合、
        # |t-start_time|と|t-end_time|がともにtについて単調減少なためargminが
        # 常に同一フレームになる等価変異であり、いかなるフィクスチャでも
        # kill不能である。本テストは代替として「start_time直前の候補が正しく
        # 選ばれる」という性質を固定する。
        background = 80
        star_points = self.PATH_SAMPLE_POINTS
        star_value = 190
        frame_base_old_no_star = self._baseline_frame(background)
        frame_base_near_with_star = self._baseline_frame(background, star_points=star_points, star_value=star_value)
        frame_before = self._frame_with_trail(
            background, trail_value=255, star_points=star_points, star_value=star_value,
        )
        frame_after = self._frame_with_trail(
            background, trail_value=None, star_points=star_points, star_value=star_value,
        )
        ring_buffer = self._ring_buffer_with_frames([
            (0.2, frame_base_old_no_star),
            (0.88, frame_base_near_with_star),
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False

    def test_baseline_older_than_tolerance_fails_open(self):
        # 第3回レビュー指摘E-2（変異M5対策）。ベースラインフレームが許容誤差
        # （tolerance=max(window*frame_time_tolerance_ratio, 0.05)、既定値では
        # window=2.0・frame_time_tolerance_ratio=0.25で0.5）を超えて古い場合、
        # 静止成分の除去ができないため評価不能としてfail-openで通ることを
        # 確認する。before/afterは本物の残光（背景から独立した高輝度がafterも
        # ほぼ変わらず残る）にしておき、ベースライン差し引きが機能していれば
        # 本来はTrue（棄却）になるはずのケースで、tolerance超過ガードにより
        # Falseになることを確認する。
        background = 80
        frame_base_too_old = self._baseline_frame(background)
        frame_before = self._frame_with_trail(background, trail_value=255)
        frame_after = self._frame_with_trail(background, trail_value=250)
        ring_buffer = self._ring_buffer_with_frames([
            (0.2, frame_base_too_old),  # start_time(0.9)との差0.7 > tolerance(0.5)
            (0.9, frame_before),
            (3.0, frame_after),
        ])
        event = _make_event(start_point=(10, 10), end_point=(90, 90), start_time=0.9, end_time=1.0)
        result = web.check_contrail_afterglow(ring_buffer, event, DetectionParams(), window=2.0)
        assert result is False


class TestClampEnvValueAndWarn:
    def test_twilight_rate_window_sec_zero_is_clamped_to_lower_bound(self, capsys):
        # twilight_rate_window_sec=0はTwilightRateLimiter._prune()のcutoff計算
        # (now - window_sec)を破壊し記録を即座に全消去するため、下限1.0への
        # クランプが確実に効くことを確認する（第1回レビュー指摘3で名指しされた
        # ケース）。
        result = web._clamp_env_value_and_warn("twilight_rate_window_sec", 0.0, 1.0, 3600.0)
        assert result == 1.0
        assert "twilight_rate_window_sec" in capsys.readouterr().out

    def test_negative_window_sec_is_clamped_to_lower_bound(self, capsys):
        result = web._clamp_env_value_and_warn("twilight_rate_window_sec", -5.0, 1.0, 3600.0)
        assert result == 1.0
        assert "[WARN]" in capsys.readouterr().out

    def test_residual_brightness_ratio_above_range_is_clamped(self, capsys):
        result = web._clamp_env_value_and_warn("contrail_residual_brightness_ratio", 5.0, 0.0, 1.0)
        assert result == 1.0
        assert "contrail_residual_brightness_ratio" in capsys.readouterr().out

    def test_negative_max_events_is_clamped_to_zero(self, capsys):
        result = web._clamp_env_value_and_warn("twilight_rate_max_events", -3, 0, None)
        assert result == 0
        assert "[WARN]" in capsys.readouterr().out

    def test_in_range_value_is_not_clamped_and_no_warning(self, capsys):
        result = web._clamp_env_value_and_warn("contrail_afterglow_window", 2.0, 0.0, 10.0)
        assert result == 2.0
        assert capsys.readouterr().out == ""
