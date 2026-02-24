"""
Dashboard configuration and environment setup.
"""

import os

VERSION = "1.19.0"

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
        CAMERAS.append({"name": name, "url": url})

# デフォルト設定
if not CAMERAS:
    CAMERAS = [
        {"name": "camera1_10.0.1.25", "url": "http://camera1:8080"},
        {"name": "camera2_10.0.1.3", "url": "http://camera2:8080"},
        {"name": "camera3_10.0.1.11", "url": "http://camera3:8080"},
    ]

PORT = int(os.environ.get("PORT", 8080))
_default_detections = "/output"
_base_dir = os.path.dirname(os.path.abspath(__file__))
_local_detections = os.path.join(_base_dir, "detections")
if os.path.isdir(_local_detections):
    _default_detections = _local_detections
DETECTIONS_DIR = os.environ.get("DETECTIONS_DIR", _default_detections)
