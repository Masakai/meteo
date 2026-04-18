"""
Dashboard configuration and environment setup.
"""

import os

VERSION = "3.11.2"

# 検出時間の取得用
try:
    from astro_utils import get_detection_window
except ImportError:
    get_detection_window = None

# 環境変数からカメラ設定を取得
CAMERAS = []
for i in range(1, 10):
    name = os.environ.get(f"CAMERA{i}_NAME")
    url = os.environ.get(f"CAMERA{i}_URL")
    if name and url:
        display_name = os.environ.get(f"CAMERA{i}_NAME_DISPLAY", name)
        stream_url = os.environ.get(f"CAMERA{i}_STREAM_URL", "").strip() or url
        stream_kind = os.environ.get(f"CAMERA{i}_STREAM_KIND", "webrtc").strip().lower() or "webrtc"
        if stream_kind not in ("mjpeg", "webrtc"):
            stream_kind = "webrtc"
        cam = {
            "name": name,
            "url": url,
            "display_name": display_name,
            "stream_url": stream_url,
            "stream_kind": stream_kind,
        }
        youtube_key = os.environ.get(f"CAMERA{i}_YOUTUBE_KEY", "").strip()
        if youtube_key:
            cam["youtube_key"] = youtube_key
            cam["rtsp_url"] = os.environ.get(f"CAMERA{i}_RTSP_URL", "").strip()
        CAMERAS.append(cam)

# デフォルト設定
if not CAMERAS:
    CAMERAS = [
        {"name": "camera1", "url": "http://camera1:8080", "stream_url": "http://camera1:8080", "stream_kind": "webrtc"},
        {"name": "camera2", "url": "http://camera2:8080", "stream_url": "http://camera2:8080", "stream_kind": "webrtc"},
        {"name": "camera3", "url": "http://camera3:8080", "stream_url": "http://camera3:8080", "stream_kind": "webrtc"},
    ]

# go2rtc API URL (Docker内ではホスト名go2rtcを使用)
_go2rtc_url = os.environ.get("GO2RTC_API_URL", "http://localhost:1984")
if os.path.exists("/.dockerenv") and "localhost" in _go2rtc_url:
    from urllib.parse import urlparse as _urlparse
    _parsed = _urlparse(_go2rtc_url)
    if (_parsed.hostname or "") in ("localhost", "127.0.0.1", "::1"):
        _go2rtc_url = f"{_parsed.scheme}://go2rtc:{_parsed.port or 1984}"
GO2RTC_API_URL = _go2rtc_url

PORT = int(os.environ.get("PORT", 8080))
_default_detections = "/output"
_base_dir = os.path.dirname(os.path.abspath(__file__))
_local_detections = os.path.join(_base_dir, "detections")
if os.path.isdir(_local_detections):
    _default_detections = _local_detections
DETECTIONS_DIR = os.environ.get("DETECTIONS_DIR", _default_detections)
