#!/usr/bin/env python3
"""
RTSPストリームからリアルタイムで流星を検出するプログラム

使い方:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

import argparse
import cv2
from datetime import datetime
from pathlib import Path
import time
import signal
import sys
from threading import Event

from meteor_detector_realtime import (
    DetectionParams,
    EventMerger,
    RTSPReader,
    RealtimeMeteorDetector,
    RingBuffer,
    save_meteor_event,
)

VERSION = "1.6.0"


def process_rtsp_stream(
    url: str,
    output_dir: str = "meteor_detections",
    params: DetectionParams = None,
    process_scale: float = 0.5,
    buffer_seconds: float = 15.0,
    show_preview: bool = False,
    sensitivity: str = "medium",
):
    """RTSPストリームを処理"""
    params = params or DetectionParams()
    params.max_gap_time = 0.2
    params.merge_max_gap_time = 0.7

    # 感度プリセット
    if sensitivity == "low":
        params.diff_threshold = 40
        params.min_brightness = 220
        params.min_length = 30
    elif sensitivity == "high":
        params.diff_threshold = 20
        params.min_brightness = 180
        params.min_length = 15
    elif sensitivity == "fireball":
        params.diff_threshold = 15
        params.min_brightness = 150
        params.min_length = 30
        params.max_duration = 20.0
        params.min_speed = 20.0
        params.min_linearity = 0.6

    params.min_brightness_tracking = params.min_brightness

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"RTSPストリーム: {url}")
    print(f"出力先: {output_path}")
    print(f"感度: {sensitivity}")
    print(f"処理スケール: {process_scale}")
    print(f"バッファ: {buffer_seconds}秒")
    print()

    # ストリーム接続
    reader = RTSPReader(url, log_detail=True)
    print("接続中...")
    reader.start()

    if not reader.connected.is_set():
        print("接続に失敗しました")
        return

    width, height = reader.frame_size
    fps = reader.fps
    proc_width = int(width * process_scale)
    proc_height = int(height * process_scale)
    scale_factor = 1.0 / process_scale

    print(f"解像度: {width}x{height} @ {fps:.1f}fps")
    print(f"処理解像度: {proc_width}x{proc_height}")
    print()
    print("検出開始 (Ctrl+C で終了)")
    print("-" * 50)

    # コンポーネント初期化
    ring_buffer = RingBuffer(buffer_seconds, fps)
    detector = RealtimeMeteorDetector(params, fps)
    merger = EventMerger(params)

    prev_gray = None
    detection_count = 0
    frame_count = 0
    start_time = time.time()

    # シグナルハンドラ
    stop_flag = Event()

    def signal_handler(sig, frame):
        print("\n終了中...")
        stop_flag.set()

    signal.signal(signal.SIGINT, signal_handler)

    try:
        while not stop_flag.is_set():
            ret, timestamp, frame = reader.read()

            if not ret:
                break

            if frame is None:
                continue

            # バッファに保存
            ring_buffer.add(timestamp, frame)

            # 処理用にリサイズ
            if process_scale != 1.0:
                proc_frame = cv2.resize(frame, (proc_width, proc_height),
                                       interpolation=cv2.INTER_AREA)
            else:
                proc_frame = frame

            gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)

            if prev_gray is not None:
                # 検出
                objects = detector.detect_bright_objects(gray, prev_gray)

                # 座標変換
                if process_scale != 1.0:
                    for obj in objects:
                        cx, cy = obj["centroid"]
                        obj["centroid"] = (int(cx * scale_factor), int(cy * scale_factor))

                # 追跡
                events = detector.track_objects(objects, timestamp)

                # 流星イベントを保存
                for event in events:
                    merged_events = merger.add_event(event)
                    for merged_event in merged_events:
                        detection_count += 1
                        print(f"\n[{merged_event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
                        print(f"  長さ: {merged_event.length:.1f}px, 時間: {merged_event.duration:.2f}秒")
                        print(f"  信頼度: {merged_event.confidence:.0%}")
                        overlay_text = f"{merged_event.timestamp.strftime('%H:%M:%S')} | Conf: {merged_event.confidence:.0%}"
                        save_meteor_event(
                            merged_event,
                            ring_buffer,
                            output_path,
                            fps=fps,
                            extract_clips=True,
                            clip_margin_before=2.0,
                            clip_margin_after=2.0,
                            composite_after=0.0,
                            overlay_text=overlay_text,
                        )

                expired_events = merger.flush_expired(timestamp)
                for expired_event in expired_events:
                    detection_count += 1
                    print(f"\n[{expired_event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
                    print(f"  長さ: {expired_event.length:.1f}px, 時間: {expired_event.duration:.2f}秒")
                    print(f"  信頼度: {expired_event.confidence:.0%}")
                    overlay_text = f"{expired_event.timestamp.strftime('%H:%M:%S')} | Conf: {expired_event.confidence:.0%}"
                    save_meteor_event(
                        expired_event,
                        ring_buffer,
                        output_path,
                        fps=fps,
                        extract_clips=True,
                        clip_margin_before=2.0,
                        clip_margin_after=2.0,
                        composite_after=0.0,
                        overlay_text=overlay_text,
                    )

                # プレビュー
                if show_preview:
                    display = frame.copy()

                    # 検出中の物体
                    for obj in objects:
                        cx, cy = obj["centroid"]
                        cv2.circle(display, (cx, cy), 5, (0, 255, 0), 2)

                    # アクティブトラック
                    with detector.lock:
                        for track_points in detector.active_tracks.values():
                            if len(track_points) >= 2:
                                for i in range(1, len(track_points)):
                                    pt1 = (track_points[i-1][1], track_points[i-1][2])
                                    pt2 = (track_points[i][1], track_points[i][2])
                                    cv2.line(display, pt1, pt2, (0, 255, 255), 2)

                    # 情報表示
                    elapsed = time.time() - start_time
                    cv2.putText(display, f"Time: {elapsed:.1f}s | Detections: {detection_count}",
                               (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                    cv2.imshow("RTSP Meteor Detection", display)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

            prev_gray = gray.copy()
            frame_count += 1

            # 定期的な状態表示
            if frame_count % (int(fps) * 60) == 0:  # 1分ごと
                elapsed = time.time() - start_time
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"稼働: {elapsed/60:.1f}分, 検出: {detection_count}個")

    finally:
        # 残りのトラックを処理
        events = detector.finalize_all()
        for event in events:
            merged_events = merger.add_event(event)
            for merged_event in merged_events:
                detection_count += 1
                print(f"\n[{merged_event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
                save_meteor_event(merged_event, ring_buffer, output_path, fps=fps)

        for event in merger.flush_all():
            detection_count += 1
            print(f"\n[{event.timestamp.strftime('%H:%M:%S')}] 流星検出 #{detection_count}")
            save_meteor_event(event, ring_buffer, output_path, fps=fps)

        reader.stop()
        if show_preview:
            cv2.destroyAllWindows()

        elapsed = time.time() - start_time
        print()
        print("=" * 50)
        print(f"終了")
        print(f"稼働時間: {elapsed/60:.1f}分")
        print(f"検出数: {detection_count}個")
        print(f"出力先: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="RTSPストリームからリアルタイム流星検出",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
================================================================================
使用例
================================================================================

  基本的な使い方:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream

  プレビューウィンドウを表示しながら検出:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --preview

  火球（長く明るい流星）の検出に最適化:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --sensitivity fireball

  出力先ディレクトリを指定:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream -o ./my_detections

  処理負荷を軽減（解像度を1/4に縮小して処理）:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --scale 0.25

  長い火球用にバッファを30秒に拡張:
    python meteor_detector_rtsp.py rtsp://192.168.1.100:554/stream --buffer 30

================================================================================
感度プリセット (--sensitivity)
================================================================================

  low      誤検出を最小限に抑える。明るい流星のみ検出。
           ノイズの多い環境や、確実な検出のみ記録したい場合に推奨。

  medium   バランスの取れた設定（デフォルト）。
           一般的な流星観測に適しています。

  high     暗い流星も検出。感度が高いため誤検出が増える可能性あり。
           暗い空や、微光流星も記録したい場合に推奨。

  fireball 火球検出に最適化。長時間（最大20秒）の明るい流星を検出。
           軌道が多少曲がっていても検出可能。流星群の極大期に推奨。

================================================================================
出力ファイル
================================================================================

  検出された流星ごとに以下のファイルが自動保存されます:

  meteor_YYYYMMDD_HHMMSS.mov
      流星が写っているクリップ動画（前後2秒のマージン含む）
      マーキングなしの元映像

  meteor_YYYYMMDD_HHMMSS_composite.jpg
      流星の全フレームを比較明合成した画像（軌跡マーク付き）

  meteor_YYYYMMDD_HHMMSS_composite_original.jpg
      合成画像（マーキングなし）

  detections.jsonl
      全検出結果のログ（JSON Lines形式、1行1イベント）
      時刻、座標、信頼度などの詳細情報を記録

================================================================================
終了方法
================================================================================

  Ctrl+C で安全に終了します。
  終了時、処理中の流星トラックも保存されます。

================================================================================
        """
    )

    parser.add_argument("url",
        help="RTSPストリームのURL\n"
             "例: rtsp://192.168.1.100:554/stream\n"
             "    rtsp://user:pass@192.168.1.100:554/ch1")

    parser.add_argument("-o", "--output",
        default="meteor_detections",
        metavar="DIR",
        help="検出結果の出力先ディレクトリ。\n"
             "存在しない場合は自動作成されます。\n"
             "(デフォルト: meteor_detections)")

    parser.add_argument("--preview",
        action="store_true",
        help="検出状況をリアルタイムでプレビュー表示します。\n"
             "検出中の物体は緑色の丸、追跡中の軌跡は黄色の線で表示。\n"
             "プレビューウィンドウで 'q' キーを押すと終了。")

    parser.add_argument("--sensitivity",
        choices=["low", "medium", "high", "fireball"],
        default="medium",
        metavar="LEVEL",
        help="検出感度のプリセット。\n"
             "  low:      誤検出を減らす（明るい流星のみ）\n"
             "  medium:   バランス（デフォルト）\n"
             "  high:     暗い流星も検出\n"
             "  fireball: 火球検出モード（長時間・高輝度）")

    parser.add_argument("--scale",
        type=float,
        default=0.5,
        metavar="RATIO",
        help="処理解像度のスケール（0.1〜1.0）。\n"
             "小さいほど処理が軽くなりますが、暗い流星を見逃す可能性あり。\n"
             "  1.0:  フル解像度（高精度・高負荷）\n"
             "  0.5:  半分の解像度（デフォルト、バランス良好）\n"
             "  0.25: 1/4解像度（低負荷、火球検出向き）\n"
             "(デフォルト: 0.5)")

    parser.add_argument("--buffer",
        type=float,
        default=15.0,
        metavar="SEC",
        help="フレームバッファの保持秒数。\n"
             "流星検出時、この秒数分の過去フレームからクリップを生成します。\n"
             "長い火球を記録する場合は大きめに設定してください。\n"
             "メモリ使用量に影響します（目安: 1080p/30fps で 1秒≒150MB）。\n"
             "(デフォルト: 15秒)")

    parser.add_argument("--exclude-bottom",
        type=float,
        default=1/16,
        metavar="RATIO",
        help="画像下部の検出除外範囲（0〜1）。\n"
             "タイムスタンプやカメラ情報の誤検出を防ぎます。\n"
             "  0:      除外なし\n"
             "  0.0625: 下部1/16を除外（デフォルト）\n"
             "  0.125:  下部1/8を除外\n"
             "(デフォルト: 0.0625 = 1/16)")

    args = parser.parse_args()

    params = DetectionParams()
    params.exclude_bottom_ratio = args.exclude_bottom

    process_rtsp_stream(
        args.url,
        output_dir=args.output,
        params=params,
        process_scale=args.scale,
        buffer_seconds=args.buffer,
        show_preview=args.preview,
        sensitivity=args.sensitivity,
    )


if __name__ == "__main__":
    main()
