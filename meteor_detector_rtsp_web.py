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
from typing import List, Tuple, Optional, Dict
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
)
from recording_manager import (
    _stop_recording_process,
)
from http_handlers import MJPEGHandler, ThreadedHTTPServer, STREAM_JPEG_QUALITY

VERSION = "3.6.1"

# 天文薄暮期間の判定用
try:
    from astro_utils import is_detection_active
except ImportError:
    is_detection_active = None

try:
    from astro_twilight_utils import is_twilight_active
except ImportError:
    is_twilight_active = None


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
    bird_filter_enabled=False,
    bird_min_brightness=80.0,
    twilight_bird_filter_enabled=True,
    twilight_bird_min_brightness=80.0,
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
        if mask_image is None and persistent_mask_path.exists():
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
                cached_twilight = is_twilight_active(latitude, longitude, timezone, twilight_type)
            except Exception:
                cached_twilight = False
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
                        twilight_params = build_twilight_params(twilight_sensitivity, twilight_min_speed, params)
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

        for event in events:
            merged_events = merger.add_event(event)
            for merged_event in merged_events:
                state.detection_count += 1
                print(f"\n[{merged_event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{state.detection_count}")
                print(f"  長さ: {merged_event.length:.1f}px, 時間: {merged_event.duration:.2f}秒")
                clip_path = save_meteor_event(
                    merged_event,
                    ring_buffer,
                    output_path,
                    fps=fps,
                    extract_clips=extract_clips,
                    clip_margin_before=state.current_clip_margin_before,
                    clip_margin_after=state.current_clip_margin_after,
                    composite_after=state.current_clip_margin_after,
                )

        expired_events = merger.flush_expired(timestamp)
        for expired_event in expired_events:
            state.detection_count += 1
            print(f"\n[{expired_event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{state.detection_count}")
            print(f"  長さ: {expired_event.length:.1f}px, 時間: {expired_event.duration:.2f}秒")
            clip_path = save_meteor_event(
                expired_event,
                ring_buffer,
                output_path,
                fps=fps,
                extract_clips=extract_clips,
                clip_margin_before=state.current_clip_margin_before,
                clip_margin_after=state.current_clip_margin_after,
                composite_after=state.current_clip_margin_after,
            )

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
            state.detection_count += 1
            clip_path = save_meteor_event(
                merged_event,
                ring_buffer,
                output_path,
                fps=fps,
                extract_clips=extract_clips,
                clip_margin_before=state.current_clip_margin_before,
                clip_margin_after=state.current_clip_margin_after,
                composite_after=state.current_clip_margin_after,
            )

    for event in merger.flush_all():
        state.detection_count += 1
        clip_path = save_meteor_event(
            event,
            ring_buffer,
            output_path,
            fps=fps,
            extract_clips=extract_clips,
            clip_margin_before=state.current_clip_margin_before,
            clip_margin_after=state.current_clip_margin_after,
            composite_after=state.current_clip_margin_after,
        )


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
):
    params = params or DetectionParams()
    state.camera_name = _storage_camera_name(cam_name)
    state.camera_display_name = os.environ.get("CAMERA_NAME_DISPLAY", "")

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
        "exclude_edge_ratio",
        "nuisance_path_overlap_threshold",
        "min_track_points",
        "max_stationary_ratio",
        "small_area_threshold",
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
        "nuisance_path_overlap_threshold": params.nuisance_path_overlap_threshold,
        "min_track_points": params.min_track_points,
        "max_stationary_ratio": params.max_stationary_ratio,
        "small_area_threshold": params.small_area_threshold,
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
            'bird_filter_enabled': bird_filter_enabled,
            'bird_min_brightness': bird_min_brightness,
            'twilight_bird_filter_enabled': twilight_bird_filter_enabled,
            'twilight_bird_min_brightness': twilight_bird_min_brightness,
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
