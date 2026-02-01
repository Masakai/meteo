#!/usr/bin/env python3
"""
流星検出ダッシュボード
全カメラのプレビューを1ページで表示
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
import json
import os
from pathlib import Path
from datetime import datetime

# 環境変数からカメラ設定を取得
CAMERAS = []
for i in range(1, 10):
    name = os.environ.get(f'CAMERA{i}_NAME')
    url = os.environ.get(f'CAMERA{i}_URL')
    if name and url:
        CAMERAS.append({'name': name, 'url': url})

# デフォルト設定
if not CAMERAS:
    CAMERAS = [
        {'name': 'camera1_10.0.1.25', 'url': 'http://camera1:8080'},
        {'name': 'camera2_10.0.1.3', 'url': 'http://camera2:8080'},
        {'name': 'camera3_10.0.1.11', 'url': 'http://camera3:8080'},
    ]

PORT = int(os.environ.get('PORT', 8080))
DETECTIONS_DIR = os.environ.get('DETECTIONS_DIR', '/output')


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()

            # カメラグリッドを生成
            camera_cards = ""
            for i, cam in enumerate(CAMERAS):
                camera_cards += f'''
                <div class="camera-card">
                    <div class="camera-header">
                        <span class="camera-name">{cam['name']}</span>
                        <span class="camera-status" id="status{i}">●</span>
                    </div>
                    <div class="camera-video">
                        <img src="{cam['url']}/stream" alt="{cam['name']}"
                             onerror="this.style.display='none'; document.getElementById('error{i}').style.display='flex';">
                        <div class="camera-error" id="error{i}">
                            <span>接続中...</span>
                        </div>
                    </div>
                    <div class="camera-stats">
                        <span>検出: <b id="count{i}">-</b></span>
                    </div>
                </div>
                '''

            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Meteor Detection Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }}
        .header {{
            text-align: center;
            padding: 20px 0 30px;
        }}
        .header h1 {{
            color: #00d4ff;
            font-size: 2em;
            margin-bottom: 10px;
        }}
        .header .subtitle {{
            color: #888;
            font-size: 0.9em;
        }}
        .stats-bar {{
            display: flex;
            justify-content: center;
            gap: 40px;
            margin-bottom: 30px;
            padding: 15px;
            background: rgba(0,212,255,0.1);
            border-radius: 10px;
        }}
        .stats-bar .stat {{
            text-align: center;
        }}
        .stats-bar .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #00ff88;
        }}
        .stats-bar .stat-label {{
            color: #888;
            font-size: 0.85em;
        }}
        .camera-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            max-width: 1800px;
            margin: 0 auto;
        }}
        .camera-card {{
            background: #1e2a4a;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid #2a3f6f;
        }}
        .camera-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 15px;
            background: #16213e;
            border-bottom: 1px solid #2a3f6f;
        }}
        .camera-name {{
            font-weight: bold;
            color: #00d4ff;
        }}
        .camera-status {{
            color: #00ff88;
            font-size: 0.8em;
        }}
        .camera-status.offline {{
            color: #ff4444;
        }}
        .camera-video {{
            position: relative;
            background: #000;
            aspect-ratio: 16/9;
        }}
        .camera-video img {{
            width: 100%;
            height: 100%;
            object-fit: contain;
        }}
        .camera-error {{
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            display: none;
            align-items: center;
            justify-content: center;
            background: rgba(0,0,0,0.8);
            color: #888;
        }}
        .camera-stats {{
            padding: 10px 15px;
            background: #16213e;
            font-size: 0.9em;
        }}
        .camera-stats b {{
            color: #00ff88;
        }}
        .recent-detections {{
            max-width: 1800px;
            margin: 30px auto 0;
            padding: 20px;
            background: #1e2a4a;
            border-radius: 12px;
        }}
        .recent-detections h3 {{
            color: #00d4ff;
            margin-bottom: 15px;
        }}
        .detection-list {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 10px;
        }}
        .detection-item {{
            padding: 10px;
            background: #16213e;
            border-radius: 8px;
            font-size: 0.85em;
        }}
        .detection-item .time {{
            color: #00d4ff;
            font-weight: bold;
        }}
        .footer {{
            text-align: center;
            padding: 30px;
            color: #555;
            font-size: 0.85em;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Meteor Detection Dashboard</h1>
        <div class="subtitle">リアルタイム流星検出システム</div>
    </div>

    <div class="stats-bar">
        <div class="stat">
            <div class="stat-value" id="total-detections">0</div>
            <div class="stat-label">総検出数</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="active-cameras">{len(CAMERAS)}</div>
            <div class="stat-label">カメラ数</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="uptime">0:00</div>
            <div class="stat-label">稼働時間</div>
        </div>
    </div>

    <div class="camera-grid">
        {camera_cards}
    </div>

    <div class="recent-detections">
        <h3>最近の検出</h3>
        <div class="detection-list" id="detection-list">
            <div class="detection-item" style="color:#666">検出待機中...</div>
        </div>
    </div>

    <div class="footer">
        Meteor Detection System | Ctrl+C で終了
    </div>

    <script>
        const cameras = {json.dumps(CAMERAS)};
        const startTime = Date.now();

        // 稼働時間を更新
        setInterval(() => {{
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const hours = Math.floor(elapsed / 3600);
            const mins = Math.floor((elapsed % 3600) / 60);
            document.getElementById('uptime').textContent =
                hours > 0 ? hours + ':' + String(mins).padStart(2,'0') + 'h' : mins + 'm';
        }}, 1000);

        // 各カメラの統計を取得
        let totalDetections = 0;
        cameras.forEach((cam, i) => {{
            setInterval(() => {{
                fetch(cam.url + '/stats')
                    .then(r => r.json())
                    .then(data => {{
                        document.getElementById('count' + i).textContent = data.detections;
                        document.getElementById('status' + i).className = 'camera-status';
                    }})
                    .catch(() => {{
                        document.getElementById('status' + i).className = 'camera-status offline';
                    }});
            }}, 2000);
        }});

        // 検出一覧を更新
        setInterval(() => {{
            fetch('/detections')
                .then(r => r.json())
                .then(data => {{
                    document.getElementById('total-detections').textContent = data.total;
                    if (data.recent.length > 0) {{
                        const html = data.recent.map(d => `
                            <div class="detection-item">
                                <div class="time">${{d.time}}</div>
                                <div>${{d.camera}}</div>
                                <div>信頼度: ${{d.confidence}}</div>
                            </div>
                        `).join('');
                        document.getElementById('detection-list').innerHTML = html;
                    }}
                }});
        }}, 3000);
    </script>
</body>
</html>'''
            self.wfile.write(html.encode())

        elif self.path == '/detections':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            # 検出結果を集計
            detections = []
            total = 0

            try:
                for cam_dir in Path(DETECTIONS_DIR).iterdir():
                    if cam_dir.is_dir():
                        jsonl_file = cam_dir / 'detections.jsonl'
                        if jsonl_file.exists():
                            with open(jsonl_file, 'r') as f:
                                for line in f:
                                    try:
                                        d = json.loads(line)
                                        total += 1
                                        detections.append({
                                            'time': d.get('timestamp', '')[:19].replace('T', ' '),
                                            'camera': cam_dir.name,
                                            'confidence': f"{d.get('confidence', 0):.0%}",
                                        })
                                    except:
                                        pass
            except:
                pass

            # 最新10件
            detections.sort(key=lambda x: x['time'], reverse=True)
            result = {
                'total': total,
                'recent': detections[:10],
            }
            self.wfile.write(json.dumps(result).encode())

        else:
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
