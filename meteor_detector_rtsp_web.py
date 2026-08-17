#!/usr/bin/env python3
"""
RTSPストリームからリアルタイム流星検出（Webプレビュー付き）

Webブラウザでプレビューを確認できます。
http://localhost:8080/ でアクセス

使い方:
    python meteor_detector_rtsp_web.py rtsp://192.168.1.100:554/stream --web-port 8080

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

import argparse
import cv2
import numpy as np
from typing import List, Optional, Dict
from threading import Thread, Event
import time
import signal
import sys
import os
import copy
from pathlib import Path
from datetime import datetime

from meteor_detector_realtime import (
    DetectionParams,
    EventMerger,
    RTSPReader,
    RealtimeMeteorDetector,
    RingBuffer,
    probe_rtsp_endpoint,
    probe_rtsp_with_ffprobe,
    save_meteor_event,
    sanitize_fps,
)
from meteor_mask_utils import (
    build_exclusion_mask,
    build_exclusion_mask_from_frame,
    build_nuisance_mask_from_night,
)
from detection_state import (
    state,
    _storage_camera_name,
    _runtime_override_paths,
    _load_runtime_overrides,
    _save_runtime_overrides,
)
from detection_filters import (
    _to_bool,
    build_twilight_params,
    filter_dark_objects,
    apply_sensitivity_preset,
    TwilightRateLimiter,
)
from recording_manager import (
    _stop_recording_process,
)
from http_handlers import MJPEGHandler, ThreadedHTTPServer, STREAM_JPEG_QUALITY

VERSION = "3.6.1"

# 終了処理で残イベントの保存にかけてよい時間の上限（秒）。
# メインスレッドは detection_thread.join(timeout=5.0) で待つため、これを大きく
# 超えると検出スレッドが孤児化して「終了」ログの後も保存を続けることになる。
SHUTDOWN_SAVE_BUDGET_SEC = 4.0

# 方式4（薄明期間バーストレート抑制）: レート超過時に感度プリセットを一段階
# 下げる（誤検出を減らす方向＝lowに近づける）ためのステップマッピング。
# faint は薄明reduceモードのプリセットとしては通常使わないが念のため定義する。
_TWILIGHT_SENSITIVITY_STEP_DOWN = {
    "faint": "high",
    "high": "medium",
    "medium": "low",
    "low": "low",
}

# 天文薄暮期間の判定用
try:
    from astro_utils import is_detection_active
except ImportError:
    is_detection_active = None

try:
    from astro_twilight_utils import is_twilight_active
except ImportError:
    is_twilight_active = None


def _clamp_env_value_and_warn(name, value, min_v, max_v):
    """環境変数またはconfig.json(runtime_overrides)由来の値をレンジ外ならクランプし
    [WARN]ログを出す。

    contrail_afterglow_window / contrail_residual_brightness_ratio /
    twilight_rate_window_sec / twilight_rate_max_events はDetectionParamsの
    フィールドではないため、DetectionParams._clamp_and_warn()は使わずここに
    ローカル実装する（メッセージにDetectionParamsではなく実際のパラメータ名を
    正しく出すため）。process_rtsp_stream()内、runtime_overrides適用直後の
    一箇所で呼び出すことで、main()のenv読み取り経路とconfig.json
    (runtime_overrides)経由の上書き経路の両方をカバーする。レンジは
    /apply_settingsの検証テーブル（http_handlers.pyのstartup_float_fields/
    startup_int_fields）と一致させる。特にtwilight_rate_window_secの下限1.0は、
    0や負値がTwilightRateLimiter._prune()のcutoff計算を破壊し記録を即座に
    全消去する問題を防ぐために必須。
    """
    clamped = value
    if min_v is not None and clamped < min_v:
        clamped = min_v
    if max_v is not None and clamped > max_v:
        clamped = max_v
    if clamped != value:
        print(
            f"[WARN] {name}={value} は許容範囲外のためクランプ: {clamped}",
            flush=True,
        )
    return clamped


def check_contrail_afterglow(
    ring_buffer,
    event,
    params,
    *,
    window: float = 2.0,
    residual_brightness_ratio: float = 0.5,
    sample_points: int = 5,
    frame_time_tolerance_ratio: float = 0.25,
    min_excess_brightness: float = 8.0,
) -> bool:
    """飛行機雲の残光チェック（方式2）。真=飛行機雲疑いで棄却。

    event.start_point〜end_pointを結ぶ経路上の数点について、イベント終了直後
    のフレームでの「背景を差し引いた経路の輝度超過分」が終了直前フレームと
    比べて有意に残存しているかを見る。飛行機雲は太陽光を反射し続けるため
    軌跡経路に沿って輝度が残りやすく、流星は一瞬の発光のため直後には残らない
    性質を利用する。

    背景の推定には各サンプル点を中心としたリング状領域（経路パッチの外側、
    中心からinner_radius〜outer_radius）の中央値を用いる。パッチ平均から
    この背景推定値を差し引いた「超過輝度」をbefore/afterそれぞれで求める。
    単純な絶対輝度比較では、背景そのものが明るい場合（薄明期間・月明かり等）
    に流星が完全に消滅していてもafterのパッチ輝度がbeforeの一定割合を
    超えてしまい、確定流星を誤棄却する（fail-open原則違反）。背景を
    差し引くことでこの誤判定を避ける（リング差し引き、指摘1是正）。

    ただしリング差し引きはパッチの周囲の輝度しか除去できない。パッチ内部に
    恒常的に存在する高輝度源（恒星・ホットピクセル・固定光源）があると、
    その輝度はbefore/after双方の超過輝度に等しく残ってしまい、静止成分が
    十分明るいと消滅した流星でも「残光あり」と誤判定する（指摘1と同クラスの
    fail-open違反、第2回レビュー新規指摘B）。これを避けるため、イベント
    開始前（流星が写り込む前）のベースラインフレームでも同じ超過輝度
    excess_baseを求め、before/afterそれぞれからexcess_baseを差し引いた
    m_before（流星による輝度上昇分のみ）・m_afterで比を取る。before/after/
    baseの3フレームすべてに等しく存在する静止成分（恒星等）はこの差し引きで
    相殺されるため、residual_brightness_ratioの意味（「流星自身の寄与のうち
    どれだけが残ったか」の比）は変わらない。

    beforeの超過輝度（m_before、ベースライン差し引き後）がmin_excess_brightness
    未満（流星由来の輝度上昇がパッチに観測できない）のサンプル点は判定不能
    としてスキップする。これは前後フレームが完全に同一の静止シーンであっても
    residual_hitsに数えられないことを保証する（fail-openの根幹）。さらに、
    判定可能なサンプル点数（valid_samples）がsample_pointsの過半数に満たない
    場合も評価不能として通す。単発ノイズによる残光っぽい値が1点だけ観測
    できたケースで、その1点だけでresidual_hits/valid_samples比が跳ね上がり
    誤棄却することを防ぐため。

    params引数は現時点では未使用（判定に必要な閾値はすべてキーワード引数
    window/residual_brightness_ratioで渡している）。呼び出し元のDetectionParams
    を将来的な拡張のために受け取れるようシグネチャに残している。

    座標系: event.start_point/end_pointはフル解像度座標（meteor_detector_rtsp_web.py
    の scale_factor 変換後）であり、本関数はフル解像度フレームに対してそのまま
    処理する（既存の_calculate_line_overlap_ratioのスケール不整合を新規コードに
    持ち込まない設計方針）。

    評価不能（フレーム不足、ストリーム終端付近でRingBufferがwindow秒後まで
    到達していない、イベント開始前のベースラインフレームがRingBufferに
    残っていない等）の場合はフィルタを適用せず通す（fail-open）。特に
    frame_afterが要求時刻(event.end_time + window)から大きくずれている場合、
    観測窓が実質的に縮小され残光判定の意味が変わってしまう
    （終了直後の輝度をwindow秒後の輝度と誤って比較し、残光が実際は消えている
    のに「残っている」と誤判定して確定流星を棄却するリスクがある）ため、
    許容誤差を超えるずれは評価不能として扱う。ベースラインフレームについても
    同じ許容誤差でevent.start_timeとの近さを要求する。

    既知の限界:
    - 飛行機雲がwindow秒以内に周囲へ拡散した場合、背景推定用のリング領域も
      明るくなり超過輝度が過小評価されうる（見逃し方向でありfail-open原則
      には反しない、感度上の制約）。痕の幅が概ね9px以上になるとリング
      （半径6〜10px）が痕自身で汚染され、同様に見逃し方向へ働く。
    - ベースラインフレームはevent.start_timeより前かつRingBuffer内に必要。
      RingBufferの実効長は`min(buffer_seconds, max_duration + 2.0)`（既定値では
      約12秒）に制限されるため、イベント継続時間がmax_durationに近づくほど
      ベースライン取得の余裕が減る（見逃し方向でありfail-open原則には反しない）。

    フレーム取得: baseline/before/afterの3フレームは、いずれもRingBuffer.
    get_nearest_in_range()で目標時刻に最も近い1フレームのみを複製して取得する
    （第3回レビュー指摘C是正）。従来はRingBuffer.get_range()で範囲内の全フレーム
    を複製したリストを作ってから最も近い1件を選んでおり、1920x1080想定で
    イベントごとに約946MBの不要な複製と約149msの検出スレッド停止が発生して
    いた。get_nearest_in_range()はタイムスタンプの比較のみで走査し、選ばれた
    1フレームだけを複製するため、同条件で約18MB・数msに削減される。
    """
    # get_nearest_in_rangeは範囲外を単に無視する実装のため、下限クランプ
    # （旧: max(0.0, ...)）は不要（第3回レビュー指摘D）。event.start_time==0.0の
    # ストリーム開始直後のイベントでも[start_time-window, start_time)がそのまま
    # 渡り、ベースライン取得が不当に無効化されない。end_exclusive=Trueで
    # t==event.start_timeのフレーム（流星が写り込んだ最初の追跡フレーム、
    # start_time=min(times)）を誤ってベースラインに選ばないようにする。
    baseline_entry = ring_buffer.get_nearest_in_range(
        event.start_time, event.start_time - window, event.start_time, end_exclusive=True,
    )

    before_entry = ring_buffer.get_nearest_in_range(
        event.end_time, event.end_time - window, event.end_time,
    )
    target_after_time = event.end_time + window
    after_entry = ring_buffer.get_nearest_in_range(
        target_after_time, event.end_time, target_after_time,
    )

    if before_entry is None or after_entry is None or baseline_entry is None:
        return False

    # RingBufferがwindow秒後まで到達していない（ストリーム終端付近、
    # finalize_all()/flush_all()のシャットダウン経路等）場合、直後のフレームを
    # window秒後の輝度と誤って比較すると観測窓が縮小し、実際にはまだ消えて
    # いない一瞬の残光を「window秒後も残っている」と誤判定しうる。
    # 許容誤差を超えるずれは評価不能としてfail-openで通す。
    tolerance = max(window * frame_time_tolerance_ratio, 0.05)
    if abs(after_entry[0] - target_after_time) > tolerance:
        return False

    # ベースラインフレームがevent.start_timeから大きく離れている場合
    # （RingBufferの保持範囲が足りない等）も同様に評価不能としてfail-openで
    # 通す。
    if abs(baseline_entry[0] - event.start_time) > tolerance:
        return False

    frame_before, frame_after, frame_base = before_entry[1], after_entry[1], baseline_entry[1]

    if frame_before.shape != frame_after.shape or frame_before.shape != frame_base.shape:
        return False

    height, width = frame_before.shape[:2]
    sx, sy = event.start_point
    ex, ey = event.end_point

    # 背景推定用リング領域の半径。経路パッチ（半径patch_radius）の外側に
    # 隙間（inner_radius）を空けてから外周（outer_radius）までを背景推定に
    # 使う。パッチにすぐ隣接させると経路自体の輝度がリングに混入し背景推定が
    # 汚染されるため、隙間を空けて分離する。
    patch_radius = 3
    ring_inner_radius = 6
    ring_outer_radius = 10

    residual_hits = 0
    valid_samples = 0
    for i in range(sample_points):
        t = i / max(1, sample_points - 1)
        x = int(round(sx + (ex - sx) * t))
        y = int(round(sy + (ey - sy) * t))
        if not (0 <= x < width and 0 <= y < height):
            continue

        px0, px1 = max(0, x - patch_radius), min(width, x + patch_radius + 1)
        py0, py1 = max(0, y - patch_radius), min(height, y + patch_radius + 1)

        rx0, rx1 = max(0, x - ring_outer_radius), min(width, x + ring_outer_radius + 1)
        ry0, ry1 = max(0, y - ring_outer_radius), min(height, y + ring_outer_radius + 1)

        yy, xx = np.mgrid[ry0:ry1, rx0:rx1]
        dist = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
        ring_mask = (dist >= ring_inner_radius) & (dist <= ring_outer_radius)
        if not np.any(ring_mask):
            continue

        patch_before = frame_before[py0:py1, px0:px1]
        patch_after = frame_after[py0:py1, px0:px1]
        patch_base = frame_base[py0:py1, px0:px1]
        ring_region_before = frame_before[ry0:ry1, rx0:rx1]
        ring_region_after = frame_after[ry0:ry1, rx0:rx1]
        ring_region_base = frame_base[ry0:ry1, rx0:rx1]

        background_before = float(np.median(ring_region_before[ring_mask]))
        background_after = float(np.median(ring_region_after[ring_mask]))
        background_base = float(np.median(ring_region_base[ring_mask]))

        excess_before = float(np.mean(patch_before)) - background_before
        excess_after = float(np.mean(patch_after)) - background_after
        excess_base = float(np.mean(patch_base)) - background_base

        # excess_baseは恒星・ホットピクセル等、イベント開始前から恒常的に
        # パッチ内に存在する静止輝度（リング差し引きでは除去できない成分）の
        # 推定値。before/afterそれぞれから差し引くことで、静止成分をキャンセル
        # し「流星自身の輝度寄与」だけを残す（新規指摘Bの是正）。
        m_before = excess_before - excess_base
        m_after = excess_after - excess_base

        if m_before < min_excess_brightness:
            # 流星由来の輝度超過がこのサンプル点に観測できない（判定不能）。
            # 前後フレームが同一の静止シーンの場合や、ベースラインと変わらない
            # 静止輝点しかない場合、常にこの分岐に入りresidual_hitsに
            # 加算されない（fail-openの根幹）。
            continue
        valid_samples += 1
        # m_afterが負（静止輝点未満まで暗くなった等）の場合もそのまま比較する。
        # residual_brightness_ratioは0以上のためm_after<0なら残光ヒットには
        # ならず、fail-open方向は維持される。
        if m_after >= m_before * residual_brightness_ratio:
            residual_hits += 1

    # 判定可能なサンプル点（min_excess_brightnessをクリアした点）が少数の場合、
    # 1点のノイズだけで比が跳ね上がり誤棄却しうる。sample_pointsの過半数
    # （最低2点）に満たない場合は判定不能としてfail-openで通す。
    min_required_samples = max(2, (sample_points + 1) // 2)
    if valid_samples < min_required_samples:
        return False

    return residual_hits / valid_samples >= 0.5


def detection_thread_worker(  # pragma: no cover
    reader,
    params,
    process_scale,
    buffer_seconds,
    fps,
    output_path,
    extract_clips,
    stop_flag,
    mask_image=None,
    mask_from_day=None,
    mask_dilate=5,
    mask_save=None,
    nuisance_mask_image=None,
    nuisance_from_night=None,
    nuisance_dilate=3,
    clip_margin_before=1.0,
    clip_margin_after=1.0,
    enable_time_window=False,
    latitude=35.3606,
    longitude=138.7274,
    timezone="Asia/Tokyo",
    twilight_detection_mode="reduce",
    twilight_type="nautical",
    twilight_sensitivity="low",
    twilight_min_speed=200.0,
    twilight_max_speed=0.0,
    bird_filter_enabled=False,
    bird_min_brightness=80.0,
    twilight_bird_filter_enabled=True,
    twilight_bird_min_brightness=80.0,
    contrail_check_enabled=False,
    contrail_afterglow_window=2.0,
    contrail_residual_brightness_ratio=0.5,
    twilight_rate_window_sec=300.0,
    twilight_rate_max_events=0,
    twilight_rate_suppress_enabled=False,
):
    """検出処理を行うワーカースレッド"""

    width, height = reader.frame_size
    proc_width = int(width * process_scale)
    proc_height = int(height * process_scale)
    scale_factor = 1.0 / process_scale

    ring_buffer = RingBuffer(buffer_seconds, fps)
    exclusion_mask = None
    nuisance_mask = None
    persistent_mask_path = None
    if output_path:
        persistent_mask_path = Path(output_path) / "masks" / f"{_storage_camera_name(state.camera_name)}_mask.png"
        if persistent_mask_path.exists():
            mask_image = str(persistent_mask_path)
    if mask_image:
        mask_img = cv2.imread(mask_image, cv2.IMREAD_GRAYSCALE)
        if mask_img is None:
            print(f"[WARN] マスク画像を読み込めません: {mask_image}")
        else:
            if (mask_img.shape[1], mask_img.shape[0]) != (proc_width, proc_height):
                mask_img = cv2.resize(mask_img, (proc_width, proc_height), interpolation=cv2.INTER_NEAREST)
            _, exclusion_mask = cv2.threshold(mask_img, 1, 255, cv2.THRESH_BINARY)
            print(f"マスク適用: {mask_image}")
    elif mask_from_day:
        exclusion_mask = build_exclusion_mask(
            mask_from_day,
            (proc_width, proc_height),
            dilate_px=mask_dilate,
            save_path=mask_save,
        )
        if exclusion_mask is not None:
            print(f"マスク適用: {mask_from_day}")

    if nuisance_mask_image:
        nuisance_img = cv2.imread(nuisance_mask_image, cv2.IMREAD_GRAYSCALE)
        if nuisance_img is None:
            print(f"[WARN] ノイズ帯マスク画像を読み込めません: {nuisance_mask_image}")
        else:
            if (nuisance_img.shape[1], nuisance_img.shape[0]) != (proc_width, proc_height):
                nuisance_img = cv2.resize(nuisance_img, (proc_width, proc_height), interpolation=cv2.INTER_NEAREST)
            _, nuisance_mask = cv2.threshold(nuisance_img, 1, 255, cv2.THRESH_BINARY)
            print(f"ノイズ帯マスク適用: {nuisance_mask_image}")

    if nuisance_from_night:
        auto_nuisance = build_nuisance_mask_from_night(
            nuisance_from_night,
            (proc_width, proc_height),
            dilate_px=nuisance_dilate,
        )
        if auto_nuisance is not None:
            nuisance_mask = auto_nuisance if nuisance_mask is None else cv2.bitwise_or(nuisance_mask, auto_nuisance)
            print(f"ノイズ帯マスク自動生成: {nuisance_from_night}")

    detector = RealtimeMeteorDetector(
        params,
        fps,
        exclusion_mask=exclusion_mask,
        nuisance_mask=nuisance_mask,
    )
    merger = EventMerger(params)
    state.current_detector = detector
    state.current_proc_size = (proc_width, proc_height)
    state.current_mask_dilate = mask_dilate
    state.current_nuisance_dilate = nuisance_dilate
    state.current_clip_margin_before = clip_margin_before
    state.current_clip_margin_after = clip_margin_after
    state.current_mask_save = mask_save
    state.current_output_dir = Path(output_path)
    state.current_camera_name = state.camera_name
    with state.current_pending_mask_lock:
        state.current_pending_exclusion_mask = None
        state.current_pending_mask_save_path = None

    prev_gray = None
    frame_count = 0
    recent_frame_times: List[float] = []

    # 天文薄暮期間のチェック（ウィンドウ終了後に再計算）
    is_detection_time = True  # デフォルトは有効
    detection_start = None
    detection_end = None
    state.current_detection_window_enabled = bool(enable_time_window and is_detection_active)
    if enable_time_window and is_detection_active:
        is_detection_time, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
        state.current_detection_window_active = is_detection_time
        state.current_detection_window_start = detection_start.strftime("%Y-%m-%d %H:%M:%S")
        state.current_detection_window_end = detection_end.strftime("%Y-%m-%d %H:%M:%S")
    else:
        state.current_detection_window_active = True
        state.current_detection_window_start = ""
        state.current_detection_window_end = ""
    state.current_detection_status = "WAITING_FRAME"

    # 薄明判定キャッシュ（60秒ごとに更新）
    last_twilight_check = 0.0
    cached_twilight = False
    state.current_twilight_detection_mode = twilight_detection_mode
    state.current_twilight_type = twilight_type

    # 方式4（薄明期間バーストレート抑制）。観測はcached_twilight中の確定
    # イベントごとに行う。EventMergerの秒オーダーのバースト抑制とは独立させる
    # （分オーダーの現象を対象とするため、EventMerger内部のギャップクラスタリング
    # には一切手を入れない）。
    if twilight_rate_suppress_enabled and twilight_rate_max_events <= 0:
        print(
            "[WARN] twilight_rate_suppress_enabled=true ですが "
            "twilight_rate_max_events<=0 のため抑制は発動しません"
            "（観測専用モードのまま）。抑制を有効にするには "
            "TWILIGHT_RATE_MAX_EVENTS を正の値に設定してください",
            flush=True,
        )
    twilight_rate_limiter = TwilightRateLimiter(
        window_sec=twilight_rate_window_sec,
        max_events=twilight_rate_max_events if twilight_rate_suppress_enabled else 0,
    )

    def _save_if_allowed(ev):
        """方式2（残光チェック）を通過したイベントのみsave_meteor_event()に回す。

        4箇所ある確定イベントの保存経路（通常フロー・タイムアウト排出・
        finalize_all・シャットダウン残処理）を一本化し、方式2の適用漏れを防ぐ。
        棄却時はdetection_countを増やさず、mitigation_rejected_countsのみ加算する。
        """
        if contrail_check_enabled:
            try:
                is_contrail = check_contrail_afterglow(
                    ring_buffer,
                    ev,
                    params,
                    window=contrail_afterglow_window,
                    residual_brightness_ratio=contrail_residual_brightness_ratio,
                )
            except Exception as e:
                print(f"[WARN] 残光チェックでエラー、フィルタを適用せず通します: {e}", flush=True)
                is_contrail = False
            if is_contrail:
                state.current_mitigation_rejected_counts["contrail_afterglow"] += 1
                print(
                    f"[INFO] rejected_by=contrail_afterglow start={ev.start_time:.3f} end={ev.end_time:.3f}",
                    flush=True,
                )
                return None

        if cached_twilight:
            # 観測モード（twilight_rate_suppress_enabled=False）でもレートは
            # 記録する。抑制発動閾値(twilight_rate_max_events)を決めるための
            # 実データ収集が観測モードの目的であり、記録自体を抑制フラグで
            # ゲートすると常にレート0のままになってしまう。
            twilight_rate_limiter.record_event(ev.end_time)
            # mitigation_rejected_countsのキー名は他3方式が「棄却数」なのに対し
            # ここは「直近ウィンドウ内の薄明期間確定イベント数」（現在のレート、
            # 累積ではない）。方式4は抑制せず記録するだけの状態もあるため
            # 棄却数ではないが、既存のstate.current_mitigation_rejected_counts
            # 辞書（/stats露出、設計書指定のキー構成）に一本化するためここに置く。
            state.current_mitigation_rejected_counts["twilight_rate"] = twilight_rate_limiter.current_rate(
                ev.end_time
            )

        state.detection_count += 1
        print(f"\n[{ev.timestamp.strftime('%H:%M:%S')}] 流星検出 #{state.detection_count}")
        print(f"  長さ: {ev.length:.1f}px, 時間: {ev.duration:.2f}秒")
        return save_meteor_event(
            ev,
            ring_buffer,
            output_path,
            fps=fps,
            extract_clips=extract_clips,
            clip_margin_before=state.current_clip_margin_before,
            clip_margin_after=state.current_clip_margin_after,
            composite_after=state.current_clip_margin_after,
        )

    while not stop_flag.is_set():
        ret, timestamp, frame = reader.read()
        if not ret:
            state.is_detecting_now = False
            state.current_detection_status = "STREAM_LOST"
            break
        if frame is None:
            continue

        # ストリーム生存確認用の時刻を更新
        state.last_frame_time = time.time()
        recent_frame_times.append(timestamp)
        if len(recent_frame_times) > 30:
            recent_frame_times.pop(0)
        if len(recent_frame_times) >= 2:
            dt = recent_frame_times[-1] - recent_frame_times[0]
            if dt > 0:
                state.current_runtime_fps = (len(recent_frame_times) - 1) / dt

        ring_buffer.add(timestamp, frame)

        if process_scale != 1.0:
            proc_frame = cv2.resize(frame, (proc_width, proc_height), interpolation=cv2.INTER_AREA)
        else:
            proc_frame = frame

        gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)

        # 天文薄暮期間のチェック（定期的に）
        if enable_time_window and is_detection_active:
            if detection_start is None or detection_end is None:
                is_detection_time, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
            else:
                now = datetime.now(detection_start.tzinfo)
                if now > detection_end:
                    is_detection_time, detection_start, detection_end = is_detection_active(latitude, longitude, timezone)
                else:
                    is_detection_time = detection_start <= now <= detection_end
            state.current_detection_window_active = is_detection_time
            state.current_detection_window_start = detection_start.strftime("%Y-%m-%d %H:%M:%S")
            state.current_detection_window_end = detection_end.strftime("%Y-%m-%d %H:%M:%S")

        # 薄明判定（60秒キャッシュ）
        now_mono = time.time()
        if is_twilight_active is not None and now_mono - last_twilight_check >= 60.0:
            try:
                new_cached_twilight = is_twilight_active(latitude, longitude, timezone, twilight_type)
            except Exception:
                new_cached_twilight = False
            if cached_twilight and not new_cached_twilight:
                # 薄明期間が終了したら方式4のレート表示を陳腐化させない
                # （/statsがmitigation_rejected_counts.twilight_rateとして
                # 前回薄明期間の値をいつまでも返し続けるのを防ぐ）。
                state.current_mitigation_rejected_counts["twilight_rate"] = 0
            cached_twilight = new_cached_twilight
            state.current_twilight_active = cached_twilight
            last_twilight_check = now_mono

        objects = []
        if prev_gray is not None:
            # 検出期間内の場合のみ検出処理を実行
            if not state.current_detection_enabled:
                objects = []
                state.is_detecting_now = False
                state.current_detection_status = "DISABLED"
            elif is_detection_time:
                if cached_twilight and is_twilight_active is not None:
                    if twilight_detection_mode == "skip":
                        objects = []
                        state.is_detecting_now = False
                        state.current_detection_status = "TWILIGHT_SKIP"
                    else:
                        # reduce モード: 感度プリセットと min_speed を上書きした params で検出
                        effective_twilight_sensitivity = twilight_sensitivity
                        if twilight_rate_suppress_enabled and twilight_rate_limiter.should_suppress(timestamp):
                            # 方式4: レート超過時は感度プリセットを一段階下げて
                            # （low側へ）検出継続する。すでにlowの場合はこれ以上
                            # 下げられないためそのまま維持する。
                            effective_twilight_sensitivity = _TWILIGHT_SENSITIVITY_STEP_DOWN.get(
                                twilight_sensitivity, twilight_sensitivity
                            )
                        twilight_params = build_twilight_params(
                            effective_twilight_sensitivity,
                            twilight_min_speed,
                            params,
                            twilight_max_speed=twilight_max_speed,
                        )
                        # detector の params を一時差し替えて検出し、元に戻す
                        orig_params = detector.params
                        detector.params = twilight_params
                        try:
                            tracking_mode = len(detector.active_tracks) > 0
                            objects = detector.detect_bright_objects(gray, prev_gray, tracking_mode=tracking_mode)
                        finally:
                            detector.params = orig_params
                        if twilight_bird_filter_enabled:
                            objects = filter_dark_objects(objects, twilight_bird_min_brightness)
                        state.is_detecting_now = True
                        state.current_detection_status = "DETECTING"
                else:
                    # アクティブなトラックがある場合は追跡モードを有効化
                    tracking_mode = len(detector.active_tracks) > 0
                    objects = detector.detect_bright_objects(gray, prev_gray, tracking_mode=tracking_mode)
                    if bird_filter_enabled:
                        objects = filter_dark_objects(objects, bird_min_brightness)
                    state.is_detecting_now = True
                    state.current_detection_status = "DETECTING"
            else:
                objects = []
                state.is_detecting_now = False
                state.current_detection_status = "OUT_OF_WINDOW"
        else:
            state.is_detecting_now = False
            state.current_detection_status = "WAITING_FRAME"

        if process_scale != 1.0:
            for obj in objects:
                cx, cy = obj["centroid"]
                obj["centroid"] = (int(cx * scale_factor), int(cy * scale_factor))

        events = detector.track_objects(objects, timestamp)

        # 方式1a・方式3の棄却カウンタをstateへ反映（detectorはdetection_stateに
        # 依存させない方針のため、この境界でのみ合算する）。track_objects()は
        # トラック確定時（gap>max_gap_time）のみ_finalize_track()を呼ぶため、
        # 棄却のみが起きてeventsが空のフレームもあり得る。detector側は単調増加の
        # 累計値を持つのでそのまま上書きコピーする（トラック確定頻度＝低頻度の
        # ためコスト無視できる）。
        state.current_mitigation_rejected_counts["heading_variance"] = detector.rejected_counts.get(
            "heading_variance", 0
        )
        state.current_mitigation_rejected_counts["max_speed"] = detector.rejected_counts.get("max_speed", 0)

        for event in events:
            if stop_flag.is_set():
                break
            merged_events = merger.add_event(event)
            for merged_event in merged_events:
                # 1周の内側で多数のイベントが確定すると save_meteor_event() の
                # MP4書き出しが件数分だけ直列に走り、停止要求が来てもループを
                # 抜けられずメインスレッドの join(timeout=5.0) がタイムアウトする。
                # その結果「終了」ログの後もこのスレッドが保存を続けてしまうため、
                # 保存のたびに停止要求を確認する。
                if stop_flag.is_set():
                    break
                clip_path = _save_if_allowed(merged_event)

        expired_events = merger.flush_expired(timestamp)
        for expired_event in expired_events:
            if stop_flag.is_set():
                break
            clip_path = _save_if_allowed(expired_event)

        # プレビュー用フレーム生成
        display = frame.copy()

        for obj in objects:
            cx, cy = obj["centroid"]
            cv2.circle(display, (cx, cy), 5, (0, 255, 0), 2)

        with detector.lock:
            for track_points in detector.active_tracks.values():
                if len(track_points) >= 2:
                    for i in range(1, len(track_points)):
                        pt1 = (track_points[i-1][1], track_points[i-1][2])
                        pt2 = (track_points[i][1], track_points[i][2])
                        cv2.line(display, pt1, pt2, (0, 255, 255), 2)

        elapsed = time.time() - state.start_time_global
        overlay_name = state.camera_display_name or state.camera_name
        cv2.putText(display, f"{overlay_name} | {elapsed:.0f}s | Detections: {state.detection_count}",
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        stream_jpeg = None
        ok, encoded_stream = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY])
        if ok:
            stream_jpeg = encoded_stream.tobytes()

        with state.current_frame_lock:
            state.current_frame = display
            state.current_frame_seq += 1
            if stream_jpeg is not None:
                state.current_stream_jpeg = stream_jpeg
                state.current_stream_jpeg_seq = state.current_frame_seq

        prev_gray = gray.copy()
        frame_count += 1

        if frame_count % (int(fps) * 60) == 0:
            elapsed = time.time() - state.start_time_global
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 稼働: {elapsed/60:.1f}分, 検出: {state.detection_count}個")

    # 終了処理
    events = detector.finalize_all()
    for event in events:
        merged_events = merger.add_event(event)
        for merged_event in merged_events:
            clip_path = _save_if_allowed(merged_event)

    # 終了時に残ったイベントを保存する。ここは stop_flag で打ち切らない
    # （停止要求そのものが到達のきっかけなので、打ち切ると常に保存0件になる）。
    # ただしメインスレッドの join(timeout=5.0) を大きく超えないよう、
    # 保存にかけてよい時間の上限を設ける。
    remaining = merger.flush_all()
    shutdown_save_deadline = time.time() + SHUTDOWN_SAVE_BUDGET_SEC
    for idx, event in enumerate(remaining):
        if idx > 0 and time.time() > shutdown_save_deadline:
            print(
                f"[WARN] 終了処理の保存が{SHUTDOWN_SAVE_BUDGET_SEC}秒を超えたため"
                f"残り{len(remaining) - idx}件の保存を打ち切りました",
                flush=True,
            )
            break
        clip_path = _save_if_allowed(event)


def process_rtsp_stream(  # pragma: no cover
    url: str,
    output_dir: str = "meteor_detections",
    params: DetectionParams = None,
    process_scale: float = 0.5,
    buffer_seconds: float = 15.0,
    sensitivity: str = "medium",
    web_port: int = 0,
    cam_name: str = "camera",
    extract_clips: bool = True,
    mask_image: Optional[str] = None,
    mask_from_day: Optional[str] = None,
    mask_dilate: int = 5,
    mask_save: Optional[str] = None,
    nuisance_mask_image: Optional[str] = None,
    nuisance_from_night: Optional[str] = None,
    nuisance_dilate: int = 3,
    nuisance_overlap_threshold: float = 0.60,
    clip_margin_before: float = 1.0,
    clip_margin_after: float = 1.0,
    bird_filter_enabled: bool = False,
    bird_min_brightness: float = 80.0,
    twilight_bird_filter_enabled: bool = True,
    twilight_bird_min_brightness: float = 80.0,
    contrail_check_enabled: bool = False,
    contrail_afterglow_window: float = 2.0,
    contrail_residual_brightness_ratio: float = 0.5,
    twilight_rate_window_sec: float = 300.0,
    twilight_rate_max_events: int = 0,
    twilight_rate_suppress_enabled: bool = False,
):
    params = params or DetectionParams()
    state.camera_name = _storage_camera_name(cam_name)
    state.camera_display_name = os.environ.get("CAMERA_NAME_DISPLAY", "")
    state.stream_timeout = float(os.environ.get("STREAM_TIMEOUT", str(state.stream_timeout)))

    override_paths = _runtime_override_paths(output_dir, cam_name)
    state.current_runtime_overrides_paths = override_paths
    runtime_overrides = {}
    loaded_from = None
    for path in override_paths:
        runtime_overrides = _load_runtime_overrides(path)
        if runtime_overrides:
            loaded_from = path
            break
    if runtime_overrides:
        print(f"ランタイム設定を適用: {loaded_from}")
        # 旧パスから読んだ場合でも、優先保存先へ寄せる
        try:
            _save_runtime_overrides(override_paths[0], runtime_overrides)
        except Exception as e:
            print(f"[WARN] ランタイム設定の移行保存に失敗: {override_paths[0]} ({e})")

    sensitivity = str(runtime_overrides.get("sensitivity", sensitivity))
    process_scale = float(runtime_overrides.get("scale", process_scale))
    buffer_seconds = float(runtime_overrides.get("buffer", buffer_seconds))
    extract_clips = _to_bool(runtime_overrides.get("extract_clips", extract_clips), default=extract_clips)
    mask_image = runtime_overrides.get("mask_image", mask_image) or None
    mask_from_day = runtime_overrides.get("mask_from_day", mask_from_day) or None
    mask_dilate = int(runtime_overrides.get("mask_dilate", mask_dilate))
    nuisance_mask_image = runtime_overrides.get("nuisance_mask_image", nuisance_mask_image) or None
    nuisance_from_night = runtime_overrides.get("nuisance_from_night", nuisance_from_night) or None
    nuisance_dilate = int(runtime_overrides.get("nuisance_dilate", nuisance_dilate))
    nuisance_overlap_threshold = float(
        runtime_overrides.get("nuisance_overlap_threshold", nuisance_overlap_threshold)
    )
    clip_margin_before = float(runtime_overrides.get("clip_margin_before", clip_margin_before))
    clip_margin_after = float(runtime_overrides.get("clip_margin_after", clip_margin_after))
    state.current_detection_enabled = _to_bool(runtime_overrides.get("detection_enabled", True), default=True)
    bird_filter_enabled = _to_bool(
        runtime_overrides.get("bird_filter_enabled", bird_filter_enabled),
        default=bird_filter_enabled,
    )
    bird_min_brightness = float(runtime_overrides.get("bird_min_brightness", bird_min_brightness))
    twilight_bird_filter_enabled = _to_bool(
        runtime_overrides.get("twilight_bird_filter_enabled", twilight_bird_filter_enabled),
        default=twilight_bird_filter_enabled,
    )
    twilight_bird_min_brightness = float(
        runtime_overrides.get("twilight_bird_min_brightness", twilight_bird_min_brightness)
    )
    contrail_check_enabled = _to_bool(
        runtime_overrides.get("contrail_check_enabled", contrail_check_enabled),
        default=contrail_check_enabled,
    )
    contrail_afterglow_window = float(
        runtime_overrides.get("contrail_afterglow_window", contrail_afterglow_window)
    )
    contrail_residual_brightness_ratio = float(
        runtime_overrides.get("contrail_residual_brightness_ratio", contrail_residual_brightness_ratio)
    )
    twilight_rate_window_sec = float(
        runtime_overrides.get("twilight_rate_window_sec", twilight_rate_window_sec)
    )
    twilight_rate_max_events = int(
        runtime_overrides.get("twilight_rate_max_events", twilight_rate_max_events)
    )
    twilight_rate_suppress_enabled = _to_bool(
        runtime_overrides.get("twilight_rate_suppress_enabled", twilight_rate_suppress_enabled),
        default=twilight_rate_suppress_enabled,
    )

    # env/config.json(runtime_overrides)いずれの経路でも/apply_settingsの検証
    # テーブル（http_handlers.pyのstartup_float_fields/startup_int_fields）と
    # 同じレンジへクランプする。特にtwilight_rate_window_secの下限1.0は、
    # 0や負値がTwilightRateLimiter._prune()のcutoff計算を破壊し記録を
    # 即座に全消去する問題を防ぐために必須。
    contrail_afterglow_window = _clamp_env_value_and_warn(
        "contrail_afterglow_window", contrail_afterglow_window, 0.0, 10.0
    )
    contrail_residual_brightness_ratio = _clamp_env_value_and_warn(
        "contrail_residual_brightness_ratio", contrail_residual_brightness_ratio, 0.0, 1.0
    )
    twilight_rate_window_sec = _clamp_env_value_and_warn(
        "twilight_rate_window_sec", twilight_rate_window_sec, 1.0, 3600.0
    )
    twilight_rate_max_events = int(
        _clamp_env_value_and_warn("twilight_rate_max_events", twilight_rate_max_events, 0, None)
    )

    params.exclude_bottom_ratio = float(runtime_overrides.get("exclude_bottom_ratio", params.exclude_bottom_ratio))
    params.exclude_edge_ratio = float(runtime_overrides.get("exclude_edge_ratio", params.exclude_edge_ratio))
    pending_param_overrides = {}
    for field in (
        "diff_threshold",
        "min_brightness",
        "min_brightness_tracking",
        "min_length",
        "max_length",
        "min_duration",
        "max_duration",
        "min_speed",
        "min_linearity",
        "min_area",
        "max_area",
        "max_gap_time",
        "max_distance",
        "merge_max_gap_time",
        "merge_max_distance",
        "merge_max_speed_ratio",
        "burst_window_time",
        "burst_max_events",
        "exclude_edge_ratio",
        "nuisance_path_overlap_threshold",
        "min_track_points",
        "max_stationary_ratio",
        "small_area_threshold",
        "max_speed",
        "max_heading_variance",
        "min_heading_variance_points",
        "record_track_points",
    ):
        if field in runtime_overrides:
            pending_param_overrides[field] = runtime_overrides[field]

    preset = apply_sensitivity_preset(params, sensitivity)
    params.__dict__.update(preset.__dict__)

    for field, value in pending_param_overrides.items():
        setattr(params, field, value)

    # 追跡中は検出閾値より低めにして追跡継続を優先
    if "min_brightness_tracking" not in runtime_overrides:
        params.min_brightness_tracking = (
            max(1, int(params.min_brightness * 0.8))
            if sensitivity == "faint"
            else params.min_brightness
        )
    params.nuisance_overlap_threshold = nuisance_overlap_threshold

    required_buffer = params.max_duration + 2.0
    effective_buffer_seconds = min(buffer_seconds, required_buffer)
    if effective_buffer_seconds != buffer_seconds:
        print(f"バッファ秒数を{effective_buffer_seconds:.1f}秒に調整（検出前後1秒 + 最大検出時間）")

    # 設定情報を更新（ダッシュボード表示用）
    state.current_settings.update({
        "sensitivity": sensitivity,
        "scale": process_scale,
        "buffer": effective_buffer_seconds,
        "extract_clips": extract_clips,
        "exclude_bottom": params.exclude_bottom_ratio,
        "exclude_bottom_ratio": params.exclude_bottom_ratio,
        "exclude_edge_ratio": params.exclude_edge_ratio,
        "source_fps": 30.0,
        "mask_image": mask_image or "",
        "mask_from_day": mask_from_day or "",
        "mask_dilate": mask_dilate,
        "nuisance_mask_image": nuisance_mask_image or "",
        "nuisance_from_night": nuisance_from_night or "",
        "nuisance_dilate": nuisance_dilate,
        "nuisance_overlap_threshold": nuisance_overlap_threshold,
        "clip_margin_before": clip_margin_before,
        "clip_margin_after": clip_margin_after,
        "detection_enabled": state.current_detection_enabled,
        "bird_filter_enabled": bird_filter_enabled,
        "bird_min_brightness": bird_min_brightness,
        "twilight_bird_filter_enabled": twilight_bird_filter_enabled,
        "twilight_bird_min_brightness": twilight_bird_min_brightness,
        "diff_threshold": params.diff_threshold,
        "min_brightness": params.min_brightness,
        "min_brightness_tracking": params.min_brightness_tracking,
        "min_length": params.min_length,
        "max_length": params.max_length,
        "min_duration": params.min_duration,
        "max_duration": params.max_duration,
        "min_speed": params.min_speed,
        "min_linearity": params.min_linearity,
        "min_area": params.min_area,
        "max_area": params.max_area,
        "max_gap_time": params.max_gap_time,
        "max_distance": params.max_distance,
        "merge_max_gap_time": params.merge_max_gap_time,
        "merge_max_distance": params.merge_max_distance,
        "merge_max_speed_ratio": params.merge_max_speed_ratio,
        "burst_window_time": params.burst_window_time,
        "burst_max_events": params.burst_max_events,
        "nuisance_path_overlap_threshold": params.nuisance_path_overlap_threshold,
        "min_track_points": params.min_track_points,
        "max_stationary_ratio": params.max_stationary_ratio,
        "small_area_threshold": params.small_area_threshold,
        "max_speed": params.max_speed,
        "max_heading_variance": params.max_heading_variance,
        "min_heading_variance_points": params.min_heading_variance_points,
        "record_track_points": params.record_track_points,
        "contrail_check_enabled": contrail_check_enabled,
        "contrail_afterglow_window": contrail_afterglow_window,
        "contrail_residual_brightness_ratio": contrail_residual_brightness_ratio,
        "twilight_rate_window_sec": twilight_rate_window_sec,
        "twilight_rate_max_events": twilight_rate_max_events,
        "twilight_rate_suppress_enabled": twilight_rate_suppress_enabled,
    })

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"RTSPストリーム: {url}", flush=True)
    print(f"出力先: {output_path}", flush=True)
    if web_port > 0:
        print(f"Webプレビュー: http://0.0.0.0:{web_port}/", flush=True)

    # Webサーバー起動
    httpd = None
    if web_port > 0:
        httpd = ThreadedHTTPServer(('0.0.0.0', web_port), MJPEGHandler)
        web_thread = Thread(target=httpd.serve_forever, daemon=True)
        web_thread.start()

    rtsp_log_detail = _to_bool(os.environ.get("RTSP_LOG_DETAIL", "true"), default=True)
    reader = RTSPReader(url, log_detail=rtsp_log_detail)
    print(f"RTSP事前診断: {probe_rtsp_endpoint(url)}", flush=True)
    if rtsp_log_detail:
        print(f"RTSP ffprobe診断: {probe_rtsp_with_ffprobe(url)}", flush=True)
    print("接続中...", flush=True)
    reader.start()

    if not reader.connected.is_set():
        print("接続失敗（10秒以内に接続確立できず）", flush=True)
        return

    width, height = reader.frame_size
    fps = sanitize_fps(reader.fps, default=30.0)

    state.current_settings["source_fps"] = fps
    state.current_rtsp_url = url

    print(f"解像度: {width}x{height}", flush=True)
    print("検出開始 (Ctrl+C で終了)", flush=True)
    print("-" * 50, flush=True)

    state.detection_count = 0
    state.start_time_global = time.time()
    state.current_runtime_fps = 0.0

    stop_flag = Event()
    state.current_stop_flag = stop_flag

    def signal_handler(sig, frame):
        print("\n終了中...")
        stop_flag.set()

    signal.signal(signal.SIGINT, signal_handler)

    # 環境変数から天文薄暮期間の設定を取得
    enable_time_window = os.environ.get('ENABLE_TIME_WINDOW', 'true').lower() == 'true'
    latitude = float(os.environ.get('LATITUDE', '35.3606'))
    longitude = float(os.environ.get('LONGITUDE', '138.7274'))
    timezone = os.environ.get('TIMEZONE', 'Asia/Tokyo')

    TWILIGHT_DETECTION_MODE = os.environ.get("TWILIGHT_DETECTION_MODE", "reduce")  # "reduce" or "skip"
    TWILIGHT_TYPE = os.environ.get("TWILIGHT_TYPE", "nautical")  # "civil"/"nautical"/"astronomical"
    TWILIGHT_SENSITIVITY = os.environ.get("TWILIGHT_SENSITIVITY", "low")  # sensitivity preset
    try:
        TWILIGHT_MIN_SPEED = float(os.environ.get("TWILIGHT_MIN_SPEED", "200"))
    except ValueError:
        TWILIGHT_MIN_SPEED = 200.0
    # 方式3（薄明期間速度上限フィルタ）。既定0=無効。UIには公開しない
    # env-only設定（twilight_min_speedと同様、/apply_settingsの対応表がなく
    # UI経由では変更できないdead endを新規に再現しないため）。
    try:
        TWILIGHT_MAX_SPEED = float(os.environ.get("TWILIGHT_MAX_SPEED", "0"))
    except ValueError:
        TWILIGHT_MAX_SPEED = 0.0

    _valid_twilight_modes = {"reduce", "skip"}
    if TWILIGHT_DETECTION_MODE not in _valid_twilight_modes:
        print(
            f"WARNING: TWILIGHT_DETECTION_MODE={TWILIGHT_DETECTION_MODE!r} は無効です。"
            " デフォルト 'reduce' を使用します。",
            flush=True,
        )
        TWILIGHT_DETECTION_MODE = "reduce"

    _valid_twilight_sensitivities = {"low", "medium", "high", "faint"}
    if TWILIGHT_SENSITIVITY not in _valid_twilight_sensitivities:
        print(
            f"WARNING: TWILIGHT_SENSITIVITY={TWILIGHT_SENSITIVITY!r} は無効です。"
            " デフォルト 'low' を使用します。",
            flush=True,
        )
        TWILIGHT_SENSITIVITY = "low"

    _valid_twilight_types = {"civil", "nautical", "astronomical"}
    if TWILIGHT_TYPE not in _valid_twilight_types:
        print(
            f"WARNING: TWILIGHT_TYPE={TWILIGHT_TYPE!r} は無効です。"
            " デフォルト 'nautical' を使用します。",
            flush=True,
        )
        TWILIGHT_TYPE = "nautical"

    if enable_time_window:
        print(f"検出時間制限: 有効（緯度: {latitude}, 経度: {longitude}）", flush=True)
    else:
        print(f"検出時間制限: 無効（常時検出）", flush=True)

    # twilight 設定を current_settings に反映（TWILIGHT_* 変数はここで確定済み）
    state.current_settings.update({
        "twilight_detection_mode": TWILIGHT_DETECTION_MODE,
        "twilight_type": TWILIGHT_TYPE,
        "twilight_sensitivity": TWILIGHT_SENSITIVITY,
        "twilight_min_speed": TWILIGHT_MIN_SPEED,
        "twilight_max_speed": TWILIGHT_MAX_SPEED,
    })

    # 検出処理を別スレッドで実行
    detection_thread = Thread(
        target=detection_thread_worker,
        args=(reader, params, process_scale, effective_buffer_seconds, fps, output_path, extract_clips, stop_flag),
        kwargs={
            'mask_image': mask_image,
            'mask_from_day': mask_from_day,
            'mask_dilate': mask_dilate,
            'mask_save': Path(mask_save) if mask_save else None,
            'nuisance_mask_image': nuisance_mask_image,
            'nuisance_from_night': nuisance_from_night,
            'nuisance_dilate': nuisance_dilate,
            'clip_margin_before': clip_margin_before,
            'clip_margin_after': clip_margin_after,
            'enable_time_window': enable_time_window,
            'latitude': latitude,
            'longitude': longitude,
            'timezone': timezone,
            'twilight_detection_mode': TWILIGHT_DETECTION_MODE,
            'twilight_type': TWILIGHT_TYPE,
            'twilight_sensitivity': TWILIGHT_SENSITIVITY,
            'twilight_min_speed': TWILIGHT_MIN_SPEED,
            'twilight_max_speed': TWILIGHT_MAX_SPEED,
            'bird_filter_enabled': bird_filter_enabled,
            'bird_min_brightness': bird_min_brightness,
            'twilight_bird_filter_enabled': twilight_bird_filter_enabled,
            'twilight_bird_min_brightness': twilight_bird_min_brightness,
            'contrail_check_enabled': contrail_check_enabled,
            'contrail_afterglow_window': contrail_afterglow_window,
            'contrail_residual_brightness_ratio': contrail_residual_brightness_ratio,
            'twilight_rate_window_sec': twilight_rate_window_sec,
            'twilight_rate_max_events': twilight_rate_max_events,
            'twilight_rate_suppress_enabled': twilight_rate_suppress_enabled,
        },
        daemon=False,
    )
    detection_thread.start()

    # メインスレッドは停止シグナルを待機
    try:
        while not stop_flag.is_set():
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n終了中...")
        stop_flag.set()

    # 検出スレッドの終了を待機
    detection_thread.join(timeout=5.0)
    if detection_thread.is_alive():
        # ここに来ると検出スレッドが生き残ったまま以降の後始末が進む。
        # 過去に、バーストで多数のイベントが確定した際にMP4書き出しが直列に走って
        # 5秒では抜けきれず、「終了」ログの後もスレッドが検出結果を書き続けた事例がある。
        print(
            "[WARN] 検出スレッドが5秒以内に終了しませんでした。"
            "保存処理が継続している可能性があります",
            flush=True,
        )

    with state.current_recording_lock:
        job = state.current_recording_job
    if job and job.get("state") in ("scheduled", "recording"):
        _stop_recording_process(job, reason="camera service shutting down")

    reader.stop()
    if httpd:
        httpd.shutdown()
    state.current_stop_flag = None

    print(f"\n終了 - 検出数: {state.detection_count}個", flush=True)


def main():  # pragma: no cover
    parser = argparse.ArgumentParser(description="RTSPストリーム流星検出（Webプレビュー付き）")

    parser.add_argument("url", help="RTSP URL")
    parser.add_argument("-o", "--output", default="meteor_detections", help="出力ディレクトリ")
    parser.add_argument("--sensitivity", choices=["low", "medium", "high", "faint", "fireball"], default="medium")
    parser.add_argument("--scale", type=float, default=0.5, help="処理スケール")
    parser.add_argument("--buffer", type=float, default=15.0, help="バッファ秒数")
    parser.add_argument("--exclude-bottom", type=float, default=1/16)
    parser.add_argument("--web-port", type=int, default=0, help="Webプレビューポート (0=無効)")
    parser.add_argument("--camera-name", default="camera", help="カメラ名")
    parser.add_argument("--extract-clips", action="store_true", default=True,
                        help="流星検出時に動画クリップを保存 (デフォルト: 有効)")
    parser.add_argument("--no-clips", action="store_true",
                        help="動画クリップを保存しない（コンポジット画像のみ）")
    parser.add_argument("--mask-image", help="作成済みの除外マスク画像を使用（優先）")
    parser.add_argument("--mask-from-day", help="昼間画像から検出除外マスクを生成（空以外を除外）")
    parser.add_argument("--mask-dilate", type=int, default=20, help="除外マスクの拡張ピクセル数")
    parser.add_argument("--mask-save", help="生成した除外マスク画像の保存先")
    parser.add_argument("--nuisance-mask-image", help="作成済みのノイズ帯マスク画像を使用")
    parser.add_argument("--nuisance-from-night", help="夜間基準画像からノイズ帯マスクを生成")
    parser.add_argument("--nuisance-dilate", type=int, default=3, help="ノイズ帯マスクの拡張ピクセル数")
    parser.add_argument(
        "--nuisance-overlap-threshold",
        type=float,
        default=0.60,
        help="小領域候補を除外するノイズ帯重なり率の閾値",
    )
    parser.add_argument("--clip-margin-before", type=float, default=1.0, help="検出前の記録秒数")
    parser.add_argument("--clip-margin-after", type=float, default=1.0, help="検出後の記録秒数")

    args = parser.parse_args()

    params = DetectionParams()
    params.exclude_bottom_ratio = args.exclude_bottom

    # クリップ抽出の判定（--no-clips または環境変数 EXTRACT_CLIPS=false で無効化）
    env_extract = os.environ.get("EXTRACT_CLIPS", "true").lower()
    extract_clips = not args.no_clips and env_extract not in ("false", "0", "no")

    bird_filter_enabled = os.environ.get("BIRD_FILTER_ENABLED", "false").lower() in ("1", "true", "yes")
    try:
        bird_min_brightness = float(os.environ.get("BIRD_MIN_BRIGHTNESS", "80"))
    except ValueError:
        bird_min_brightness = 80.0
    twilight_bird_filter_enabled = os.environ.get("TWILIGHT_BIRD_FILTER_ENABLED", "true").lower() in ("1", "true", "yes")
    try:
        twilight_bird_min_brightness = float(os.environ.get("TWILIGHT_BIRD_MIN_BRIGHTNESS", "80"))
    except ValueError:
        twilight_bird_min_brightness = 80.0

    # 方式1b（観測専用）。既定False=記録しない。データ構造が変わるため
    # DetectionParams側のフィールドとしてここで確定させる（bird_filter_enabled
    # と同様の起動時パターン）。
    params.record_track_points = os.environ.get("RECORD_TRACK_POINTS", "false").lower() in ("1", "true", "yes")

    # 方式2（飛行機雲の残光チェック）。既定False=無効。
    # レンジ検証はprocess_rtsp_stream()側で行う（runtime_overrides経由の
    # 上書きも同じ関数を通るため、env/config.json両経路を一箇所でカバーする）。
    contrail_check_enabled = os.environ.get("CONTRAIL_CHECK_ENABLED", "false").lower() in ("1", "true", "yes")
    try:
        contrail_afterglow_window = float(os.environ.get("CONTRAIL_AFTERGLOW_WINDOW", "2.0"))
    except ValueError:
        contrail_afterglow_window = 2.0
    try:
        contrail_residual_brightness_ratio = float(
            os.environ.get("CONTRAIL_RESIDUAL_BRIGHTNESS_RATIO", "0.5")
        )
    except ValueError:
        contrail_residual_brightness_ratio = 0.5

    # 方式4（薄明期間バーストレート抑制、観測モードから開始）。既定False=抑制なし。
    try:
        twilight_rate_window_sec = float(os.environ.get("TWILIGHT_RATE_WINDOW_SEC", "300"))
    except ValueError:
        twilight_rate_window_sec = 300.0
    try:
        twilight_rate_max_events = int(os.environ.get("TWILIGHT_RATE_MAX_EVENTS", "0"))
    except ValueError:
        twilight_rate_max_events = 0
    twilight_rate_suppress_enabled = os.environ.get(
        "TWILIGHT_RATE_SUPPRESS_ENABLED", "false"
    ).lower() in ("1", "true", "yes")

    mask_image = args.mask_image.strip() if args.mask_image else None
    mask_image = mask_image if mask_image else None
    mask_from_day = args.mask_from_day.strip() if args.mask_from_day else None
    mask_from_day = mask_from_day if mask_from_day else None
    mask_save = args.mask_save.strip() if args.mask_save else None
    mask_save = mask_save if mask_save else None
    nuisance_mask_image = args.nuisance_mask_image.strip() if args.nuisance_mask_image else None
    nuisance_mask_image = nuisance_mask_image if nuisance_mask_image else None
    nuisance_from_night = args.nuisance_from_night.strip() if args.nuisance_from_night else None
    nuisance_from_night = nuisance_from_night if nuisance_from_night else None

    process_rtsp_stream(
        args.url,
        output_dir=args.output,
        params=params,
        process_scale=args.scale,
        buffer_seconds=args.buffer,
        sensitivity=args.sensitivity,
        web_port=args.web_port,
        cam_name=args.camera_name,
        extract_clips=extract_clips,
        mask_image=mask_image,
        mask_from_day=mask_from_day,
        mask_dilate=args.mask_dilate,
        mask_save=mask_save,
        nuisance_mask_image=nuisance_mask_image,
        nuisance_from_night=nuisance_from_night,
        nuisance_dilate=args.nuisance_dilate,
        nuisance_overlap_threshold=args.nuisance_overlap_threshold,
        clip_margin_before=args.clip_margin_before,
        clip_margin_after=args.clip_margin_after,
        bird_filter_enabled=bird_filter_enabled,
        bird_min_brightness=bird_min_brightness,
        twilight_bird_filter_enabled=twilight_bird_filter_enabled,
        twilight_bird_min_brightness=twilight_bird_min_brightness,
        contrail_check_enabled=contrail_check_enabled,
        contrail_afterglow_window=contrail_afterglow_window,
        contrail_residual_brightness_ratio=contrail_residual_brightness_ratio,
        twilight_rate_window_sec=twilight_rate_window_sec,
        twilight_rate_max_events=twilight_rate_max_events,
        twilight_rate_suppress_enabled=twilight_rate_suppress_enabled,
    )


def _setup_log_file():  # pragma: no cover
    """LOG_FILE環境変数が指定されていれば stdout/stderr をファイルにも出力する"""
    log_path = os.environ.get("LOG_FILE")
    if not log_path:
        return
    try:
        from logging.handlers import RotatingFileHandler

        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        class _TeeStream:
            """元のストリームとローテーションファイルの両方に書き込む"""
            def __init__(self, orig, handler):
                self._orig = orig
                self._handler = handler

            def write(self, data):
                self._orig.write(data)
                if data:
                    self._handler.stream.write(data)
                    self._handler.stream.flush()
                    if self._handler.stream.tell() >= self._handler.maxBytes:
                        self._handler.doRollover()

            def flush(self):
                self._orig.flush()
                try:
                    self._handler.stream.flush()
                except Exception:
                    pass

            def fileno(self):
                return self._orig.fileno()

        handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        sys.stdout = _TeeStream(sys.__stdout__, handler)
        sys.stderr = _TeeStream(sys.__stderr__, handler)
    except Exception as e:
        print(f"[WARN] ログファイル設定に失敗: {e}", file=sys.__stderr__)


if __name__ == "__main__":
    _setup_log_file()
    main()
