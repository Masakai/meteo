"""Camera-related dashboard handlers."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse

logger = logging.getLogger(__name__)

# YouTube配信中のffmpegサブプロセス {camera_index: subprocess.Popen}
_youtube_processes: dict[int, subprocess.Popen] = {}
# 自動再接続ループの継続フラグ {camera_index: bool}
_youtube_active: dict[int, bool] = {}
# 自動再接続ループのスレッド {camera_index: threading.Thread}
_youtube_threads: dict[int, threading.Thread] = {}


def parse_camera_index(path: str, camera_count: int) -> int:
    parsed_path = urlparse(path).path
    camera_index = int(parsed_path.rstrip("/").split("/")[-1])
    if camera_index < 0 or camera_index >= camera_count:
        raise ValueError(f"camera index out of range: {camera_index}")
    return camera_index


def camera_url_for_proxy(raw_url: str, in_docker: bool, camera_index: int | None = None) -> str:
    parsed = urlparse(raw_url)
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1"):
        if in_docker and camera_index is not None:
            return f"{parsed.scheme}://camera{camera_index + 1}:8080"
        netloc = "host.docker.internal"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return raw_url


def handle_camera_snapshot(handler, cameras, in_docker, parse_index, request_cls, urlopen_fn):
    if not handler.path.startswith("/camera_snapshot/"):
        return False

    parsed = urlparse(handler.path)
    try:
        camera_index = parse_index(parsed.path)
        cam = cameras[camera_index]
        target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + "/snapshot"
        req = request_cls(target_url)
        with urlopen_fn(req, timeout=5) as response:
            payload = response.read()

        query = parse_qs(parsed.query)
        should_download = query.get("download", ["0"])[0] in ("1", "true", "yes")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if (c.isalnum() and c.isascii()) else "_" for c in cam["name"]).strip("_") or f"camera{camera_index+1}"
        filename = f"snapshot_{safe_name}_{timestamp}.jpg"

        handler.send_response(200)
        handler.send_header("Content-type", "image/jpeg")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        if should_download:
            handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError):
        handler.send_response(503)
        handler.end_headers()
        return True
    except Exception:
        handler.send_response(500)
        handler.end_headers()
        return True


def _proxy_camera_post(
    handler,
    camera_path,
    ok_status,
    cameras,
    in_docker,
    parse_index,
    request_cls,
    urlopen_fn,
):
    try:
        camera_index = parse_index(handler.path)
        cam = cameras[camera_index]
        target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + camera_path
        req = request_cls(target_url, method="POST")
        with urlopen_fn(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(ok_status)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def _read_handler_body(handler) -> bytes:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except Exception:
        length = 0
    return handler.rfile.read(length) if length > 0 else b""


def _proxy_camera_json(
    handler,
    *,
    camera_index: int,
    target_path: str,
    method: str,
    cameras,
    in_docker,
    request_cls,
    urlopen_fn,
    body: bytes = b"",
    timeout: float = 10,
):
    cam = cameras[camera_index]
    target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + target_path
    headers = {"Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    req = request_cls(target_url, data=body if body else None, headers=headers, method=method)
    with urlopen_fn(req, timeout=timeout) as response:
        payload = response.read()
    return payload


def proxy_camera_recording_request(
    handler,
    *,
    target_path: str,
    method: str,
    cameras,
    in_docker,
    parse_index,
    request_cls,
    urlopen_fn,
    timeout: float = 10,
):
    parsed = urlparse(handler.path)
    try:
        camera_index = parse_index(parsed.path)
        body = _read_handler_body(handler) if method.upper() != "GET" else b""
        payload = _proxy_camera_json(
            handler,
            camera_index=camera_index,
            target_path=target_path,
            method=method.upper(),
            cameras=cameras,
            in_docker=in_docker,
            request_cls=request_cls,
            urlopen_fn=urlopen_fn,
            body=body,
            timeout=timeout,
        )
        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
    except HTTPError as e:
        payload = e.read() if hasattr(e, "read") else b""
        handler.send_response(e.code)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(payload or json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def handle_camera_mask(handler, *args):
    if not handler.path.startswith("/camera_mask/"):
        return False
    return _proxy_camera_post(handler, "/update_mask", 200, *args)


def handle_camera_mask_confirm(handler, *args):
    if not handler.path.startswith("/camera_mask_confirm/"):
        return False
    return _proxy_camera_post(handler, "/confirm_mask_update", 200, *args)


def handle_camera_mask_discard(handler, *args):
    if not handler.path.startswith("/camera_mask_discard/"):
        return False
    return _proxy_camera_post(handler, "/discard_mask_update", 200, *args)


def handle_camera_restart(handler, cameras, in_docker, parse_index, request_cls, urlopen_fn):
    if not handler.path.startswith("/camera_restart/"):
        return False

    try:
        camera_index = parse_index(handler.path)
        cam = cameras[camera_index]
        target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + "/restart"
        req = request_cls(target_url, method="POST")
        with urlopen_fn(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(202)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def handle_camera_mask_image(handler, cameras, in_docker, parse_index, request_cls, urlopen_fn):
    if not handler.path.startswith("/camera_mask_image/"):
        return False

    parsed = urlparse(handler.path)
    try:
        camera_index = parse_index(parsed.path)
        cam = cameras[camera_index]
        target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + "/mask"
        if parsed.query:
            target_url += "?" + parsed.query
        req = request_cls(target_url)
        with urlopen_fn(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(200)
        handler.send_header("Content-type", "image/png")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except HTTPError as e:
        handler.send_response(404 if e.code == 404 else 503)
        handler.end_headers()
        return True
    except (ValueError, URLError, TimeoutError):
        handler.send_response(503)
        handler.end_headers()
        return True
    except Exception:
        handler.send_response(500)
        handler.end_headers()
        return True


def handle_camera_settings_current(handler, cameras, camera_stats_target, request_cls, urlopen_fn):
    if handler.path != "/camera_settings/current":
        return False

    results = []
    first_settings = {}

    for camera_index, cam in enumerate(cameras):
        target_url = camera_stats_target(camera_index)
        try:
            req = request_cls(target_url, headers={"Accept": "application/json"})
            with urlopen_fn(req, timeout=5) as response:
                payload = response.read()
            data = json.loads(payload.decode("utf-8")) if payload else {}
            settings = data.get("settings", {}) if isinstance(data, dict) else {}
            if not first_settings and isinstance(settings, dict) and settings:
                first_settings = settings
            results.append({
                "camera": cam["name"],
                "success": True,
                "settings": settings,
            })
        except Exception as e:
            results.append({
                "camera": cam["name"],
                "success": False,
                "error": str(e),
            })

    ok_count = sum(1 for item in results if item.get("success"))
    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()
    handler.wfile.write(
        json.dumps(
            {
                "success": ok_count > 0,
                "settings": first_settings,
                "results": results,
                "ok_count": ok_count,
                "total": len(cameras),
            }
        ).encode("utf-8")
    )
    return True


def handle_camera_settings_apply_all(handler, cameras, camera_apply_settings_target, request_cls, urlopen_fn):
    if handler.path != "/camera_settings/apply_all":
        return False

    try:
        length = int(handler.headers.get("Content-Length", "0"))
        raw_body = handler.rfile.read(length)
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be object")
    except Exception as e:
        handler.send_response(400)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": f"invalid payload: {e}"}).encode("utf-8"))
        return True

    results = []
    applied_count = 0
    request_body = json.dumps(payload).encode("utf-8")
    for camera_index, cam in enumerate(cameras):
        target_url = camera_apply_settings_target(camera_index)
        try:
            req = request_cls(
                target_url,
                data=request_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen_fn(req, timeout=8) as response:
                resp_payload = response.read()
            data = json.loads(resp_payload.decode("utf-8")) if resp_payload else {}
            success = bool(data.get("success", False))
            if success:
                applied_count += 1
            results.append({
                "camera": cam["name"],
                "success": success,
                "response": data,
            })
        except Exception as e:
            results.append({
                "camera": cam["name"],
                "success": False,
                "error": str(e),
            })

    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()
    handler.wfile.write(
        json.dumps(
            {
                "success": applied_count > 0,
                "applied_count": applied_count,
                "total": len(cameras),
                "results": results,
            }
        ).encode("utf-8")
    )
    return True


def _youtube_rtmp_dst(youtube_key: str) -> str:
    return f"rtmp://a.rtmp.youtube.com/live2/{youtube_key}"


def _youtube_json_response(handler, data: dict, status: int = 200) -> bool:
    handler.send_response(status)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(json.dumps(data).encode("utf-8"))
    return True


_RECONNECT_DELAY = 15  # 切断後の再接続待機秒数
_qsv_available_cache: bool | None = None  # QSV利用可否キャッシュ


def _check_qsv_available() -> bool:
    """Intel QSVハードウェアエンコードが使用可能か確認する（初回のみ実行）"""
    global _qsv_available_cache
    if _qsv_available_cache is not None:
        return _qsv_available_cache
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner",
                "-init_hw_device", "qsv=qsv:hw",
                "-f", "lavfi", "-i", "nullsrc=s=64x64",
                "-c:v", "h264_qsv", "-t", "0.1", "-f", "null", "-",
            ],
            capture_output=True,
            timeout=10,
        )
        _qsv_available_cache = result.returncode == 0
    except Exception:
        _qsv_available_cache = False
    logger.info("QSV available: %s", _qsv_available_cache)
    return _qsv_available_cache


def _youtube_loop(camera_index: int, cmd: list, ffmpeg_log_path: str | None) -> None:
    """ffmpegを自動再接続ループで実行するバックグラウンドスレッド"""
    while _youtube_active.get(camera_index, False):
        try:
            ffmpeg_log_fh = None
            if ffmpeg_log_path:
                try:
                    os.makedirs(os.path.dirname(ffmpeg_log_path), exist_ok=True)
                    ffmpeg_log_fh = open(ffmpeg_log_path, "ab")
                except Exception:
                    pass
            proc = subprocess.Popen(
                cmd,
                stdout=ffmpeg_log_fh or subprocess.DEVNULL,
                stderr=ffmpeg_log_fh or subprocess.DEVNULL,
            )
            _youtube_processes[camera_index] = proc
            logger.info("youtube camera%d started pid=%d", camera_index + 1, proc.pid)
            proc.wait()
            if ffmpeg_log_fh:
                ffmpeg_log_fh.close()
            _youtube_processes.pop(camera_index, None)
            logger.info("youtube camera%d ffmpeg exited (rc=%d)", camera_index + 1, proc.returncode)
        except Exception as exc:
            logger.error("youtube camera%d error: %s", camera_index + 1, exc)

        if not _youtube_active.get(camera_index, False):
            break
        logger.info("youtube camera%d reconnecting in %ds...", camera_index + 1, _RECONNECT_DELAY)
        time.sleep(_RECONNECT_DELAY)

    logger.info("youtube camera%d loop ended", camera_index + 1)


def handle_youtube_start(handler, cameras, go2rtc_api_url, parse_index, request_cls, urlopen_fn):
    """YouTube Live配信を開始する（ffmpegサブプロセスで直接RTMP送信・自動再接続）"""
    try:
        camera_index = parse_index(handler.path)
    except (ValueError, IndexError):
        return _youtube_json_response(handler, {"success": False, "error": "invalid camera index"}, 400)

    cam = cameras[camera_index]
    youtube_key = cam.get("youtube_key", "")
    if not youtube_key:
        return _youtube_json_response(handler, {"success": False, "error": "YouTube key not configured"}, 400)

    # 既存ループがあれば先に停止
    _stop_youtube_process(camera_index)

    rtsp_src = f"rtsp://go2rtc:8554/camera{camera_index + 1}"
    rtmp_dst = _youtube_rtmp_dst(youtube_key)

    if _check_qsv_available():
        # Intel QSVハードウェアエンコード（N100 / i5 Gen12以降）
        logger.info("youtube camera%d using h264_qsv", camera_index + 1)
        video_opts = [
            "-c:v", "h264_qsv", "-b:v", "2000k", "-maxrate", "2000k",
            "-g", "40", "-bf", "0",
        ]
    else:
        # ソフトウェアエンコード（Apple Silicon / QSV非対応環境）
        logger.info("youtube camera%d QSV unavailable, using libx264 ultrafast", camera_index + 1)
        video_opts = [
            "-vf", "scale=1280:720",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-b:v", "2000k", "-maxrate", "2000k", "-bufsize", "4000k",
            "-g", "40", "-bf", "0", "-pix_fmt", "yuv420p",
        ]

    cmd = [
        "ffmpeg", "-re",
        "-rtsp_transport", "tcp",
        "-thread_queue_size", "4096",
        "-i", rtsp_src,
        *video_opts,
        "-af", "aresample=async=1,volume=0",
        "-c:a", "aac", "-ar", "44100", "-b:a", "32k",
        "-f", "flv", rtmp_dst,
    ]

    log_path = os.environ.get("LOG_FILE", "")
    if log_path:
        ffmpeg_log_path = os.path.join(os.path.dirname(log_path), f"ffmpeg_youtube_{camera_index + 1}.log")
    else:
        ffmpeg_log_path = None

    _youtube_active[camera_index] = True
    thread = threading.Thread(
        target=_youtube_loop,
        args=(camera_index, cmd, ffmpeg_log_path),
        daemon=True,
        name=f"youtube-{camera_index + 1}",
    )
    _youtube_threads[camera_index] = thread
    thread.start()
    logger.info("youtube_start camera%d loop started", camera_index + 1)
    return _youtube_json_response(handler, {"success": True})


def _stop_youtube_process(camera_index: int) -> None:
    """自動再接続ループを停止しffmpegプロセスを終了する"""
    _youtube_active[camera_index] = False
    proc = _youtube_processes.pop(camera_index, None)
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
            logger.info("youtube_stop camera%d pid=%d terminated", camera_index + 1, proc.pid)
        except Exception:
            proc.kill()
    thread = _youtube_threads.pop(camera_index, None)
    if thread is not None:
        thread.join(timeout=10)


def handle_youtube_stop(handler, cameras, go2rtc_api_url, parse_index, request_cls, urlopen_fn):
    """YouTube Live配信を停止する"""
    try:
        camera_index = parse_index(handler.path)
    except (ValueError, IndexError):
        return _youtube_json_response(handler, {"success": False, "error": "invalid camera index"}, 400)

    cam = cameras[camera_index]
    if not cam.get("youtube_key"):
        return _youtube_json_response(handler, {"success": False, "error": "YouTube key not configured"}, 400)

    _stop_youtube_process(camera_index)
    return _youtube_json_response(handler, {"success": True})


def handle_youtube_status(handler, cameras, go2rtc_api_url, parse_index, request_cls, urlopen_fn):
    """YouTube Live配信の状態を取得する"""
    try:
        camera_index = parse_index(handler.path)
    except (ValueError, IndexError):
        return _youtube_json_response(handler, {"streaming": False, "error": "invalid camera index"}, 400)

    cam = cameras[camera_index]
    if not cam.get("youtube_key"):
        return _youtube_json_response(handler, {"streaming": False})

    thread = _youtube_threads.get(camera_index)
    streaming = (
        _youtube_active.get(camera_index, False)
        and thread is not None
        and thread.is_alive()
    )
    return _youtube_json_response(handler, {"streaming": streaming})
