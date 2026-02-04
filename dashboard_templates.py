"""Dashboard HTML rendering."""

import json


def render_dashboard_html(cameras, version):
    # カメラグリッドを生成
    camera_cards = ""
    for i, cam in enumerate(cameras):
        camera_cards += f'''
                <div class="camera-card">
                    <div class="camera-header">
                        <span class="camera-name">{cam['name']}</span>
                        <div class="status-indicators">
                            <span class="camera-status" id="status{i}" title="ストリーム接続">●</span>
                            <span class="detection-status" id="detection{i}" title="検出処理">●</span>
                        </div>
                    </div>
                    <div class="camera-actions">
                        <button class="mask-btn" onclick="updateMask({i})">マスク更新</button>
                    </div>
                    <div class="camera-video">
                        <img src="/camera_stream/{i}" alt="{cam['name']}"
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

    return f'''<!DOCTYPE html>
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
        .status-indicators {{
            display: flex;
            gap: 8px;
        }}
        .camera-status {{
            color: #00ff88;
            font-size: 0.8em;
        }}
        .camera-status.offline {{
            color: #ff4444;
        }}
        .detection-status {{
            color: #666;
            font-size: 0.8em;
        }}
        .detection-status.detecting {{
            color: #ff4444;
            animation: blink 1s infinite;
        }}
        @keyframes blink {{
            0%, 50% {{ opacity: 1; }}
            51%, 100% {{ opacity: 0.3; }}
        }}
        .camera-video {{
            position: relative;
            background: #000;
            aspect-ratio: 16/9;
        }}
        .camera-actions {{
            padding: 8px 12px;
            background: #16213e;
            border-bottom: 1px solid #2a3f6f;
            text-align: right;
        }}
        .mask-btn {{
            background: #2a3f6f;
            border: 1px solid #00d4ff;
            color: #00d4ff;
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
        }}
        .mask-btn:hover {{
            background: #00d4ff;
            color: #0f1530;
        }}
        .mask-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
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
            display: block;
            max-height: 60vh;
            overflow-y: auto;
            padding-right: 6px;
        }}
        .detection-group {{
            margin-bottom: 16px;
        }}
        .detection-group:last-child {{
            margin-bottom: 0;
        }}
        .detection-group-title {{
            color: #00ff88;
            font-weight: bold;
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1px solid #2a3f6f;
        }}
        .detection-group-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 10px;
        }}
        .detection-item {{
            padding: 10px;
            background: #16213e;
            border-radius: 8px;
            font-size: 0.85em;
            transition: background 0.2s;
        }}
        .detection-item:hover {{
            background: #2a3f6f;
        }}
        .detection-thumb {{
            width: 100%;
            height: 140px;
            object-fit: cover;
            border-radius: 6px;
            background: #000;
            cursor: pointer;
        }}
        .detection-item .time {{
            color: #00d4ff;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .detection-links {{
            display: flex;
            gap: 5px;
            margin-top: 8px;
            flex-wrap: wrap;
        }}
        .detection-actions {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin-top: 8px;
        }}
        .detection-link {{
            padding: 3px 8px;
            background: #2a3f6f;
            border: 1px solid #00d4ff;
            color: #00d4ff;
            border-radius: 4px;
            text-decoration: none;
            font-size: 0.8em;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .detection-link:hover {{
            background: #00d4ff;
            color: #0f1530;
        }}
        .delete-btn {{
            background: #ff4444;
            border: none;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8em;
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
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .modal-content img, .modal-content video {{
            max-width: 90%;
            max-height: 80vh;
            object-fit: contain;
            z-index: 1001;
        }}
        .modal-content video {{
            background: #000;
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
            <div class="stat-value" id="active-cameras">{len(cameras)}</div>
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
        Meteor Detection System <span class="version-link" onclick="showChangelog()">v{version}</span> | Ctrl+C で終了<br>
        &copy; 2026 株式会社　リバーランズ・コンサルティング
    </div>

    <!-- 画像・動画表示モーダル -->
    <div class="modal" id="image-modal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <img id="modal-image" src="" alt="検出画像" style="display:none;">
            <video id="modal-video" controls autoplay loop muted playsinline preload="metadata" style="display:none;"></video>
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
        const cameras = {json.dumps(cameras)};
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
        const cameraStatsTimers = [];
        const cameraStatsState = [];

        function scheduleCameraStats(i, delay) {{
            if (cameraStatsTimers[i]) {{
                clearTimeout(cameraStatsTimers[i]);
            }}
            cameraStatsTimers[i] = setTimeout(() => updateCameraStats(i), delay);
        }}

        function updateCameraStats(i) {{
            const cam = cameras[i];
            if (!cam) return;
            const baseDelay = 2000;
            const maxDelay = 30000;
            if (!cameraStatsState[i]) {{
                cameraStatsState[i] = {{ delay: baseDelay }};
            }}

            fetch('/camera_stats/' + i, {{ cache: 'no-store' }})
                .then(r => r.json())
                .then(data => {{
                    cameraStatsState[i].delay = baseDelay;
                    document.getElementById('count' + i).textContent = data.detections;
                    if (data.stream_alive === false) {{
                        document.getElementById('status' + i).className = 'camera-status offline';
                    }} else {{
                        document.getElementById('status' + i).className = 'camera-status';
                    }}
                    if (data.is_detecting === true) {{
                        document.getElementById('detection' + i).className = 'detection-status detecting';
                    }} else {{
                        document.getElementById('detection' + i).className = 'detection-status';
                    }}
                }})
                .catch(() => {{
                    cameraStatsState[i].delay = Math.min(cameraStatsState[i].delay * 2, maxDelay);
                    document.getElementById('status' + i).className = 'camera-status offline';
                    document.getElementById('detection' + i).className = 'detection-status';
                }})
                .finally(() => {{
                    scheduleCameraStats(i, cameraStatsState[i].delay);
                }});
        }}

        cameras.forEach((cam, i) => {{
            // 設定情報の取得（初回のみ）
            fetch('/camera_stats/' + i, {{ cache: 'no-store' }})
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

            updateCameraStats(i);
        }});

        // マスク更新
        function updateMask(i) {{
            const btn = document.querySelectorAll('.mask-btn')[i];
            if (!btn) return;
            btn.disabled = true;
            btn.textContent = '更新中...';
            fetch('/camera_mask/' + i, {{ method: 'POST' }})
                .then(r => r.json())
                .then(data => {{
                    btn.textContent = data.success ? '更新完了' : '失敗';
                }})
                .catch(() => {{
                    btn.textContent = '失敗';
                }})
                .finally(() => {{
                    setTimeout(() => {{
                        btn.textContent = 'マスク更新';
                        btn.disabled = false;
                    }}, 1500);
                }});
        }}

        // 画像モーダル表示
        function showImage(imagePath, time, camera, confidence) {{
            const imgEl = document.getElementById('modal-image');
            const videoEl = document.getElementById('modal-video');

            imgEl.src = '/image/' + encodeURI(imagePath);
            imgEl.style.display = 'block';
            videoEl.style.display = 'none';
            videoEl.pause();

            document.getElementById('modal-info').innerHTML =
                `${{time}} | ${{camera}} | 信頼度: ${{confidence}}`;
            document.getElementById('image-modal').classList.add('active');
        }}

        // 動画モーダル表示
        function showVideo(videoPath, time, camera, confidence) {{
            const imgEl = document.getElementById('modal-image');
            const videoEl = document.getElementById('modal-video');

            videoEl.src = '/image/' + encodeURI(videoPath);
            videoEl.style.display = 'block';
            imgEl.style.display = 'none';
            videoEl.load();
            videoEl.play().catch(() => {{}});

            document.getElementById('modal-info').innerHTML =
                `${{time}} | ${{camera}} | 信頼度: ${{confidence}}`;
            document.getElementById('image-modal').classList.add('active');
        }}

        function closeModal() {{
            const videoEl = document.getElementById('modal-video');
            videoEl.pause();
            videoEl.src = '';
            document.getElementById('image-modal').classList.remove('active');
        }}

        // モーダルの背景クリックで閉じる（動画のコントロールは除外）
        document.getElementById('image-modal').onclick = function(e) {{
            if (e.target.id === 'image-modal') {{
                closeModal();
            }}
        }};

        // 動画とコントロールのクリックでモーダルが閉じないようにする
        document.getElementById('modal-video').onclick = function(e) {{
            e.stopPropagation();
        }};
        document.getElementById('modal-image').onclick = function(e) {{
            e.stopPropagation();
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

            if (!confirm(`この検出を削除しますか?\n${{time}} - ${{camera}}`)) {{
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

        let lastDetectionsKey = '';
        const detectionPollBaseDelay = 3000;
        const detectionPollMaxDelay = 30000;
        let detectionPollDelay = detectionPollBaseDelay;
        let detectionPollTimer = null;

        function scheduleDetectionPoll(delay) {{
            if (detectionPollTimer) {{
                clearTimeout(detectionPollTimer);
            }}
            detectionPollTimer = setTimeout(updateDetections, delay);
        }}

        // 検出一覧を更新
        function updateDetections() {{
            fetch('/detections', {{ cache: 'no-store' }})
                .then(r => r.json())
                .then(data => {{
                    detectionPollDelay = detectionPollBaseDelay;
                    document.getElementById('total-detections').textContent = data.total;
                    if (data.recent.length > 0) {{
                        const detectionsKey = data.recent.map(d =>
                            `${{d.camera}}|${{d.time}}|${{d.confidence}}|${{d.image}}|${{d.mp4}}|${{d.composite_original}}`
                        ).join('||');
                        if (detectionsKey === lastDetectionsKey) {{
                            return;
                        }}
                        lastDetectionsKey = detectionsKey;

                        const grouped = {{}};
                        data.recent.forEach(d => {{
                            if (!grouped[d.camera]) {{
                                grouped[d.camera] = [];
                            }}
                            grouped[d.camera].push(d);
                        }});

                        const cameraOrder = cameras.map(cam => cam.name).filter(name => grouped[name]);
                        Object.keys(grouped).forEach(name => {{
                            if (!cameraOrder.includes(name)) {{
                                cameraOrder.push(name);
                            }}
                        }});

                        const html = cameraOrder.map(camera => {{
                            const items = grouped[camera].map(d => {{
                                const thumb = d.image
                                    ? `<img class="detection-thumb" src="/image/${{encodeURI(d.image)}}" alt="${{camera}}" loading="lazy" onclick="showImage('${{d.image}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">`
                                    : '';
                                return `
                                    <div class="detection-item">
                                        <div class="time">${{d.time}}</div>
                                        ${{thumb}}
                                        <div>信頼度: ${{d.confidence}}</div>
                                        <div class="detection-actions">
                                            <div class="detection-links">
                                                <span class="detection-link" onclick="showVideo('${{d.mp4}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">MP4</span>
                                                <span class="detection-link" onclick="showImage('${{d.image}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">合成</span>
                                                <span class="detection-link" onclick="showImage('${{d.composite_original}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">元画像</span>
                                            </div>
                                            <button class="delete-btn" onclick="deleteDetection('${{d.camera}}', '${{d.time}}', event)">削除</button>
                                        </div>
                                    </div>
                                `;
                            }}).join('');
                            return `
                                <div class="detection-group">
                                    <div class="detection-group-title">${{camera}}</div>
                                    <div class="detection-group-grid">
                                        ${{items}}
                                    </div>
                                </div>
                            `;
                        }}).join('');
                        document.getElementById('detection-list').innerHTML = html;
                    }} else {{
                        document.getElementById('detection-list').innerHTML = '<div class="detection-item" style="color:#666">検出待機中...</div>';
                    }}
                }})
                .catch(err => {{
                    detectionPollDelay = Math.min(detectionPollDelay * 2, detectionPollMaxDelay);
                    console.warn('Detections fetch error:', err);
                }})
                .finally(() => {{
                    scheduleDetectionPoll(detectionPollDelay);
                }});
        }}

        // 定期的に検出一覧を更新
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
