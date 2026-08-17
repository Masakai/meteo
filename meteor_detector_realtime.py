"""
RTSPリアルタイム検出の共通コンポーネント

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from collections import deque
from threading import Thread, Lock, Event
from queue import Queue, Empty
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

import cv2
import numpy as np

from meteor_detector_common import calculate_linearity, calculate_confidence, open_video_writer

# FFmpegバックエンドのTCP読み書きタイムアウト（マイクロ秒）。TCP接続が生きたまま
# ストリームが停止すると cap.read() が無期限にブロックしうるため、
# RTSP_RW_TIMEOUT_US が明示的に設定された場合のみ有効化する（既定では未設定＝
# 従来通りOpenCVの組み込みデフォルトのまま）。無条件にデフォルト値を設定しない
# 理由: (1) OPENCV_FFMPEG_CAPTURE_OPTIONS は既存のオプションを上書きするため、
# コンテナのOpenCVビルドが元々どのデフォルトを使っていたか未検証のまま置き換える
# リスクがある。(2) rtsp:// 入力に対してFFmpegのRTSPデムクサーが解釈するのは
# 主に timeout（旧stimeout）オプションであり、汎用AVIOオプションの rw_timeout は
# RTSP経由では無視されることが多い。効果が未検証のため、既定で有効化せず
# 明示的なopt-inとする。有効化する場合はコンテナのOpenCV/FFmpegビルドで
# 実際に効くか確認すること。
_rw_timeout_us = os.environ.get("RTSP_RW_TIMEOUT_US")
if _rw_timeout_us:
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        f"rtsp_transport;tcp|rw_timeout;{_rw_timeout_us}",
    )

# 棄却理由の[DEBUG]ログは、ノイズ多発時（大量の輪郭・トラックが棄却される局面）に
# ホットループ内のI/O負荷とログ肥大の一因になるため、既定では出力しない。
# METEOR_DEBUG_LOG=1（またはtrue/yes/on）で有効化する。ホットループ内で毎回
# os.getenvを呼ばないよう、モジュール読み込み時に一度だけ判定する。
_DEBUG_LOG_ENABLED = os.environ.get("METEOR_DEBUG_LOG", "").strip().lower() in ("1", "true", "yes", "on")


def _debug_log(message: str) -> None:
    if _DEBUG_LOG_ENABLED:
        print(message, flush=True)


def write_mp4_clip_ffmpeg(
    output_path: Path,
    frames: List[Tuple[float, np.ndarray]],
    *,
    fps: float,
    size: Tuple[int, int],
    wait_timeout: float = 60.0,
) -> bool:
    """ffmpegで目的メタデータに近いMP4を直接出力する。"""
    width, height = size
    target_fps = sanitize_fps(fps, default=30.0)
    gop = int(target_fps * 2)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{target_fps:.3f}",
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-profile:v",
        "baseline",
        "-level",
        "4.0",
        "-pix_fmt",
        "yuv420p",
        "-bf",
        "0",
        "-refs",
        "1",
        "-coder",
        "0",
        "-x264-params",
        "cabac=0:ref=1:bframes=0:weightp=0:8x8dct=0:force-cfr=1",
        "-fps_mode",
        "cfr",
        "-g",
        str(gop),
        "-keyint_min",
        str(gop),
        "-sc_threshold",
        "0",
        "-video_track_timescale",
        "15360",
        "-tag:v",
        "avc1",
        "-brand",
        "isom",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    # stderrは一時ファイルへ逃がす（returncode!=0時の表示にのみ使うため、
    # フレーム書き込み中にパイプバッファが溢れてffmpegがブロックし、
    # proc.stdin.write()と相互待ちになるデッドロックを避ける）。
    # stdoutは使わないためDEVNULLへ捨てる。
    with tempfile.TemporaryFile() as stderr_file:
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
            )
        except FileNotFoundError:
            return False
        except Exception:
            return False

        try:
            assert proc.stdin is not None
            for _, frame in frames:
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            proc.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return False
        except Exception:
            proc.kill()
            proc.wait()
            return False
        finally:
            # kill()後にはstdinバッファ未送出のデータが残っている場合があり、
            # 死んだプロセスへのパイプをcloseするとBrokenPipeErrorを送出しうる。
            # ここで例外を伝播させるとフォールバック経路に到達できなくなるため抑制する。
            if proc.stdin is not None and not proc.stdin.closed:
                with contextlib.suppress(Exception):
                    proc.stdin.close()

        if proc.returncode != 0:
            stderr_file.seek(0)
            stderr = stderr_file.read()
            if stderr:
                sys.stderr.write(stderr.decode("utf-8", errors="ignore"))
            return False
        return True


def write_clip_with_fallback(
    output_path: Path,
    frames: List[Tuple[float, np.ndarray]],
    *,
    fps: float,
    size: Tuple[int, int],
    wait_timeout: float = 60.0,
) -> bool:
    """ffmpeg優先でMP4を書き出し、失敗時のみOpenCVへフォールバックする。"""
    if write_mp4_clip_ffmpeg(output_path, frames, fps=fps, size=size, wait_timeout=wait_timeout):
        return True

    writer = open_video_writer(output_path, fps, size)
    if writer is None:
        return False
    for _, frame in frames:
        writer.write(frame)
    writer.release()
    return True


def sanitize_fps(value: Optional[float], default: float = 30.0) -> float:
    """FPS値を実用範囲に正規化"""
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(fps):
        return default
    if fps < 1.0 or fps > 120.0:
        return default
    return fps


def estimate_fps_from_frames(
    frames: List[Tuple[float, np.ndarray]],
    fallback_fps: float = 30.0,
    max_ratio_to_fallback: float = 1.5,
) -> float:
    """フレーム時刻差の中央値から実効FPSを推定

    fallback_fpsはRTSP接続時にネゴシエートされたカメラ本来のfpsを想定する。
    CPU飽和等でcap.read()の呼び出し間隔が乱れると、フレームに付与される
    受信時刻が実際の撮影間隔より詰まり、推定fpsがカメラの実効fpsを大きく
    上回ることがある（2026-08-16の本番greeng4で、接続時20.0fpsのカメラに対し
    108fps・117fpsで書き出された事例）。これらはsanitize_fps()の上限120.0の
    内側にあるため上限だけでは弾けない。カメラのネゴシエーション値を基準に
    max_ratio_to_fallback倍を超える推定値を退けることで、実効fpsの正常な変動
    （夜間IRモードでの低下など）は保ちつつ非物理的な値のみ除外する。
    """
    sanitized_fallback = sanitize_fps(fallback_fps, default=30.0)

    if len(frames) < 2:
        return sanitized_fallback

    deltas: List[float] = []
    for idx in range(1, len(frames)):
        dt = frames[idx][0] - frames[idx - 1][0]
        if dt > 0:
            deltas.append(dt)

    if not deltas:
        return sanitized_fallback

    median_dt = float(np.median(np.array(deltas, dtype=np.float64)))
    if median_dt <= 0:
        return sanitized_fallback

    estimated_fps = sanitize_fps(1.0 / median_dt, default=sanitized_fallback)
    if estimated_fps > sanitized_fallback * max_ratio_to_fallback:
        print(
            f"[WARN] fps推定値をクランプ: 推定={estimated_fps:.1f} "
            f"接続時={sanitized_fallback:.1f} 上限比率={max_ratio_to_fallback} "
            "(CPU飽和等でフレーム受信間隔が乱れている可能性)",
            flush=True,
        )
        return sanitized_fallback

    return estimated_fps


def probe_rtsp_endpoint(url: str, timeout: float = 3.0) -> str:
    """RTSP先の host:port 到達性を簡易診断して文字列で返す。"""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = int(parsed.port or 554)
    except Exception as e:
        return f"probe=invalid_url error={e}"

    if not host:
        return "probe=invalid_url error=missing_host"

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return f"probe=tcp_ok host={host} port={port}"
    except Exception as e:
        return f"probe=tcp_error host={host} port={port} error={type(e).__name__}: {e}"


def probe_rtsp_with_ffprobe(url: str, timeout: float = 8.0) -> str:
    """ffprobe で RTSP セッション開始可否を簡易診断する。"""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-show_streams",
        url,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return "ffprobe=missing"
    except subprocess.TimeoutExpired:
        return f"ffprobe=timeout timeout={timeout}s"
    except Exception as e:
        return f"ffprobe=error error={type(e).__name__}: {e}"

    if result.returncode == 0:
        return "ffprobe=ok"

    detail = (result.stderr or result.stdout or "").strip().replace("\n", " | ")
    if not detail:
        detail = f"returncode={result.returncode}"
    return f"ffprobe=error detail={detail}"


@dataclass
class MeteorEvent:
    """検出された流星イベント"""
    timestamp: datetime
    start_time: float
    end_time: float
    start_point: Tuple[int, int]
    end_point: Tuple[int, int]
    peak_brightness: float
    confidence: float
    frames: List[Tuple[float, np.ndarray]]

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def length(self) -> float:
        dx = self.end_point[0] - self.start_point[0]
        dy = self.end_point[1] - self.start_point[1]
        return np.sqrt(dx**2 + dy**2)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "duration": round(self.duration, 3),
            "start_point": self.start_point,
            "end_point": self.end_point,
            "length_pixels": round(self.length, 1),
            "peak_brightness": round(self.peak_brightness, 1),
            "confidence": round(self.confidence, 2),
        }


@dataclass
class DetectionParams:
    """検出パラメータ"""
    diff_threshold: int = 30
    min_brightness: int = 200
    min_brightness_tracking: Optional[int] = None
    min_length: int = 20
    max_length: int = 5000
    min_duration: float = 0.1
    max_duration: float = 10.0
    min_speed: float = 50.0
    min_linearity: float = 0.7
    min_area: int = 5
    max_area: int = 10000
    max_gap_time: float = 2.0
    max_distance: float = 80
    merge_max_gap_time: float = 1.5
    merge_max_distance: float = 80
    merge_max_speed_ratio: float = 0.5
    # 同時刻バースト抑制: 到着間隔が burst_window_time 秒以内で連なった
    # イベントの塊（クラスタ）のサイズが burst_max_events 件を超えた場合、
    # 流星ではなく画面全体の輝度急変（雷のフラッシュ、雲の明滅など）由来の
    # ノイズとみなしてクラスタ内のイベントをすべて破棄する。
    burst_window_time: float = 1.0
    burst_max_events: int = 5
    exclude_bottom_ratio: float = 1 / 16
    exclude_edge_ratio: float = 0.0  # 四辺から除外する割合（0.0〜0.5）。UIからはpx指定→ratio変換で設定される。例: 20px / min(幅,高さ)
    nuisance_overlap_threshold: float = 0.60
    nuisance_path_overlap_threshold: float = 0.70
    min_track_points: int = 4
    max_stationary_ratio: float = 0.40
    small_area_threshold: int = 40

    def __post_init__(self):
        if self.min_brightness_tracking is None:
            self.min_brightness_tracking = self.min_brightness
        self.validate()

    def validate(self) -> None:
        """レンジ外の値を安全な値へクランプし、[WARN]ログを出す。

        exclude_bottom_ratio / exclude_edge_ratio が範囲外（特に1.0超）だと
        detect_bright_objects() のマスク処理でthreshが無警告に全面ゼロ化され
        検出が全滅する。無警告の機能停止を避けるため、クランプ発動時は必ず
        警告を出す。

        レンジは http_handlers.py の /apply_settings 入力検証テーブル
        （int_fields / float_fields）の既存の正の値と一致させている。二層で
        食い違うと運用者の正当な設定が別の値にクランプされるため。

        注意: この検証は __post_init__ 経由の生成時のみ有効。
        meteor_detector_rtsp_web.py の setattr ループ・
        params.__dict__.update(preset.__dict__) は dataclass の再初期化を
        経由しないため、ここでのクランプは通らない（http_handlers.py 側の
        /apply_settings は別途レンジ検証済み。詳細は実装仕様書の残課題を参照）。
        """
        self.exclude_bottom_ratio = self._clamp_and_warn(
            "exclude_bottom_ratio", self.exclude_bottom_ratio, 0.0, 1.0
        )
        self.exclude_edge_ratio = self._clamp_and_warn(
            "exclude_edge_ratio", self.exclude_edge_ratio, 0.0, 0.5
        )
        self.burst_window_time = self._clamp_and_warn(
            "burst_window_time", self.burst_window_time, 0.0, None
        )
        self.burst_max_events = int(
            self._clamp_and_warn("burst_max_events", self.burst_max_events, 1, None)
        )

        # burst_max_events × burst_window_time が _prune_arrival_times() の
        # 保持幅（10 × max(burst_window_time, merge_max_gap_time)）を超える
        # 極端な設定では、クラスタ前端の到着記録が刈られてバースト検知漏れ
        # （破棄されない方向＝安全側）が起こりうる。3変数の関係式でクランプ先が
        # 一意に決まらないため、ここでは警告のみに留める。
        cluster_span = self.burst_max_events * self.burst_window_time
        retention = 10 * max(self.burst_window_time, self.merge_max_gap_time)
        if cluster_span > retention:
            print(
                f"[WARN] バースト抑制の設定が保持幅を超えています: "
                f"burst_max_events({self.burst_max_events}) × "
                f"burst_window_time({self.burst_window_time}) = {cluster_span:.2f} > "
                f"保持幅 {retention:.2f}。クラスタ前端の到着記録が刈られ、"
                "バースト検知漏れが起こりうる",
                flush=True,
            )

    @staticmethod
    def _clamp_and_warn(name: str, value: float, min_v: Optional[float], max_v: Optional[float]) -> float:
        clamped = value
        if min_v is not None and clamped < min_v:
            clamped = min_v
        if max_v is not None and clamped > max_v:
            clamped = max_v
        if clamped != value:
            print(
                f"[WARN] DetectionParams.{name}={value} は許容範囲外のためクランプ: {clamped}",
                flush=True,
            )
        return clamped


class RingBuffer:
    """リングバッファ"""

    def __init__(self, max_seconds: float, fps: float = 30):
        self.max_frames = max(1, int(max_seconds * fps))
        self.buffer: deque = deque(maxlen=self.max_frames)
        self.lock = Lock()

    def add(self, timestamp: float, frame: np.ndarray):
        with self.lock:
            self.buffer.append((timestamp, frame.copy()))

    def get_range(self, start_time: float, end_time: float) -> List[Tuple[float, np.ndarray]]:
        with self.lock:
            return [(t, f.copy()) for t, f in self.buffer if start_time <= t <= end_time]


class RTSPReader:
    """RTSPストリーム読み込み"""

    def __init__(self, url: str, reconnect_delay: float = 5.0, log_detail: bool = False):
        self.url = url
        self.reconnect_delay = reconnect_delay
        self.log_detail = log_detail
        self.queue = Queue(maxsize=30)
        self.stopped = Event()
        self.connected = Event()
        self.thread = None
        self.fps = 30.0
        self.width = 0
        self.height = 0
        self.start_time = None
        self.lock = Lock()

    def start(self):
        self.thread = Thread(target=self._read_loop, daemon=True)
        self.thread.start()
        self.connected.wait(timeout=10)
        return self

    def _read_loop(self):
        attempt = 0
        while not self.stopped.is_set():
            attempt += 1
            cap = cv2.VideoCapture(self.url)

            if not cap.isOpened():
                probe = probe_rtsp_endpoint(self.url)
                print(f"接続失敗: {self.url} ({probe}, attempt={attempt})", flush=True)
                if self.log_detail:
                    if attempt <= 3 or (attempt % 12) == 0:
                        ffprobe_detail = probe_rtsp_with_ffprobe(self.url)
                        print(f"RTSP詳細診断: {ffprobe_detail}", flush=True)
                    print("OpenCVがRTSPセッションを開始できませんでした。認証情報、URLパス、RTSPポート、カメラ側同時接続数を確認してください。", flush=True)
                    print(f"{self.reconnect_delay}秒後に再接続...", flush=True)
                time.sleep(self.reconnect_delay)
                continue

            with self.lock:
                self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.fps = sanitize_fps(cap.get(cv2.CAP_PROP_FPS), default=30.0)
                if self.start_time is None:
                    # NTPステップ調整でジャンプしうる壁時計(time.time())ではなく
                    # 単調増加するmonotonicクロックを基準にする。start_time/timestamp
                    # はプロセス起動からの相対秒というセマンティクス（detections.jsonl の
                    # start_time/end_time も同様）は変わらない。
                    self.start_time = time.monotonic()

            print(f"接続成功: {self.width}x{self.height} @ {self.fps:.1f}fps", flush=True)
            attempt = 0
            self.connected.set()

            consecutive_failures = 0
            while not self.stopped.is_set():
                ret, frame = cap.read()

                if not ret:
                    consecutive_failures += 1
                    if consecutive_failures > 30:
                        if self.log_detail:
                            print("ストリーム切断を検出", flush=True)
                        break
                    time.sleep(0.01)
                    continue

                consecutive_failures = 0
                timestamp = time.monotonic() - self.start_time

                if self.queue.full():
                    try:
                        self.queue.get_nowait()
                    except Empty:
                        pass

                self.queue.put((timestamp, frame))

            cap.release()
            self.connected.clear()

            if not self.stopped.is_set():
                if self.log_detail:
                    print(f"{self.reconnect_delay}秒後に再接続...", flush=True)
                time.sleep(self.reconnect_delay)

    def read(self) -> Tuple[bool, float, Optional[np.ndarray]]:
        if self.stopped.is_set():
            return False, 0, None
        try:
            timestamp, frame = self.queue.get(timeout=1.0)
            return True, timestamp, frame
        except Empty:
            return True, 0, None

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=2.0)

    @property
    def frame_size(self):
        with self.lock:
            return (self.width, self.height)


class RealtimeMeteorDetector:
    """リアルタイム流星検出器"""

    CONF_SPEED_NORM = 500.0
    CONF_DURATION_NORM = 1.0
    CONF_DURATION_SCALE = 0.1
    CONF_DURATION_MAX = 0.2

    def __init__(
        self,
        params: DetectionParams,
        fps: float = 30,
        exclusion_mask: Optional[np.ndarray] = None,
        nuisance_mask: Optional[np.ndarray] = None,
    ):
        self.params = params
        self.fps = fps
        self.exclusion_mask = exclusion_mask
        self.nuisance_mask = nuisance_mask
        self.active_tracks: Dict[int, List[Tuple[float, int, int, float]]] = {}
        self.next_track_id = 0
        self.lock = Lock()
        self.mask_lock = Lock()

    def detect_bright_objects(self, frame: np.ndarray, prev_frame: np.ndarray, tracking_mode: bool = False) -> List[dict]:
        """明るい移動物体を検出"""
        height = frame.shape[0]
        width = frame.shape[1]
        max_y = int(height * (1 - self.params.exclude_bottom_ratio))

        diff = cv2.absdiff(frame, prev_frame)
        _, thresh = cv2.threshold(diff, self.params.diff_threshold, 255, cv2.THRESH_BINARY)
        thresh[max_y:, :] = 0
        # 画像周辺の固定ノイズを除外
        edge = max(0, int(min(width, height) * self.params.exclude_edge_ratio))
        if edge > 0:
            thresh[:edge, :] = 0
            thresh[height - edge:, :] = 0
            thresh[:, :edge] = 0
            thresh[:, width - edge:] = 0
        with self.mask_lock:
            exclusion_mask = self.exclusion_mask
            nuisance_mask = self.nuisance_mask
        if exclusion_mask is not None:
            thresh[exclusion_mask > 0] = 0

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        min_brightness = self.params.min_brightness_tracking if tracking_mode else self.params.min_brightness

        objects = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if not (self.params.min_area <= area <= self.params.max_area):
                continue

            M = cv2.moments(contour)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])

            if cy >= max_y:
                continue

            # 輪郭の外接矩形(ROI)に限定してマスク確保・走査することで、
            # フレーム全面 np.zeros + cv2.mean(全面走査) を輪郭サイズに縮小する
            # （結果は従来の全面マスク方式と同一）。
            rx, ry, rw, rh = cv2.boundingRect(contour)
            roi_mask = np.zeros((rh, rw), dtype=np.uint8)
            cv2.drawContours(roi_mask, [contour], -1, 255, -1, offset=(-rx, -ry))
            roi_frame = frame[ry:ry + rh, rx:rx + rw]
            brightness = cv2.mean(roi_frame, mask=roi_mask)[0]
            nuisance_overlap_ratio = 0.0
            if nuisance_mask is not None and area <= self.params.small_area_threshold:
                roi_nuisance_mask = nuisance_mask[ry:ry + rh, rx:rx + rw]
                nuisance_overlap_ratio = self._calculate_mask_overlap_ratio(roi_mask, roi_nuisance_mask)
                if nuisance_overlap_ratio >= self.params.nuisance_overlap_threshold:
                    _debug_log(
                        f"[DEBUG] rejected_by=nuisance_overlap area={area:.1f} "
                        f"ratio={nuisance_overlap_ratio:.2f}"
                    )
                    continue

            if brightness >= min_brightness:
                objects.append({
                    "centroid": (cx, cy),
                    "area": area,
                    "brightness": brightness,
                    "nuisance_overlap_ratio": nuisance_overlap_ratio,
                })

        return objects

    def track_objects(self, objects: List[dict], timestamp: float) -> List[MeteorEvent]:
        completed_events = []
        used_objects = set()

        with self.lock:
            tracks_to_remove = []
            for track_id, track_points in self.active_tracks.items():
                if not track_points:
                    continue

                last_time, last_x, last_y, _ = track_points[-1]
                gap = timestamp - last_time

                if gap > self.params.max_gap_time:
                    tracks_to_remove.append(track_id)
                    continue

                best_match = None
                best_dist = float("inf")

                for i, obj in enumerate(objects):
                    if i in used_objects:
                        continue

                    cx, cy = obj["centroid"]
                    dist = np.sqrt((cx - last_x) ** 2 + (cy - last_y) ** 2)

                    if len(track_points) >= 2:
                        prev_time, prev_x, prev_y, _ = track_points[-2]
                        dt = last_time - prev_time
                        if dt > 0:
                            vx = (last_x - prev_x) / dt
                            vy = (last_y - prev_y) / dt
                            pred_x = last_x + vx * gap
                            pred_y = last_y + vy * gap
                            pred_dist = np.sqrt((cx - pred_x) ** 2 + (cy - pred_y) ** 2)
                            dist = min(dist, pred_dist)

                    if dist < self.params.max_distance and dist < best_dist:
                        best_dist = dist
                        best_match = i

                if best_match is not None:
                    obj = objects[best_match]
                    cx, cy = obj["centroid"]
                    track_points.append((timestamp, cx, cy, obj["brightness"]))
                    used_objects.add(best_match)

            for track_id in tracks_to_remove:
                event = self._finalize_track(track_id)
                if event:
                    completed_events.append(event)

            for i, obj in enumerate(objects):
                if i not in used_objects:
                    cx, cy = obj["centroid"]
                    self.active_tracks[self.next_track_id] = [
                        (timestamp, cx, cy, obj["brightness"])
                    ]
                    self.next_track_id += 1

        return completed_events

    def _finalize_track(self, track_id: int) -> Optional[MeteorEvent]:
        if track_id not in self.active_tracks:
            return None

        track_points = self.active_tracks.pop(track_id)
        if len(track_points) < self.params.min_track_points:
            _debug_log(
                f"[DEBUG] rejected_by=min_track_points points={len(track_points)} "
                f"required={self.params.min_track_points}"
            )
            return None

        times = [p[0] for p in track_points]
        duration = max(times) - min(times)

        if not (self.params.min_duration <= duration <= self.params.max_duration):
            _debug_log(f"[DEBUG] rejected_by=duration duration={duration:.3f}")
            return None

        xs = [p[1] for p in track_points]
        ys = [p[2] for p in track_points]
        brightness = [p[3] for p in track_points]

        stationary_ratio = self._calculate_stationary_ratio(xs, ys)
        if stationary_ratio > self.params.max_stationary_ratio:
            _debug_log(
                f"[DEBUG] rejected_by=stationary_ratio ratio={stationary_ratio:.2f} "
                f"max={self.params.max_stationary_ratio:.2f}"
            )
            return None

        start_idx = times.index(min(times))
        end_idx = times.index(max(times))
        start_point = (xs[start_idx], ys[start_idx])
        end_point = (xs[end_idx], ys[end_idx])

        with self.mask_lock:
            nuisance_mask = self.nuisance_mask
        if nuisance_mask is not None:
            nuisance_path_overlap_ratio = self._calculate_line_overlap_ratio(
                nuisance_mask,
                start_point,
                end_point,
            )
            if nuisance_path_overlap_ratio > self.params.nuisance_path_overlap_threshold:
                _debug_log(
                    f"[DEBUG] rejected_by=nuisance_path_overlap ratio={nuisance_path_overlap_ratio:.2f} "
                    f"max={self.params.nuisance_path_overlap_threshold:.2f}"
                )
                return None

        length = np.sqrt((end_point[0] - start_point[0]) ** 2 +
                         (end_point[1] - start_point[1]) ** 2)

        if not (self.params.min_length <= length <= self.params.max_length):
            _debug_log(f"[DEBUG] rejected_by=length length={length:.1f}")
            return None

        speed = length / max(0.001, duration)
        if speed < self.params.min_speed:
            _debug_log(f"[DEBUG] rejected_by=speed speed={speed:.1f}")
            return None

        linearity = calculate_linearity(xs, ys)
        if linearity < self.params.min_linearity:
            _debug_log(f"[DEBUG] rejected_by=linearity linearity={linearity:.2f}")
            return None

        confidence = calculate_confidence(
            length,
            speed,
            linearity,
            max(brightness),
            duration,
            speed_norm=self.CONF_SPEED_NORM,
            duration_norm=self.CONF_DURATION_NORM,
            duration_bonus_scale=self.CONF_DURATION_SCALE,
            duration_bonus_max=self.CONF_DURATION_MAX,
        )

        return MeteorEvent(
            timestamp=datetime.now(),
            start_time=min(times),
            end_time=max(times),
            start_point=start_point,
            end_point=end_point,
            peak_brightness=max(brightness),
            confidence=confidence,
            frames=[],
        )

    def finalize_all(self) -> List[MeteorEvent]:
        events = []
        with self.lock:
            for track_id in list(self.active_tracks.keys()):
                event = self._finalize_track(track_id)
                if event:
                    events.append(event)
        return events

    def update_exclusion_mask(self, new_mask: Optional[np.ndarray]) -> None:
        with self.mask_lock:
            self.exclusion_mask = new_mask

    def update_nuisance_mask(self, new_mask: Optional[np.ndarray]) -> None:
        with self.mask_lock:
            self.nuisance_mask = new_mask

    @staticmethod
    def _calculate_mask_overlap_ratio(candidate_mask: np.ndarray, nuisance_mask: np.ndarray) -> float:
        candidate_area = int(np.count_nonzero(candidate_mask))
        if candidate_area == 0:
            return 0.0
        overlap = int(np.count_nonzero((candidate_mask > 0) & (nuisance_mask > 0)))
        return overlap / candidate_area

    @staticmethod
    def _calculate_stationary_ratio(xs: List[int], ys: List[int], px_threshold: float = 2.0) -> float:
        if len(xs) < 2:
            return 1.0
        stationary = 0
        steps = len(xs) - 1
        for idx in range(1, len(xs)):
            dist = np.hypot(xs[idx] - xs[idx - 1], ys[idx] - ys[idx - 1])
            if dist <= px_threshold:
                stationary += 1
        return stationary / max(1, steps)

    @staticmethod
    def _calculate_line_overlap_ratio(
        nuisance_mask: np.ndarray,
        start_point: Tuple[int, int],
        end_point: Tuple[int, int],
    ) -> float:
        line_mask = np.zeros_like(nuisance_mask, dtype=np.uint8)
        cv2.line(line_mask, start_point, end_point, 255, 2, cv2.LINE_AA)
        line_pixels = int(np.count_nonzero(line_mask))
        if line_pixels == 0:
            return 0.0
        overlap = int(np.count_nonzero((line_mask > 0) & (nuisance_mask > 0)))
        return overlap / line_pixels


class EventMerger:
    """近接イベントを結合して1イベント化"""

    def __init__(self, params: DetectionParams):
        self.params = params
        self.pending: deque[MeteorEvent] = deque()
        # 同時刻バースト判定用: 受理したイベントの到着時刻履歴（昇順とは限らない）。
        # 確定（flush）のたびにギャップでクラスタリングして判定する。
        self._arrival_times: List[float] = []
        self._burst_dropped = 0

    def add_event(self, event: MeteorEvent) -> List[MeteorEvent]:
        finalized = []

        # バースト判定用の到着ログには「新規に成立したイベント」の到着だけを
        # 積む。トラッキングの瞬断等で1つの流星が複数の断片に分かれ、
        # _is_mergeable の条件（時間・距離・速度差）で1件に結合される場合、
        # 断片の数だけ到着として数えてしまうと、正常な単一の流星がバースト
        # 判定に巻き込まれて誤って破棄される（実測で6断片の単一流星が
        # burst_max_events=5を超えて全破棄される事例を確認した）。
        # マージが成立した場合は新規到着として扱わない。
        if self.pending and self._is_mergeable(self.pending[-1], event):
            self.pending[-1] = self._merge(self.pending[-1], event)
        else:
            self._arrival_times.append(event.start_time)
            self.pending.append(event)

        self._prune_arrival_times(event.start_time)
        finalized.extend(self.flush_expired(event.start_time))
        return finalized

    def flush_expired(self, current_time: float) -> List[MeteorEvent]:
        finalized = []
        cutoff = current_time - self.params.merge_max_gap_time
        while self.pending and self.pending[0].end_time < cutoff:
            finalized.append(self.pending.popleft())
        return self._reject_bursts(finalized)

    def flush_all(self) -> List[MeteorEvent]:
        finalized = list(self.pending)
        self.pending.clear()
        return self._reject_bursts(finalized)

    def _prune_arrival_times(self, current_time: float) -> None:
        """十分に古くなった到着記録を捨てる（メモリ肥大の防止）。

        新規イベントの到着時（add_event）にのみ行う。基準は pending に残る
        最古イベントの start_time（未確定なら current_time）より前。pending が
        空でない間は、そこに滞留しているイベントの到着記録を消してはいけない
        ——確定（flush）はまだ先で、そのとき _burst_start_times() が判定に
        使うため。current_time を無条件の基準にすると、まだ確定していない
        イベントが pending に残ったまま、時間的に離れた別イベントが先に
        到着しただけでその到着記録が消え、後で確定した際に判定不能になる
        （実際に、離れた孤立イベントの到着で発生することを検出した）。
        """
        window = self.params.burst_window_time
        if window <= 0 or not self._arrival_times:
            return
        oldest_pending = self.pending[0].start_time if self.pending else current_time
        horizon = min(oldest_pending, current_time)
        keep_after = horizon - max(window, self.params.merge_max_gap_time) * 10
        self._arrival_times = [t for t in self._arrival_times if t >= keep_after]

    def _burst_start_times(self) -> set:
        """到着ログを到着間隔(ギャップ)でクラスタリングし、バースト由来と
        判定された start_time の集合を返す。

        累積到着数を窓でカウントする方式（旧実装）は、バーストの両端で
        必ず境界バグを生む構造的な欠陥があった。バースト末尾の到着記録が
        残ると直後の孤立イベント1件で誤検知し（レビュー指摘）、逆に検知の
        たびに記録をクリアすると継続中のバーストの末尾を取りこぼす。

        ギャップベースのクラスタリングならこの矛盾が生じない。連続到着の
        間隔が burst_window_time 秒以内の塊を1クラスタとみなし、そのサイズが
        burst_max_events を超えたクラスタだけをバーストと判定する。継続中の
        バーストは全体が1クラスタのままなので末尾の取りこぼしがない。

        注意: バースト終息直後、burst_window_time 秒以内に到着した次のイベント
        は単連結クラスタリングの定義上「同じクラスタの続き」として連結される
        （旧実装のように無関係に誤判定されるのではなく、方式の定義通りの挙動）。
        これは burst_window_time を「バースト検知後に一定時間は次のイベントも
        警戒する」設計として意図的に許容している。実データでの安全マージンは
        以下の通り大きい。

        実データの裏付け: 158件バーストの到着間隔は約0.095秒。目視で流星と
        確認された記録同士の最小間隔は297秒。既定のburst_window_time(1.0秒)は
        この間にあり両側に桁違いのマージンがある。

        到着記録のprune（メモリ肥大対策）は add_event() 側でのみ行う。ここで
        current_time を基準に刈ると、pending に長く滞留した古いイベントが
        確定するタイミングでその到着記録自体を消してしまい判定できなくなる。
        """
        window = self.params.burst_window_time
        limit = self.params.burst_max_events
        if window <= 0 or limit <= 0 or not self._arrival_times:
            return set()

        ordered = sorted(self._arrival_times)
        burst_times: set = set()
        cluster = [ordered[0]]
        for t in ordered[1:]:
            if t - cluster[-1] <= window:
                cluster.append(t)
            else:
                if len(cluster) > limit:
                    burst_times.update(cluster)
                cluster = [t]
        if len(cluster) > limit:
            burst_times.update(cluster)
        return burst_times

    def _reject_bursts(self, events: List[MeteorEvent]) -> List[MeteorEvent]:
        """バーストと判定された時間帯に含まれるイベントを除外する。

        雷のフラッシュや雲の明滅で画面全体の輝度が急変すると、空間的に散在する
        多数の点が同一フレーム群の中で同時に「軌跡」として成立し、1秒未満の間に
        数十〜百数十件のイベントが確定することがある（2026-08-15 01:55:00に
        camera2で158件、start_timeの幅0.192秒の実例）。個々のイベントは
        _is_mergeable の距離条件を満たさないため EventMerger では結合できず、
        そのまま全件がMP4書き出しに回ってCPU飽和を増幅する。

        判定自体は _burst_start_times() が到着ログのギャップクラスタリングで
        行う。flush_expired() が確定を複数バッチに分割しても、到着ログは
        add_event() のたびに蓄積されているため取りこぼさない。
        """
        if not events:
            return events

        burst_times = self._burst_start_times()
        if not burst_times:
            return events

        kept = [e for e in events if e.start_time not in burst_times]
        dropped = len(events) - len(kept)
        if dropped:
            self._burst_dropped += dropped
            print(
                f"[WARN] 同時刻バーストを検出: {dropped}件のイベントを破棄"
                f"（到着間隔{self.params.burst_window_time}秒以内の塊が"
                f"{self.params.burst_max_events}件超、"
                f"輝度急変由来のノイズと判断、累計{self._burst_dropped}件）",
                flush=True,
            )
        return kept

    def _is_mergeable(self, prev: MeteorEvent, new: MeteorEvent) -> bool:
        gap = new.start_time - prev.end_time
        if gap < 0 or gap > self.params.merge_max_gap_time:
            return False

        dist = np.hypot(
            new.start_point[0] - prev.end_point[0],
            new.start_point[1] - prev.end_point[1],
        )
        if dist > self.params.merge_max_distance:
            return False

        prev_speed = prev.length / max(prev.duration, 0.001)
        new_speed = new.length / max(new.duration, 0.001)
        max_speed = max(prev_speed, new_speed, 0.001)
        speed_ratio = abs(prev_speed - new_speed) / max_speed
        return speed_ratio <= self.params.merge_max_speed_ratio

    def _merge(self, prev: MeteorEvent, new: MeteorEvent) -> MeteorEvent:
        return MeteorEvent(
            timestamp=prev.timestamp,
            start_time=prev.start_time,
            end_time=new.end_time,
            start_point=prev.start_point,
            end_point=new.end_point,
            peak_brightness=max(prev.peak_brightness, new.peak_brightness),
            confidence=max(prev.confidence, new.confidence),
            frames=[],
        )


def make_detection_id(camera_name: str, record: dict) -> str:
    source = {
        "camera": camera_name,
        "timestamp": record.get("timestamp", ""),
        "start_time": record.get("start_time", ""),
        "end_time": record.get("end_time", ""),
        "start_point": record.get("start_point", ""),
        "end_point": record.get("end_point", ""),
    }
    digest = hashlib.sha1(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"det_{digest[:20]}"


def make_detection_base_name(output_dir: Path, timestamp: datetime, detection_id: str) -> str:
    stem = f"meteor_{timestamp.strftime('%Y%m%d_%H%M%S')}_{detection_id[4:12]}"
    candidate = stem
    suffix = 1
    while any(
        (output_dir / f"{candidate}{name_suffix}").exists()
        for name_suffix in (".mp4", ".mov", "_composite.jpg", "_composite_original.jpg")
    ):
        suffix += 1
        candidate = f"{stem}_{suffix:02d}"
    return candidate


def save_meteor_event(
    event: MeteorEvent,
    ring_buffer: RingBuffer,
    output_dir: Path,
    *,
    fps: float = 30,
    extract_clips: bool = True,
    clip_margin_before: float = 1.0,
    clip_margin_after: float = 1.0,
    composite_after: float = 1.0,
    overlay_text: Optional[str] = None,
    overlay_pos: Tuple[int, int] = (10, 30),
):
    """流星イベントを保存"""
    start = max(0, event.start_time - clip_margin_before)
    end = event.end_time + clip_margin_after
    frames = ring_buffer.get_range(start, end)

    if not frames:
        print(
            f"[WARN] イベント保存を中止: RingBufferに該当区間のフレームがありません "
            f"(start={start:.3f}, end={end:.3f})。イベントは記録されず消失します",
            flush=True,
        )
        return None

    record = event.to_dict()
    camera_name = output_dir.name
    detection_id = make_detection_id(camera_name, record)
    base_name = make_detection_base_name(output_dir, event.timestamp, detection_id)

    height, width = frames[0][1].shape[:2]

    clip_fps = estimate_fps_from_frames(frames, fallback_fps=fps)

    clip_path = None
    if extract_clips:
        clip_path = output_dir / f"{base_name}.mp4"
        ok = write_clip_with_fallback(clip_path, frames, fps=clip_fps, size=(width, height))
        if not ok:
            print(
                f"[WARN] 動画クリップの書き出しに失敗しました（ffmpeg実行エラー、"
                f"またはOpenCVフォールバックのエンコーダ初期化失敗）。イベントは"
                f"記録されず消失します: base_name={base_name}",
                flush=True,
            )
            return None

    composite_end = min(event.end_time + composite_after, end)
    event_frames = ring_buffer.get_range(event.start_time, composite_end)
    if event_frames:
        composite = event_frames[0][1].astype(np.float32)
        for _, f in event_frames[1:]:
            composite = np.maximum(composite, f.astype(np.float32))
        composite = np.clip(composite, 0, 255).astype(np.uint8)

        marked = composite.copy()
        cv2.line(marked, event.start_point, event.end_point, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(marked, event.start_point, 6, (0, 255, 0), 2)
        cv2.circle(marked, event.end_point, 6, (0, 0, 255), 2)

        if overlay_text:
            cv2.putText(
                marked,
                overlay_text,
                overlay_pos,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

        if not cv2.imwrite(str(output_dir / f"{base_name}_composite.jpg"), marked):
            print(
                f"[WARN] コンポジット画像の書き込みに失敗しました（ディスクフル等）: "
                f"base_name={base_name}",
                flush=True,
            )
        if not cv2.imwrite(str(output_dir / f"{base_name}_composite_original.jpg"), composite):
            print(
                f"[WARN] オリジナル合成画像の書き込みに失敗しました（ディスクフル等）: "
                f"base_name={base_name}",
                flush=True,
            )

    record["id"] = detection_id
    record["base_name"] = base_name
    if clip_path is not None:
        record["clip_path"] = clip_path.name
    composite_path = output_dir / f"{base_name}_composite.jpg"
    composite_original_path = output_dir / f"{base_name}_composite_original.jpg"
    if composite_path.exists():
        record["image_path"] = composite_path.name
    if composite_original_path.exists():
        record["composite_original_path"] = composite_original_path.name

    log_path = output_dir / "detections.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if extract_clips and clip_path is not None:
        print(f"  保存: {clip_path.name}")
    else:
        print(f"  保存: {base_name}_composite.jpg")
    return clip_path
