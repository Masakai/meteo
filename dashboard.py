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
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import Flask, Response, jsonify, request

import dashboard_routes as routes
from dashboard_config import CAMERAS, PORT, VERSION
from dashboard_templates import render_dashboard_html, render_settings_html

logging.basicConfig(
    level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = Flask(__name__)
STREAM_PROXY_TIMEOUT_SEC = 20
STREAM_PROXY_RECONNECT_DELAY_SEC = 0.3


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


@app.get("/")
def index() -> Response:
    html = render_dashboard_html(CAMERAS, VERSION, routes._SERVER_START_TIME)
    response = Response(html, content_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/settings")
def settings() -> Response:
    html = render_settings_html(CAMERAS, VERSION)
    response = Response(html, content_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/detection_window")
def detection_window() -> Response:
    return _dispatch(routes.handle_detection_window)


@app.get("/changelog")
def changelog() -> Response:
    changelog_path = Path(__file__).parent / "CHANGELOG.md"
    if not changelog_path.exists():
        return Response("CHANGELOG.md not found", content_type="text/plain; charset=utf-8")
    return Response(changelog_path.read_text(encoding="utf-8"), content_type="text/plain; charset=utf-8")


@app.get("/detections")
def detections() -> Response:
    snapshot = routes.get_detection_cache_snapshot()
    response = jsonify({"total": snapshot["total"], "recent": snapshot["recent"]})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.get("/detections_mtime")
def detections_mtime() -> Response:
    snapshot = routes.get_detection_cache_snapshot()
    response = jsonify({"mtime": snapshot["mtime"]})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.get("/dashboard_stats")
def dashboard_stats() -> Response:
    snapshot = routes.get_dashboard_cpu_snapshot(refresh=True)
    response = jsonify(snapshot)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


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


@app.get("/camera_stream/<int:camera_index>")
def camera_stream(camera_index: int) -> Response:
    try:
        cam = CAMERAS[camera_index]
    except IndexError:
        return Response(status=503)

    target_url = routes._camera_url_for_proxy(cam["url"], camera_index) + "/stream"
    req = Request(target_url)

    try:
        upstream = urlopen(req, timeout=STREAM_PROXY_TIMEOUT_SEC)
        first_chunk = upstream.read(routes._CAMERA_STREAM_CHUNK_SIZE)
        if not first_chunk:
            upstream.close()
            return Response(status=503)
    except (TimeoutError, ValueError):
        return Response(status=503)
    except Exception:
        return Response(status=500)

    content_type = "multipart/x-mixed-replace; boundary=frame"

    def generate():
        current_upstream = upstream
        current_first_chunk = first_chunk
        try:
            while True:
                first_chunk_sent = False
                try:
                    if current_first_chunk:
                        first_chunk_sent = True
                        yield current_first_chunk
                        current_first_chunk = b""

                    while True:
                        chunk = current_upstream.read(routes._CAMERA_STREAM_CHUNK_SIZE)
                        if not chunk:
                            raise TimeoutError("stream ended")
                        first_chunk_sent = True
                        yield chunk
                except GeneratorExit:
                    break
                except Exception:
                    if first_chunk_sent:
                        time.sleep(STREAM_PROXY_RECONNECT_DELAY_SEC)

                    try:
                        if current_upstream is not None:
                            current_upstream.close()
                    except Exception:
                        pass
                    current_upstream = None
                    current_first_chunk = b""

                    while True:
                        try:
                            current_upstream = urlopen(req, timeout=STREAM_PROXY_TIMEOUT_SEC)
                            current_first_chunk = current_upstream.read(routes._CAMERA_STREAM_CHUNK_SIZE)
                            if not current_first_chunk:
                                raise TimeoutError("empty first chunk")
                            break
                        except GeneratorExit:
                            raise
                        except Exception:
                            try:
                                if current_upstream is not None:
                                    current_upstream.close()
                            except Exception:
                                pass
                            current_upstream = None
                            current_first_chunk = b""
                            time.sleep(STREAM_PROXY_RECONNECT_DELAY_SEC)
        finally:
            if current_upstream is not None:
                try:
                    current_upstream.close()
                except Exception:
                    pass

    response = Response(generate(), content_type=content_type)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


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
