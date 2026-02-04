#!/usr/bin/env python3
"""
流星検出ダッシュボード
全カメラのプレビューを1ページで表示

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

from dashboard_config import CAMERAS, PORT
from dashboard_routes import (
    handle_changelog,
    handle_delete_detection,
    handle_detection_window,
    handle_detections,
    handle_detections_mtime,
    handle_camera_mask,
    handle_camera_stats,
    handle_camera_stream,
    handle_image,
    handle_index,
)


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == '/':
            handle_index(self)
            return
        if self.path.startswith('/detection_window'):
            handle_detection_window(self)
            return
        if self.path == '/changelog':
            handle_changelog(self)
            return
        if self.path == '/detections':
            handle_detections(self)
            return
        if self.path == '/detections_mtime':
            handle_detections_mtime(self)
            return
        if self.path.startswith('/camera_stats/'):
            handle_camera_stats(self)
            return
        if self.path.startswith('/camera_stream/'):
            handle_camera_stream(self)
            return
        if self.path.startswith('/camera_mask/'):
            handle_camera_mask(self)
            return
        if self.path.startswith('/image/'):
            handle_image(self)
            return

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        """DELETE リクエストを処理（検出結果の削除）"""
        if handle_delete_detection(self):
            return

        self.send_response(404)
        self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    print(f"Dashboard starting on port {PORT}")
    print(f"Cameras: {len(CAMERAS)}")
    for cam in CAMERAS:
        print(f"  - {cam['name']}: {cam['url']}")
    print()
    print(f"Open http://localhost:{PORT}/ in your browser")

    httpd = ThreadedHTTPServer(('0.0.0.0', PORT), DashboardHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.shutdown()


if __name__ == "__main__":
    main()
