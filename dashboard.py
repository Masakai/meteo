#!/usr/bin/env python3
"""
流星検出ダッシュボード
全カメラのプレビューを1ページで表示

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
import json
import os
from pathlib import Path
from datetime import datetime

# 検出時間の取得用
try:
    from astro_utils import get_detection_window
except ImportError:
    get_detection_window = None

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
                        <span class="camera-params" id="params{i}"></span>
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
            min-width: 120px;
        }}
        .stats-bar .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #00ff88;
            white-space: nowrap;
        }}
        #detection-window {{
            font-size: 1.2em;
        }}
        .stat-wide {{
            min-width: 200px;
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
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .camera-stats b {{
            color: #00ff88;
        }}
        .camera-params {{
            font-size: 0.8em;
            color: #888;
        }}
        .camera-params .param {{
            display: inline-block;
            background: #2a3f6f;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 4px;
        }}
        .camera-params .param-clip {{
            color: #00ff88;
        }}
        .camera-params .param-no-clip {{
            color: #ff8844;
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
            cursor: pointer;
            transition: background 0.2s;
        }}
        .detection-item:hover {{
            background: #2a3f6f;
        }}
        .detection-item .time {{
            color: #00d4ff;
            font-weight: bold;
        }}
        .delete-btn {{
            background: #ff4444;
            border: none;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8em;
            margin-top: 5px;
            transition: background 0.2s;
        }}
        .delete-btn:hover {{
            background: #cc0000;
        }}
        .modal {{
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.9);
            align-items: center;
            justify-content: center;
        }}
        .modal.active {{
            display: flex;
        }}
        .modal-content {{
            max-width: 90%;
            max-height: 90%;
            position: relative;
        }}
        .modal-content img {{
            max-width: 70%;
            max-height: 70vh;
            object-fit: contain;
        }}
        .modal-close {{
            position: absolute;
            top: -40px;
            right: 0;
            color: #fff;
            font-size: 40px;
            font-weight: bold;
            cursor: pointer;
            background: none;
            border: none;
        }}
        .modal-close:hover {{
            color: #00d4ff;
        }}
        .modal-info {{
            position: absolute;
            bottom: -60px;
            left: 0;
            right: 0;
            text-align: center;
            color: #aaa;
            font-size: 0.9em;
        }}
        .footer {{
            text-align: center;
            padding: 30px;
            color: #555;
            font-size: 0.85em;
        }}
        .version-link {{
            color: #00d4ff;
            text-decoration: none;
            cursor: pointer;
            transition: color 0.2s;
        }}
        .version-link:hover {{
            color: #00ff88;
        }}
        .changelog-modal {{
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.9);
            align-items: center;
            justify-content: center;
        }}
        .changelog-modal.active {{
            display: flex;
        }}
        .changelog-content {{
            max-width: 800px;
            max-height: 80vh;
            overflow-y: auto;
            background: #1e2a4a;
            padding: 30px;
            border-radius: 12px;
            position: relative;
            color: #eee;
        }}
        .changelog-content h1, .changelog-content h2 {{
            color: #00d4ff;
        }}
        .changelog-content h3 {{
            color: #00ff88;
        }}
        .changelog-content pre {{
            background: #16213e;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
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
        <div class="stat stat-wide">
            <div class="stat-value" id="detection-window">--:-- ~ --:--</div>
            <div class="stat-label">検出時間帯</div>
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
        Meteor Detection System <span class="version-link" onclick="showChangelog()">v1.1.0</span> | Ctrl+C で終了<br>
        &copy; 2026 株式会社　リバーランズ・コンサルティング
    </div>

    <!-- 画像表示モーダル -->
    <div class="modal" id="image-modal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <img id="modal-image" src="" alt="検出画像">
            <div class="modal-info" id="modal-info"></div>
        </div>
    </div>

    <!-- CHANGELOG表示モーダル -->
    <div class="changelog-modal" id="changelog-modal">
        <div class="changelog-content">
            <button class="modal-close" onclick="closeChangelog()">&times;</button>
            <div id="changelog-text">読み込み中...</div>
        </div>
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

        // ブラウザから位置情報を取得
        let userLocation = null;
        const savedLocation = localStorage.getItem('userLocation');
        if (savedLocation) {{
            userLocation = JSON.parse(savedLocation);
        }}

        // 初回アクセス時に位置情報を取得
        if (!userLocation && navigator.geolocation) {{
            navigator.geolocation.getCurrentPosition(
                (position) => {{
                    userLocation = {{
                        lat: position.coords.latitude,
                        lon: position.coords.longitude
                    }};
                    localStorage.setItem('userLocation', JSON.stringify(userLocation));
                    console.log('位置情報を取得しました:', userLocation);
                    updateDetectionWindow();  // 位置情報取得後に更新
                }},
                (error) => {{
                    console.warn('位置情報の取得に失敗しました:', error.message);
                    updateDetectionWindow();  // デフォルト位置で更新
                }}
            );
        }}

        // 検出時間帯を取得・更新
        function updateDetectionWindow() {{
            let url = '/detection_window';
            if (userLocation) {{
                url += '?lat=' + userLocation.lat + '&lon=' + userLocation.lon;
            }}

            fetch(url)
                .then(r => r.json())
                .then(data => {{
                    console.log('Detection window data:', data);
                    if (data.enabled && data.start && data.end) {{
                        // 日付と時刻を分離
                        const startParts = data.start.split(' ');
                        const endParts = data.end.split(' ');
                        const startDate = startParts[0];
                        const endDate = endParts[0];
                        const startTime = startParts[1].substring(0, 5);
                        const endTime = endParts[1].substring(0, 5);

                        // 前日と翌日の日付を取得
                        const today = new Date();
                        const yesterday = new Date(today);
                        yesterday.setDate(yesterday.getDate() - 1);
                        const tomorrow = new Date(today);
                        tomorrow.setDate(tomorrow.getDate() + 1);

                        // 日付のフォーマット（YYYY-MM-DD）
                        const formatDate = (d) => d.toISOString().split('T')[0];
                        const todayStr = formatDate(today);
                        const yesterdayStr = formatDate(yesterday);
                        const tomorrowStr = formatDate(tomorrow);

                        let displayText = '';
                        if (startDate === yesterdayStr) {{
                            displayText = '前日' + startTime + ' ~ ';
                        }} else if (startDate === todayStr) {{
                            displayText = '当日' + startTime + ' ~ ';
                        }} else {{
                            displayText = startTime + ' ~ ';
                        }}

                        if (endDate === tomorrowStr) {{
                            displayText += '翌日' + endTime;
                        }} else if (endDate === todayStr) {{
                            displayText += '当日' + endTime;
                        }} else {{
                            displayText += endTime;
                        }}

                        document.getElementById('detection-window').textContent = displayText;
                    }} else {{
                        document.getElementById('detection-window').textContent = '常時有効';
                    }}
                }})
                .catch((err) => {{
                    console.error('Detection window fetch error:', err);
                    document.getElementById('detection-window').textContent = '--:-- ~ --:--';
                }});
        }}
        updateDetectionWindow();
        setInterval(updateDetectionWindow, 60000);  // 1分ごとに更新

        // 各カメラの統計を取得
        let totalDetections = 0;
        cameras.forEach((cam, i) => {{
            // 設定情報の取得（初回のみ）
            fetch(cam.url + '/stats')
                .then(r => r.json())
                .then(data => {{
                    if (data.settings) {{
                        const s = data.settings;
                        const clipClass = s.extract_clips ? 'param-clip' : 'param-no-clip';
                        const clipText = s.extract_clips ? 'CLIP:ON' : 'CLIP:OFF';
                        document.getElementById('params' + i).innerHTML =
                            `<span class="param">${{s.sensitivity}}</span>` +
                            `<span class="param">x${{s.scale}}</span>` +
                            `<span class="param ${{clipClass}}">${{clipText}}</span>`;
                    }}
                }})
                .catch(() => {{}});

            // 検出数の定期更新
            setInterval(() => {{
                fetch(cam.url + '/stats')
                    .then(r => r.json())
                    .then(data => {{
                        document.getElementById('count' + i).textContent = data.detections;
                        // stream_aliveがfalseの場合はオフライン表示
                        if (data.stream_alive === false) {{
                            document.getElementById('status' + i).className = 'camera-status offline';
                        }} else {{
                            document.getElementById('status' + i).className = 'camera-status';
                        }}
                    }})
                    .catch(() => {{
                        document.getElementById('status' + i).className = 'camera-status offline';
                    }});
            }}, 2000);
        }});

        // 画像モーダル表示
        function showImage(imagePath, time, camera, confidence) {{
            document.getElementById('modal-image').src = '/image/' + imagePath;
            document.getElementById('modal-info').innerHTML =
                `${{time}} | ${{camera}} | 信頼度: ${{confidence}}`;
            document.getElementById('image-modal').classList.add('active');
        }}

        function closeModal() {{
            document.getElementById('image-modal').classList.remove('active');
        }}

        // モーダルの背景クリックで閉じる
        document.getElementById('image-modal').onclick = function(e) {{
            if (e.target.id === 'image-modal') {{
                closeModal();
            }}
        }};

        // ESCキーでモーダルを閉じる
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') {{
                closeModal();
            }}
        }});

        // 検出削除関数
        function deleteDetection(camera, time, event) {{
            event.stopPropagation(); // 画像表示イベントを防止

            if (!confirm(`この検出を削除しますか?\\n${{time}} - ${{camera}}`)) {{
                return;
            }}

            fetch(`/detection/${{camera}}/${{time}}`, {{
                method: 'DELETE'
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    alert(data.message);
                    // 検出リストを即座に更新
                    updateDetections();
                }} else {{
                    alert('削除に失敗しました: ' + (data.error || '不明なエラー'));
                }}
            }})
            .catch(err => {{
                alert('削除に失敗しました: ' + err.message);
            }});
        }}

        // 検出一覧を更新
        function updateDetections() {{
            fetch('/detections')
                .then(r => r.json())
                .then(data => {{
                    document.getElementById('total-detections').textContent = data.total;
                    if (data.recent.length > 0) {{
                        const html = data.recent.map(d => `
                            <div class="detection-item" onclick="showImage('${{d.image}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">
                                <div class="time">${{d.time}}</div>
                                <div>${{d.camera}}</div>
                                <div>信頼度: ${{d.confidence}}</div>
                                <button class="delete-btn" onclick="deleteDetection('${{d.camera}}', '${{d.time}}', event)">削除</button>
                            </div>
                        `).join('');
                        document.getElementById('detection-list').innerHTML = html;
                    }} else {{
                        document.getElementById('detection-list').innerHTML = '<div class="detection-item" style="color:#666">検出待機中...</div>';
                    }}
                }});
        }}

        // 定期的に検出一覧を更新
        setInterval(updateDetections, 3000);
        updateDetections(); // 初回実行

        // CHANGELOG表示
        function showChangelog() {{
            document.getElementById('changelog-modal').classList.add('active');
            fetch('/changelog')
                .then(r => r.text())
                .then(text => {{
                    // マークダウンを簡易HTMLに変換
                    const lines = text.split('\\n');
                    let html = '';
                    for (let line of lines) {{
                        if (line.startsWith('# ')) {{
                            html += '<h1>' + line.substring(2) + '</h1>';
                        }} else if (line.startsWith('## ')) {{
                            html += '<h2>' + line.substring(3) + '</h2>';
                        }} else if (line.startsWith('### ')) {{
                            html += '<h3>' + line.substring(4) + '</h3>';
                        }} else if (line.startsWith('- ')) {{
                            html += '<li>' + line.substring(2) + '</li>';
                        }} else if (line.trim() === '') {{
                            html += '<br>';
                        }} else {{
                            html += '<p>' + line + '</p>';
                        }}
                    }}
                    document.getElementById('changelog-text').innerHTML = html;
                }})
                .catch(() => {{
                    document.getElementById('changelog-text').innerHTML = '<p>CHANGELOGの読み込みに失敗しました</p>';
                }});
        }}

        function closeChangelog() {{
            document.getElementById('changelog-modal').classList.remove('active');
        }}

        // CHANGELOGモーダルの背景クリックで閉じる
        document.getElementById('changelog-modal').onclick = function(e) {{
            if (e.target.id === 'changelog-modal') {{
                closeChangelog();
            }}
        }};
    </script>
</body>
</html>'''
            self.wfile.write(html.encode())

        elif self.path.startswith('/detection_window'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            # クエリパラメータから緯度・経度を取得（ブラウザから送信）
            from urllib.parse import urlparse, parse_qs
            query = parse_qs(urlparse(self.path).query)

            # ブラウザから送信された座標、なければ環境変数、なければデフォルト（富士山頂）
            latitude = float(query.get('lat', [os.environ.get('LATITUDE', '35.3606')])[0])
            longitude = float(query.get('lon', [os.environ.get('LONGITUDE', '138.7274')])[0])
            timezone = os.environ.get('TIMEZONE', 'Asia/Tokyo')

            try:
                if get_detection_window:
                    start, end = get_detection_window(latitude, longitude, timezone)
                    result = {
                        'start': start.strftime('%Y-%m-%d %H:%M:%S'),
                        'end': end.strftime('%Y-%m-%d %H:%M:%S'),
                        'enabled': os.environ.get('ENABLE_TIME_WINDOW', 'false').lower() == 'true',
                        'latitude': latitude,
                        'longitude': longitude
                    }
                else:
                    result = {
                        'start': '',
                        'end': '',
                        'enabled': False,
                        'error': 'meteor_detector module not available'
                    }
            except Exception as e:
                result = {
                    'start': '',
                    'end': '',
                    'enabled': False,
                    'error': str(e)
                }

            self.wfile.write(json.dumps(result).encode('utf-8'))

        elif self.path == '/changelog':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()

            try:
                changelog_path = Path(__file__).parent / 'CHANGELOG.md'
                if changelog_path.exists():
                    with open(changelog_path, 'r', encoding='utf-8') as f:
                        self.wfile.write(f.read().encode('utf-8'))
                else:
                    self.wfile.write(b'CHANGELOG.md not found')
            except Exception as e:
                self.wfile.write(f'Error: {str(e)}'.encode('utf-8'))

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
                                        timestamp_str = d.get('timestamp', '')
                                        # タイムスタンプからファイル名を推測
                                        # timestamp: "2026-02-02T06:55:33.411811"
                                        # filename: "meteor_20260202_065533_composite.jpg"
                                        if timestamp_str:
                                            dt = datetime.fromisoformat(timestamp_str)
                                            filename = f"meteor_{dt.strftime('%Y%m%d_%H%M%S')}_composite.jpg"
                                            composite_path = f"{cam_dir.name}/{filename}"
                                        else:
                                            composite_path = ''

                                        total += 1
                                        detections.append({
                                            'time': timestamp_str[:19].replace('T', ' '),
                                            'camera': cam_dir.name,
                                            'confidence': f"{d.get('confidence', 0):.0%}",
                                            'image': composite_path,
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

        elif self.path.startswith('/image/'):
            # /image/camera_name/filename.jpg
            try:
                parts = self.path[7:].split('/', 1)
                if len(parts) == 2:
                    camera_name, filename = parts
                    image_path = Path(DETECTIONS_DIR) / camera_name / filename

                    if image_path.exists() and image_path.is_file():
                        self.send_response(200)
                        if filename.endswith('.jpg') or filename.endswith('.jpeg'):
                            self.send_header('Content-type', 'image/jpeg')
                        elif filename.endswith('.png'):
                            self.send_header('Content-type', 'image/png')
                        self.end_headers()

                        with open(image_path, 'rb') as f:
                            self.wfile.write(f.read())
                        return
            except:
                pass

            self.send_response(404)
            self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        """DELETE リクエストを処理（検出結果の削除）"""
        if self.path.startswith('/detection/'):
            # /detection/camera_name/timestamp
            try:
                parts = self.path[11:].split('/', 1)
                if len(parts) == 2:
                    camera_name, timestamp_str = parts

                    # タイムスタンプから datetime オブジェクトを作成
                    # timestamp_str: "2026-02-02 06:55:33"
                    dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    base_filename = f"meteor_{dt.strftime('%Y%m%d_%H%M%S')}"

                    cam_dir = Path(DETECTIONS_DIR) / camera_name

                    # 削除するファイルのリスト（3つのファイル）
                    files_to_delete = [
                        cam_dir / f"{base_filename}.mp4",
                        cam_dir / f"{base_filename}_composite.jpg",
                        cam_dir / f"{base_filename}_composite_original.jpg",
                    ]

                    deleted_files = []
                    for file_path in files_to_delete:
                        if file_path.exists():
                            file_path.unlink()
                            deleted_files.append(file_path.name)

                    # detections.jsonl から該当行を削除
                    jsonl_file = cam_dir / 'detections.jsonl'
                    if jsonl_file.exists():
                        # 元のタイムスタンプ形式に戻す（ISO形式）
                        target_timestamp = dt.isoformat()

                        # 一時ファイルに書き込み
                        temp_file = cam_dir / 'detections.jsonl.tmp'
                        removed_count = 0

                        with open(jsonl_file, 'r', encoding='utf-8') as f_in, \
                             open(temp_file, 'w', encoding='utf-8') as f_out:
                            for line in f_in:
                                try:
                                    d = json.loads(line)
                                    # タイムスタンプが一致しない行のみ書き込む
                                    if not d.get('timestamp', '').startswith(target_timestamp):
                                        f_out.write(line)
                                    else:
                                        removed_count += 1
                                except:
                                    # パースできない行はそのまま保持
                                    f_out.write(line)

                        # 元のファイルを置き換え
                        temp_file.replace(jsonl_file)

                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()

                    response = {
                        'success': True,
                        'deleted_files': deleted_files,
                        'message': f'{len(deleted_files)}個のファイルを削除しました'
                    }
                    self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
                    return

            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                response = {
                    'success': False,
                    'error': str(e)
                }
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
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
