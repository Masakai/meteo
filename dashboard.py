#!/usr/bin/env python3
"""
流星検出ダッシュボード (Flask 版)
全カメラのプレビューを1ページで表示

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

from __future__ import annotations

import atexit
import logging
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

from flask import Flask, Response, jsonify, request

import dashboard_routes as routes
from dashboard_config import CAMERAS, PORT, VERSION
from dashboard_templates import render_dashboard_html, render_settings_html

logging.basicConfig(
    level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

class HandlerAdapter:
    """BaseHTTPRequestHandler 互換の最小アダプタ。"""

    def __init__(self, path: str):
        self.path = path
        self.headers = request.headers
        self.rfile = BytesIO(request.get_data(cache=True))
        self.wfile = BytesIO()
        self._status = 200
        self._status_set = False
        self._headers: list[tuple[str, str]] = []

    def send_response(self, code: int):
        self._status = int(code)
        self._status_set = True

    def send_header(self, key: str, value: str):
        self._headers.append((key, value))

    def end_headers(self):
        return None

    def to_response(self, default_status: int = 404) -> Response:
        status = self._status if (self._status_set or self._headers or self.wfile.tell() > 0) else default_status
        body = self.wfile.getvalue()
        return Response(body, status=status, headers=self._headers)



def _request_path_with_query() -> str:
    query = request.query_string.decode("utf-8")
    if query:
        return f"{request.path}?{query}"
    return request.path



def _dispatch(handler_func, path: str | None = None) -> Response:
    adapter = HandlerAdapter(path or _request_path_with_query())
    result = handler_func(adapter)
    if result is False:
        return Response(status=404)
    return adapter.to_response()


def _apply_no_cache_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _camera_embed_info(camera_index: int) -> dict | None:
    if camera_index < 0 or camera_index >= len(CAMERAS):
        return None
    cam = CAMERAS[camera_index]
    stream_kind = str(cam.get("stream_kind", "mjpeg")).lower()
    if stream_kind != "webrtc":
        return None
    stream_url = str(cam.get("stream_url") or "").strip()
    if not stream_url:
        return None
    parsed = urlparse(stream_url)
    src = parse_qs(parsed.query).get("src", [""])[0].strip()
    if not src:
        return None
    http_base = f"{parsed.scheme}://{parsed.netloc}"
    proxy_http_base = http_base
    hostname = parsed.hostname or ""
    if hostname in {"localhost", "127.0.0.1", "::1"} and os.path.exists("/.dockerenv"):
        proxy_host = "go2rtc"
        proxy_port = parsed.port or 1984
        proxy_http_base = f"{parsed.scheme}://{proxy_host}:{proxy_port}"
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    return {
        "camera": cam,
        "http_base": http_base,
        "proxy_http_base": proxy_http_base,
        "ws_scheme": ws_scheme,
        "ws_port": parsed.port or (443 if parsed.scheme == "https" else 80),
        "src": src,
    }


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @app.before_request
    def _ensure_background_monitors_started() -> None:
        _start_monitors_once()

    @app.get("/health")
    def health() -> Response:
        response = jsonify(
            {
                "status": "ok",
                "version": VERSION,
                "camera_count": len(CAMERAS),
            }
        )
        return _apply_no_cache_headers(response)

    @app.get("/")
    def index() -> Response:
        html = render_dashboard_html(CAMERAS, VERSION, routes._SERVER_START_TIME, page_mode="detections")
        return _apply_no_cache_headers(Response(html, content_type="text/html; charset=utf-8"))

    @app.get("/cameras")
    def cameras_page() -> Response:
        html = render_dashboard_html(CAMERAS, VERSION, routes._SERVER_START_TIME, page_mode="cameras")
        return _apply_no_cache_headers(Response(html, content_type="text/html; charset=utf-8"))

    @app.get("/settings")
    def settings() -> Response:
        html = render_settings_html(CAMERAS, VERSION)
        return _apply_no_cache_headers(Response(html, content_type="text/html; charset=utf-8"))

    @app.get("/detection_window")
    def detection_window() -> Response:
        return _dispatch(routes.handle_detection_window)

    @app.get("/changelog")
    def changelog() -> Response:
        changelog_path = Path(__file__).parent / "CHANGELOG.md"
        if not changelog_path.exists():
            return Response("CHANGELOG.md not found", content_type="text/plain; charset=utf-8")
        return _apply_no_cache_headers(
            Response(changelog_path.read_text(encoding="utf-8"), content_type="text/plain; charset=utf-8")
        )

    @app.get("/detections")
    def detections() -> Response:
        snapshot = routes.get_detection_cache_snapshot()
        response = jsonify({"total": snapshot["total"], "recent": snapshot["recent"]})
        return _apply_no_cache_headers(response)

    @app.get("/detections_mtime")
    def detections_mtime() -> Response:
        snapshot = routes.get_detection_cache_snapshot()
        response = jsonify({"mtime": snapshot["mtime"]})
        return _apply_no_cache_headers(response)

    @app.get("/dashboard_stats")
    def dashboard_stats() -> Response:
        snapshot = routes.get_dashboard_cpu_snapshot(refresh=True)
        response = jsonify(snapshot)
        return _apply_no_cache_headers(response)

    @app.get("/camera_stats/<int:camera_index>")
    def camera_stats(camera_index: int) -> Response:
        return _dispatch(routes.handle_camera_stats, path=f"/camera_stats/{camera_index}")

    @app.get("/camera_recording_status/<int:camera_index>")
    def camera_recording_status(camera_index: int) -> Response:
        return _dispatch(routes.handle_camera_recording_status, path=f"/camera_recording_status/{camera_index}")

    @app.post("/camera_recording_schedule/<int:camera_index>")
    def camera_recording_schedule(camera_index: int) -> Response:
        return _dispatch(routes.handle_camera_recording_schedule, path=f"/camera_recording_schedule/{camera_index}")

    @app.post("/camera_recording_stop/<int:camera_index>")
    def camera_recording_stop(camera_index: int) -> Response:
        return _dispatch(routes.handle_camera_recording_stop, path=f"/camera_recording_stop/{camera_index}")

    @app.get("/camera_settings/current")
    def camera_settings_current() -> Response:
        return _dispatch(routes.handle_camera_settings_current, path="/camera_settings/current")

    @app.post("/camera_settings/apply_all")
    def camera_settings_apply_all() -> Response:
        return _dispatch(routes.handle_camera_settings_apply_all, path="/camera_settings/apply_all")

    @app.route("/camera_mask/<int:camera_index>", methods=["GET", "POST"])
    def camera_mask(camera_index: int) -> Response:
        return _dispatch(routes.handle_camera_mask, path=f"/camera_mask/{camera_index}")

    @app.post("/camera_mask_confirm/<int:camera_index>")
    def camera_mask_confirm(camera_index: int) -> Response:
        return _dispatch(routes.handle_camera_mask_confirm, path=f"/camera_mask_confirm/{camera_index}")

    @app.post("/camera_mask_discard/<int:camera_index>")
    def camera_mask_discard(camera_index: int) -> Response:
        return _dispatch(routes.handle_camera_mask_discard, path=f"/camera_mask_discard/{camera_index}")

    @app.get("/camera_mask_image/<int:camera_index>")
    def camera_mask_image(camera_index: int) -> Response:
        query = request.query_string.decode("utf-8")
        path = f"/camera_mask_image/{camera_index}"
        if query:
            path = f"{path}?{query}"
        return _dispatch(routes.handle_camera_mask_image, path=path)

    @app.post("/camera_restart/<int:camera_index>")
    def camera_restart(camera_index: int) -> Response:
        return _dispatch(routes.handle_camera_restart, path=f"/camera_restart/{camera_index}")

    @app.get("/camera_snapshot/<int:camera_index>")
    def camera_snapshot(camera_index: int) -> Response:
        query = request.query_string.decode("utf-8")
        path = f"/camera_snapshot/{camera_index}"
        if query:
            path = f"{path}?{query}"
        return _dispatch(routes.handle_camera_snapshot, path=path)

    @app.get("/camera_embed/<int:camera_index>")
    def camera_embed(camera_index: int) -> Response:
        info = _camera_embed_info(camera_index)
        if info is None:
            return Response("camera embed not available", status=404, content_type="text/plain; charset=utf-8")
        display_name = info["camera"].get("display_name", info["camera"]["name"])
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{display_name}</title>
    <style>
        html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            background: #000;
            overflow: hidden;
        }}
        video-stream {{
            display: block;
            width: 100%;
            height: 100%;
            background: #000;
        }}
        video-stream video {{
            width: 100%;
            height: 100%;
            object-fit: contain;
        }}
        video-stream .info {{
            padding: 10px 14px;
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 12px;
            color: rgba(255, 255, 255, 0.85);
        }}
    </style>
</head>
<body>
    <video-stream id="player"></video-stream>
    <script type="module">
        import '/go2rtc_asset/video-stream.js';
        const player = document.getElementById('player');
        const sourceName = {info["src"]!r};
        const go2rtcPort = {info["ws_port"]!r};
        const wsScheme = {info["ws_scheme"]!r};
        const hostname = window.location.hostname.includes(':')
            ? `[${{window.location.hostname}}]`
            : window.location.hostname;
        const wsOrigin = `${{wsScheme}}://${{hostname}}:${{go2rtcPort}}`;
        const wsUrl = new URL('/api/ws', wsOrigin);
        wsUrl.searchParams.set('src', sourceName);
        player.mode = 'webrtc,mse,hls,mjpeg';
        player.media = 'video';
        player.background = true;
        player.visibilityCheck = false;
        player.src = wsUrl.toString();
    </script>
</body>
</html>"""
        return _apply_no_cache_headers(Response(html, content_type="text/html; charset=utf-8"))

    @app.get("/go2rtc_asset/<path:asset_name>")
    def go2rtc_asset(asset_name: str) -> Response:
        if asset_name not in {"video-stream.js", "video-rtc.js"}:
            return Response("not found", status=404, content_type="text/plain; charset=utf-8")
        info = next((_camera_embed_info(i) for i in range(len(CAMERAS))), None)
        if info is None:
            return Response("go2rtc asset unavailable", status=503, content_type="text/plain; charset=utf-8")
        target_url = f"{info['proxy_http_base']}/{asset_name}"
        req = Request(target_url, headers={"Accept": "application/javascript, text/javascript, */*"})
        with urlopen(req, timeout=5) as upstream:
            payload = upstream.read()
        return _apply_no_cache_headers(Response(payload, content_type="application/javascript; charset=utf-8"))

    @app.get("/image/<path:subpath>")
    def image(subpath: str) -> Response:
        query = request.query_string.decode("utf-8")
        encoded_subpath = "/".join(quote(p, safe="") for p in subpath.split("/"))
        path = f"/image/{encoded_subpath}"
        if query:
            path = f"{path}?{query}"
        return _dispatch(routes.handle_image, path=path)

    @app.delete("/detection/<path:subpath>")
    def delete_detection(subpath: str) -> Response:
        encoded_subpath = "/".join(quote(p, safe="") for p in subpath.split("/"))
        return _dispatch(routes.handle_delete_detection, path=f"/detection/{encoded_subpath}")

    @app.delete("/manual_recording/<path:subpath>")
    def delete_manual_recording(subpath: str) -> Response:
        encoded_subpath = "/".join(quote(p, safe="") for p in subpath.split("/"))
        return _dispatch(routes.handle_delete_manual_recording, path=f"/manual_recording/{encoded_subpath}")

    @app.post("/detection_label")
    def detection_label() -> Response:
        return _dispatch(routes.handle_set_detection_label, path="/detection_label")

    @app.post("/bulk_delete_non_meteor/<path:camera_name>")
    def bulk_delete_non_meteor(camera_name: str) -> Response:
        encoded_name = quote(camera_name, safe="")
        return _dispatch(routes.handle_bulk_delete_non_meteor, path=f"/bulk_delete_non_meteor/{encoded_name}")

    return app


_started = False


def _start_monitors_once():
    global _started
    if _started:
        return
    routes.start_detection_monitor()
    routes.start_camera_monitor()
    _started = True



def _stop_monitors():
    routes.stop_camera_monitor()
    routes.stop_detection_monitor()


atexit.register(_stop_monitors)


app = create_app()


def main():
    print(f"Dashboard (Flask) starting on port {PORT}")
    print(f"Cameras: {len(CAMERAS)}")
    for cam in CAMERAS:
        print(f"  - {cam['name']}: {cam['url']}")
    print()
    print(f"Open http://localhost:{PORT}/ in your browser")

    _start_monitors_once()

    try:
        app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
    finally:
        _stop_monitors()


if __name__ == "__main__":
    main()
