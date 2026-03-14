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
from urllib.parse import quote

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
