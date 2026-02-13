"""Dashboard HTML rendering."""

import json


def render_dashboard_html(cameras, version, server_start_time):
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
                            <span class="mask-status" id="mask-status{i}" title="マスク適用">MASK</span>
                        </div>
                    </div>
                    <div class="camera-actions">
                        <button class="open-tab-btn" onclick="openCameraTab({i})">タブ起動 (:808{i + 1})</button>
                        <button class="mask-btn" onclick="updateMask({i})">マスク更新</button>
                        <button class="mask-reset-btn" onclick="resetMask({i})">マスクリセット</button>
                        <button class="snapshot-btn" onclick="downloadSnapshot({i})">スナップショット保存</button>
                        <button class="restart-btn" onclick="restartCamera({i})">再起動</button>
                    </div>
                    <div class="camera-control-panel">
                        <div class="control-panel-title">rtsp_web 操作パネル</div>
                        <div class="control-panel-url" id="control-url{i}">{cam['url']}</div>
                        <div class="camera-latest-detection">
                            <div class="latest-row"><span>最終検出時刻</span><b id="latest-time{i}">-</b></div>
                            <div class="latest-row"><span>信頼度</span><b id="latest-confidence{i}">-</b></div>
                            <div class="latest-row"><span>分類</span><b id="latest-label{i}">-</b></div>
                        </div>
                    </div>
                    <div class="camera-stats">
                        <span>検出: <b id="count{i}">-</b></span>
                        <span class="meteor-lamp idle" id="meteor-lamp{i}"><span class="dot">●</span>視野内検出 OFF</span>
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
        .settings-menu-link {{
            display: inline-block;
            margin-top: 10px;
            color: #7bf3be;
            text-decoration: none;
            border: 1px solid #2a6f59;
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 0.85em;
        }}
        .settings-menu-link:hover {{
            background: #2a6f59;
            color: #eafff5;
        }}
        .stats-bar {{
            display: flex;
            justify-content: center;
            align-items: flex-end;
            flex-wrap: wrap;
            gap: 40px;
            margin-bottom: 30px;
            padding: 15px;
            background: rgba(0,212,255,0.1);
            border-radius: 10px;
        }}
        .stats-bar .stat {{
            display: flex;
            flex-direction: column;
            justify-content: flex-end;
            text-align: center;
            min-width: 120px;
        }}
        .stats-bar .stat-value {{
            line-height: 1.1;
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
        .settings-panel {{
            max-width: 1800px;
            margin: 0 auto 18px;
            padding: 12px 14px;
            background: #1e2a4a;
            border: 1px solid #2a3f6f;
            border-radius: 10px;
            display: flex;
            align-items: flex-end;
            gap: 12px;
            flex-wrap: wrap;
        }}
        .settings-panel-title {{
            color: #00d4ff;
            font-weight: bold;
            margin-right: 8px;
        }}
        .settings-field {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            min-width: 130px;
        }}
        .settings-field label {{
            color: #9bb1d8;
            font-size: 0.78em;
        }}
        .settings-field select,
        .settings-field input[type="number"] {{
            background: #131f3d;
            color: #eee;
            border: 1px solid #2a3f6f;
            border-radius: 6px;
            padding: 6px 8px;
            font-size: 0.85em;
        }}
        .settings-check {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            color: #c1d0eb;
            font-size: 0.85em;
            padding-bottom: 6px;
        }}
        .settings-apply-btn {{
            background: #2a3f6f;
            border: 1px solid #00d4ff;
            color: #00d4ff;
            padding: 7px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
        }}
        .settings-apply-btn:hover {{
            background: #00d4ff;
            color: #0f1530;
        }}
        .settings-apply-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .settings-message {{
            color: #9bb1d8;
            font-size: 0.82em;
            min-height: 1.2em;
            margin-left: auto;
        }}
        .settings-message.error {{
            color: #ff7f7f;
        }}
        .settings-message.ok {{
            color: #7bf3be;
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
        .camera-status.paused {{
            color: #888;
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
        .camera-actions {{
            padding: 8px 12px;
            background: #16213e;
            border-bottom: 1px solid #2a3f6f;
            display: flex;
            justify-content: flex-end;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .open-tab-btn {{
            margin-right: auto;
            background: #234a37;
            border: 1px solid #7bf3be;
            color: #c8ffe7;
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
        }}
        .open-tab-btn:hover {{
            background: #7bf3be;
            color: #0f1530;
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
        .mask-reset-btn {{
            background: #3a2430;
            border: 1px solid #ff7f7f;
            color: #ffb3b3;
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
        }}
        .mask-reset-btn:hover {{
            background: #ff6b6b;
            color: #1a1a2e;
        }}
        .mask-reset-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .snapshot-btn {{
            background: #1e3b37;
            border: 1px solid #48d1bf;
            color: #9ff7e9;
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
        }}
        .snapshot-btn:hover {{
            background: #48d1bf;
            color: #0f1530;
        }}
        .snapshot-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .restart-btn {{
            background: #3a2430;
            border: 1px solid #ff7f7f;
            color: #ffb3b3;
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
        }}
        .restart-btn:hover {{
            background: #ff6b6b;
            color: #1a1a2e;
        }}
        .restart-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .camera-control-panel {{
            padding: 14px 15px;
            background: #0f172d;
            border-bottom: 1px solid #2a3f6f;
            min-height: 180px;
        }}
        .control-panel-title {{
            color: #7bf3be;
            font-weight: bold;
            margin-bottom: 8px;
        }}
        .control-panel-url {{
            color: #9bb1d8;
            background: #131f3d;
            border: 1px solid #2a3f6f;
            border-radius: 6px;
            padding: 8px 10px;
            margin-bottom: 10px;
            word-break: break-all;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 0.85em;
        }}
        .camera-latest-detection {{
            background: #131f3d;
            border: 1px solid #2a3f6f;
            border-radius: 6px;
            padding: 8px 10px;
            color: #b8c8e8;
            font-size: 0.85em;
        }}
        .latest-row {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 12px;
            margin-top: 6px;
        }}
        .latest-row:first-child {{
            margin-top: 0;
        }}
        .latest-row b {{
            color: #00ff88;
            font-weight: 700;
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
        .meteor-lamp {{
            display: inline-flex;
            align-items: center;
            gap: 5px;
            font-size: 0.82em;
            border: 1px solid #3a4f79;
            border-radius: 999px;
            padding: 3px 8px;
            background: #1a2747;
            color: #9bb1d8;
            white-space: nowrap;
        }}
        .meteor-lamp .dot {{
            font-size: 0.9em;
            line-height: 1;
            color: #7d8daa;
        }}
        .meteor-lamp.on {{
            border-color: #ff6b6b;
            background: #3b2030;
            color: #ffd3d3;
        }}
        .meteor-lamp.on .dot {{
            color: #ff4d4d;
            animation: blink 0.8s infinite;
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
        .mask-status {{
            color: #666;
            border: 1px solid #666;
            font-size: 0.65em;
            padding: 1px 4px;
            border-radius: 4px;
        }}
        .mask-status.active {{
            color: #ff6b6b;
            border-color: #ff6b6b;
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
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 10px;
        }}
        .detection-item {{
            padding: 12px;
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
            flex-direction: column;
            align-items: stretch;
            gap: 10px;
            margin-top: 8px;
        }}
        .detection-view-actions {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
            gap: 6px;
        }}
        .detection-manage-actions {{
            display: flex;
            gap: 8px;
            align-items: center;
        }}
        .detection-link {{
            padding: 7px 8px;
            background: #2a3f6f;
            border: 1px solid #00d4ff;
            color: #00d4ff;
            border-radius: 4px;
            text-decoration: none;
            font-size: 0.8em;
            cursor: pointer;
            transition: all 0.2s;
            min-height: 34px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }}
        .detection-link:hover {{
            background: #00d4ff;
            color: #0f1530;
        }}
        .delete-btn {{
            background: #ff4444;
            border: none;
            color: white;
            padding: 7px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8em;
            transition: background 0.2s;
            min-height: 34px;
            white-space: nowrap;
        }}
        .delete-btn:hover {{
            background: #cc0000;
        }}
        .label-radios {{
            display: flex;
            gap: 6px;
            flex: 1;
            min-width: 0;
        }}
        .label-radio {{
            flex: 1;
            position: relative;
            cursor: pointer;
        }}
        .label-radio input {{
            position: absolute;
            opacity: 0;
            pointer-events: none;
        }}
        .label-radio span {{
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 34px;
            padding: 6px 8px;
            border-radius: 4px;
            border: 1px solid #2a5a86;
            background: #1f324f;
            color: #d8ecff;
            font-size: 0.8em;
            user-select: none;
        }}
        .label-radio input:checked + span {{
            border-color: #6ddf94;
            color: #d8ffe8;
            background: #1d4632;
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
        .modal-downloads {{
            position: absolute;
            bottom: -85px;
            left: 0;
            right: 0;
            text-align: center;
        }}
        .modal-downloads a {{
            color: #00d4ff;
            text-decoration: none;
            font-size: 0.9em;
        }}
        .modal-downloads a:hover {{
            text-decoration: underline;
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
        <a class="settings-menu-link" href="/settings">設定メニューへ</a>
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
            <div class="stat-value" id="dashboard-cpu">--</div>
            <div class="stat-label">System CPU</div>
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

    <div class="settings-panel">
        <div class="settings-panel-title">全カメラ設定</div>
        <div class="settings-field">
            <label for="setting-sensitivity">感度</label>
            <select id="setting-sensitivity">
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="fireball">fireball</option>
            </select>
        </div>
        <div class="settings-field">
            <label for="setting-exclude-bottom">下部除外比率</label>
            <input id="setting-exclude-bottom" type="number" min="0" max="0.5" step="0.01" value="0.0625">
        </div>
        <label class="settings-check">
            <input id="setting-extract-clips" type="checkbox" checked>
            クリップ保存
        </label>
        <button class="settings-apply-btn" id="settings-apply-btn" onclick="applySettingsAll()">全カメラへ反映</button>
        <div class="settings-message" id="settings-message"></div>
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
            <div class="modal-downloads" id="modal-downloads"></div>
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
        const serverStartTime = {int(server_start_time * 1000)};

        // 稼働時間を更新
        setInterval(() => {{
            const elapsed = Math.floor((Date.now() - serverStartTime) / 1000);
            const hours = Math.floor(elapsed / 3600);
            const mins = Math.floor((elapsed % 3600) / 60);
            document.getElementById('uptime').textContent =
                hours > 0 ? hours + ':' + String(mins).padStart(2,'0') + 'h' : mins + 'm';
        }}, 1000);

        function updateDashboardCpu() {{
            fetch('/dashboard_stats', {{ cache: 'no-store' }})
                .then(r => r.json())
                .then(data => {{
                    const cpu = Number(data.cpu_percent);
                    if (!Number.isFinite(cpu)) {{
                        document.getElementById('dashboard-cpu').textContent = '--';
                        return;
                    }}
                    document.getElementById('dashboard-cpu').textContent = cpu.toFixed(1) + '%';
                }})
                .catch(() => {{
                    document.getElementById('dashboard-cpu').textContent = '--';
                }});
        }}
        updateDashboardCpu();
        setInterval(updateDashboardCpu, 5000);

        // ブラウザ位置情報は使用せず、サーバー設定の位置情報を常に利用する

        const detectionWindowState = {{
            enabled: false,
            start: null,
            end: null
        }};

        function parseDetectionWindowTime(value) {{
            if (!value) return null;
            const iso = value.replace(' ', 'T');
            const dt = new Date(iso);
            return Number.isNaN(dt.getTime()) ? null : dt;
        }}

        function isWithinDetectionWindow() {{
            if (!detectionWindowState.enabled) return true;
            if (!detectionWindowState.start || !detectionWindowState.end) return true;
            const now = new Date();
            return now >= detectionWindowState.start && now <= detectionWindowState.end;
        }}

        // 検出時間帯を取得・更新
        function updateDetectionWindow() {{
            fetch('/detection_window')
                .then(r => r.json())
                .then(data => {{
                    detectionWindowState.enabled = data.enabled === true;
                    detectionWindowState.start = parseDetectionWindowTime(data.start);
                    detectionWindowState.end = parseDetectionWindowTime(data.end);
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
                    detectionWindowState.enabled = false;
                    detectionWindowState.start = null;
                    detectionWindowState.end = null;
                }});
        }}
        updateDetectionWindow();
        setInterval(updateDetectionWindow, 60000);  // 1分ごとに更新

        let settingsFormHydrated = false;
        let settingsFormDirty = false;

        function markSettingsDirty() {{
            settingsFormDirty = true;
        }}

        function hydrateSettingsForm(settings) {{
            if (!settings || settingsFormDirty) return;
            const sensitivityEl = document.getElementById('setting-sensitivity');
            const excludeBottomEl = document.getElementById('setting-exclude-bottom');
            const extractClipsEl = document.getElementById('setting-extract-clips');
            if (sensitivityEl && typeof settings.sensitivity === 'string') {{
                sensitivityEl.value = settings.sensitivity;
            }}
            if (excludeBottomEl && Number.isFinite(Number(settings.exclude_bottom))) {{
                excludeBottomEl.value = Number(settings.exclude_bottom).toFixed(4).replace(/0+$/, '').replace(/\\.$/, '') || '0';
            }}
            if (extractClipsEl && typeof settings.extract_clips === 'boolean') {{
                extractClipsEl.checked = settings.extract_clips;
            }}
            settingsFormHydrated = true;
        }}

        function setSettingsMessage(message, level = '') {{
            const el = document.getElementById('settings-message');
            if (!el) return;
            el.textContent = message || '';
            el.className = 'settings-message' + (level ? ' ' + level : '');
        }}

        function applySettingsAll() {{
            const sensitivityEl = document.getElementById('setting-sensitivity');
            const excludeBottomEl = document.getElementById('setting-exclude-bottom');
            const extractClipsEl = document.getElementById('setting-extract-clips');
            const btn = document.getElementById('settings-apply-btn');
            if (!sensitivityEl || !excludeBottomEl || !extractClipsEl || !btn) return;

            const excludeBottom = Number(excludeBottomEl.value);
            if (!Number.isFinite(excludeBottom) || excludeBottom < 0 || excludeBottom > 0.5) {{
                setSettingsMessage('下部除外比率は 0.0 から 0.5 で入力してください', 'error');
                return;
            }}

            const payload = {{
                sensitivity: sensitivityEl.value,
                extract_clips: extractClipsEl.checked === true,
                exclude_bottom: excludeBottom,
            }};

            btn.disabled = true;
            btn.textContent = '反映中...';
            setSettingsMessage('全カメラへ設定反映中...');
            fetch('/apply_settings_all', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload),
            }})
                .then(r => r.json())
                .then(data => {{
                    settingsFormDirty = false;
                    const ok = data && data.success === true;
                    if (ok) {{
                        setSettingsMessage('反映完了 (' + data.success_count + '/' + data.total + ')', 'ok');
                    }} else {{
                        const failed = (data && Array.isArray(data.results))
                            ? data.results.filter(x => !x.success).map(x => x.camera).join(', ')
                            : '';
                        const countText = '一部失敗 (' + (data.success_count || 0) + '/' + (data.total || cameras.length) + ')';
                        setSettingsMessage(countText + (failed ? (' ' + failed) : ''), 'error');
                    }}
                    cameras.forEach((_, i) => updateCameraStats(i));
                }})
                .catch((err) => {{
                    setSettingsMessage('反映失敗: ' + err.message, 'error');
                }})
                .finally(() => {{
                    btn.disabled = false;
                    btn.textContent = '全カメラへ反映';
                }});
        }}

        document.getElementById('setting-sensitivity').addEventListener('change', markSettingsDirty);
        document.getElementById('setting-exclude-bottom').addEventListener('input', markSettingsDirty);
        document.getElementById('setting-extract-clips').addEventListener('change', markSettingsDirty);

        // 各カメラの統計を取得
        let totalDetections = 0;
        const cameraStatsTimers = [];
        const cameraStatsState = [];
        let dashboardBackgroundPaused = document.hidden === true;
        let detectionPollTimer = null;

        function clearAllCameraStatsTimers() {{
            for (let i = 0; i < cameraStatsTimers.length; i++) {{
                if (cameraStatsTimers[i]) {{
                    clearTimeout(cameraStatsTimers[i]);
                    cameraStatsTimers[i] = null;
                }}
            }}
        }}

        function pauseDashboardActivity() {{
            dashboardBackgroundPaused = true;
            clearAllCameraStatsTimers();
            if (detectionPollTimer) {{
                clearTimeout(detectionPollTimer);
                detectionPollTimer = null;
            }}
            cameras.forEach((_, i) => {{
                const statusEl = document.getElementById('status' + i);
                if (statusEl) {{
                    statusEl.className = 'camera-status paused';
                }}
            }});
        }}

        function resumeDashboardActivity() {{
            if (!dashboardBackgroundPaused) {{
                return;
            }}
            dashboardBackgroundPaused = false;
            cameras.forEach((_, i) => {{
                const statusEl = document.getElementById('status' + i);
                if (statusEl) {{
                    statusEl.className = 'camera-status';
                }}
            }});
            cameras.forEach((_, i) => {{
                updateCameraStats(i);
            }});
            pollDetections();
        }}

        function syncDashboardVisibilityState() {{
            if (document.hidden) {{
                pauseDashboardActivity();
            }} else {{
                resumeDashboardActivity();
            }}
        }}

        function scheduleCameraStats(i, delay) {{
            if (dashboardBackgroundPaused) {{
                return;
            }}
            if (cameraStatsTimers[i]) {{
                clearTimeout(cameraStatsTimers[i]);
            }}
            cameraStatsTimers[i] = setTimeout(() => updateCameraStats(i), delay);
        }}

        function renderCameraParams(i, data) {{
            const el = document.getElementById('params' + i);
            if (!el || !data || !data.settings) return;
            const s = data.settings;
            if (!settingsFormHydrated) {{
                hydrateSettingsForm(s);
            }}
            const clipClass = s.extract_clips ? 'param-clip' : 'param-no-clip';
            const clipText = s.extract_clips ? 'CLIP:ON' : 'CLIP:OFF';
            const sourceFps = Number(s.source_fps || 0);
            const runtimeFps = Number(data.runtime_fps || 0);
            const fpsText = runtimeFps > 0 ? runtimeFps.toFixed(1) : (sourceFps > 0 ? sourceFps.toFixed(1) : '-');
            el.innerHTML =
                `<span class="param">${{s.sensitivity}}</span>` +
                `<span class="param">x${{s.scale}}</span>` +
                `<span class="param">FPS:${{fpsText}}</span>` +
                `<span class="param ${{clipClass}}">${{clipText}}</span>`;
        }}

        function updateCameraStats(i) {{
            if (dashboardBackgroundPaused) return;
            const cam = cameras[i];
            if (!cam) return;
            const baseDelay = 60000;
            const maxDelay = 300000;
            if (!cameraStatsState[i]) {{
                cameraStatsState[i] = {{ delay: baseDelay }};
            }}

            fetch('/camera_stats/' + i, {{ cache: 'no-store' }})
                .then(r => r.json())
                .then(data => {{
                    if (dashboardBackgroundPaused) {{
                        return;
                    }}
                    cameraStatsState[i].delay = baseDelay;
                    document.getElementById('count' + i).textContent = data.detections;
                    renderCameraParams(i, data);
                    const streamAlive = data.stream_alive !== false;
                    if (!streamAlive) {{
                        document.getElementById('status' + i).className = 'camera-status offline';
                    }} else {{
                        document.getElementById('status' + i).className = 'camera-status';
                    }}
                    if (data.is_detecting === true) {{
                        document.getElementById('detection' + i).className = 'detection-status detecting';
                        const lampEl = document.getElementById('meteor-lamp' + i);
                        if (lampEl) {{
                            lampEl.className = 'meteor-lamp on';
                            lampEl.innerHTML = '<span class="dot">●</span>視野内検出 ON';
                        }}
                    }} else {{
                        document.getElementById('detection' + i).className = 'detection-status';
                        const lampEl = document.getElementById('meteor-lamp' + i);
                        if (lampEl) {{
                            lampEl.className = 'meteor-lamp idle';
                            lampEl.innerHTML = '<span class="dot">●</span>視野内検出 OFF';
                        }}
                    }}
                    const maskActive = data.mask_active === true;
                    const maskStatusEl = document.getElementById('mask-status' + i);
                    if (maskStatusEl) {{
                        maskStatusEl.className = maskActive ? 'mask-status active' : 'mask-status';
                    }}
                }})
                .catch(() => {{
                    if (dashboardBackgroundPaused) {{
                        return;
                    }}
                    cameraStatsState[i].delay = Math.min(cameraStatsState[i].delay * 2, maxDelay);
                    document.getElementById('status' + i).className = 'camera-status offline';
                    document.getElementById('detection' + i).className = 'detection-status';
                    const lampEl = document.getElementById('meteor-lamp' + i);
                    if (lampEl) {{
                        lampEl.className = 'meteor-lamp idle';
                        lampEl.innerHTML = '<span class="dot">●</span>視野内検出 OFF';
                    }}
                }})
                .finally(() => {{
                    scheduleCameraStats(i, cameraStatsState[i].delay);
                }});
        }}

        cameras.forEach((cam, i) => {{
            updateCameraStats(i);
        }});
        updateCameraControlUrls();
        syncDashboardVisibilityState();

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

        function resetMask(i) {{
            const btn = document.querySelectorAll('.mask-reset-btn')[i];
            if (!btn) return;
            if (!confirm('マスクをリセットしますか?')) return;
            btn.disabled = true;
            btn.textContent = 'リセット中...';
            fetch('/camera_mask_reset/' + i, {{ method: 'POST' }})
                .then(r => r.json())
                .then(data => {{
                    btn.textContent = data.success ? 'リセット完了' : '失敗';
                    if (data.success) {{
                        const maskStatusEl = document.getElementById('mask-status' + i);
                        if (maskStatusEl) {{
                            maskStatusEl.className = 'mask-status';
                        }}
                    }}
                }})
                .catch(() => {{
                    btn.textContent = '失敗';
                }})
                .finally(() => {{
                    setTimeout(() => {{
                        btn.textContent = 'マスクリセット';
                        btn.disabled = false;
                    }}, 1500);
                }});
        }}

        function downloadSnapshot(i) {{
            const cam = cameras[i];
            if (!cam) return;
            const btn = document.querySelectorAll('.snapshot-btn')[i];
            if (!btn) return;

            btn.disabled = true;
            btn.textContent = '保存中...';
            try {{
                const link = document.createElement('a');
                link.href = '/camera_snapshot/' + i + '?download=1&t=' + Date.now();
                link.setAttribute('download', '');
                link.style.display = 'none';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                btn.textContent = '保存要求済み';
            }} catch (_) {{
                btn.textContent = '失敗';
            }} finally {{
                setTimeout(() => {{
                    btn.textContent = 'スナップショット保存';
                    btn.disabled = false;
                }}, 1500);
            }}
        }}

        function restartCamera(i) {{
            const cam = cameras[i];
            if (!cam) return;
            if (!confirm(`カメラを再起動しますか?\n${{cam.name}}`)) {{
                return;
            }}
            const btn = document.querySelectorAll('.restart-btn')[i];
            if (!btn) return;
            btn.disabled = true;
            btn.textContent = '再起動中...';
            fetch('/camera_restart/' + i, {{ method: 'POST' }})
                .then(r => r.json())
                .then(data => {{
                    btn.textContent = data.success ? '再起動要求済み' : '失敗';
                    document.getElementById('status' + i).className = 'camera-status offline';
                }})
                .catch(() => {{
                    btn.textContent = '失敗';
                }})
                .finally(() => {{
                    setTimeout(() => {{
                        btn.textContent = '再起動';
                        btn.disabled = false;
                    }}, 3000);
                }});
        }}

        function resolveCameraTabUrl(i) {{
            const cam = cameras[i];
            if (!cam || !cam.url) return;
            try {{
                const parsed = new URL(cam.url, window.location.origin);
                const protocol = window.location.protocol || parsed.protocol || 'http:';
                const host = window.location.hostname || parsed.hostname;
                const port = parsed.port || String(8081 + i);
                const path = parsed.pathname && parsed.pathname !== '/' ? parsed.pathname : '/';
                return `${{protocol}}//${{host}}:${{port}}${{path}}`;
            }} catch (_) {{
                return `${{window.location.protocol}}//${{window.location.hostname}}:${{8081 + i}}/`;
            }}
        }}

        function updateCameraControlUrls() {{
            cameras.forEach((_, i) => {{
                const el = document.getElementById('control-url' + i);
                if (!el) return;
                const target = resolveCameraTabUrl(i);
                if (target) {{
                    el.textContent = target;
                }}
            }});
        }}

        function openCameraTab(i) {{
            const target = resolveCameraTabUrl(i);
            if (!target) return;

            const win = window.open('', '_blank');
            if (win) {{
                try {{
                    win.opener = null;
                }} catch (_) {{
                    // noop
                }}
                win.location.href = target;
                try {{
                    win.focus();
                }} catch (_) {{
                    // noop
                }}
                return;
            }}
            // ポップアップがブロックされた場合は同一タブで遷移
            window.location.href = target;
        }}

        // 画像モーダル表示
        function showImage(imagePath, time, camera, confidence) {{
            const imgEl = document.getElementById('modal-image');
            const videoEl = document.getElementById('modal-video');
            const downloadsEl = document.getElementById('modal-downloads');

            imgEl.src = '/image/' + encodeURI(imagePath);
            imgEl.style.display = 'block';
            videoEl.style.display = 'none';
            videoEl.pause();

            document.getElementById('modal-info').innerHTML =
                `${{time}} | ${{camera}} | 信頼度: ${{confidence}}`;
            downloadsEl.innerHTML =
                `<a href="/image/${{encodeURI(imagePath)}}" download>画像をダウンロード</a>`;
            document.getElementById('image-modal').classList.add('active');
        }}

        // 動画モーダル表示
        function showVideo(videoPath, time, camera, confidence) {{
            const imgEl = document.getElementById('modal-image');
            const videoEl = document.getElementById('modal-video');
            const downloadsEl = document.getElementById('modal-downloads');

            videoEl.src = '/image/' + encodeURI(videoPath);
            videoEl.style.display = 'block';
            imgEl.style.display = 'none';
            videoEl.load();
            videoEl.play().catch(() => {{}});

            document.getElementById('modal-info').innerHTML =
                `${{time}} | ${{camera}} | 信頼度: ${{confidence}}`;
            downloadsEl.innerHTML =
                `<a href="/image/${{encodeURI(videoPath)}}" download>動画をダウンロード</a>`;
            document.getElementById('image-modal').classList.add('active');
        }}

        function closeModal() {{
            const videoEl = document.getElementById('modal-video');
            const downloadsEl = document.getElementById('modal-downloads');
            videoEl.pause();
            videoEl.src = '';
            downloadsEl.innerHTML = '';
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

        function setDetectionLabelSelection(groupEl, label) {{
            const normalized = label === 'post_detected' ? 'post_detected' : 'detected';
            groupEl.dataset.label = normalized;
            groupEl.querySelectorAll('input[type="radio"]').forEach((radio) => {{
                radio.checked = radio.value === normalized;
            }});
        }}

        function updateDetectionLabel(camera, time, label, radioEl) {{
            const groupEl = radioEl.closest('.label-radios');
            if (!groupEl) return;
            const normalized = label === 'post_detected' ? 'post_detected' : 'detected';
            const previous = groupEl.dataset.label || 'detected';
            setDetectionLabelSelection(groupEl, normalized);
            fetch('/detection_label', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{ camera, time, label: normalized }})
            }})
            .then(r => r.json())
            .then(data => {{
                if (!data.success) {{
                    throw new Error(data.error || 'update failed');
                }}
                setDetectionLabelSelection(groupEl, normalized);
                lastDetectionsKey = '';
            }})
            .catch((err) => {{
                alert('ラベル更新に失敗しました: ' + err.message);
                setDetectionLabelSelection(groupEl, previous);
            }});
        }}

        function labelToText(label) {{
            return label === 'post_detected' ? 'それ以外' : '流星';
        }}

        function updateLatestDetectionSummary(groupedDetections) {{
            cameras.forEach((cam, i) => {{
                const latest = (groupedDetections && groupedDetections[cam.name] && groupedDetections[cam.name][0])
                    ? groupedDetections[cam.name][0]
                    : null;
                const timeEl = document.getElementById('latest-time' + i);
                const confEl = document.getElementById('latest-confidence' + i);
                const labelEl = document.getElementById('latest-label' + i);
                if (timeEl) timeEl.textContent = latest ? latest.time : '-';
                if (confEl) confEl.textContent = latest ? latest.confidence : '-';
                if (labelEl) labelEl.textContent = latest ? labelToText(latest.label) : '-';
            }});
        }}

        let lastDetectionsKey = '';
        let lastDetectionsMtime = 0;
        const detectionPollBaseDelay = 5000;
        const detectionPollMaxDelay = 30000;
        const detectionWindowIdleDelay = 60000;
        let detectionPollDelay = detectionPollBaseDelay;
        detectionPollTimer = null;
        document.addEventListener('visibilitychange', syncDashboardVisibilityState);

        function scheduleDetectionPoll(delay) {{
            if (dashboardBackgroundPaused) {{
                return;
            }}
            if (detectionPollTimer) {{
                clearTimeout(detectionPollTimer);
            }}
            detectionPollTimer = setTimeout(pollDetections, delay);
        }}

        // 検出一覧を更新
        function updateDetections() {{
            if (dashboardBackgroundPaused) {{
                return Promise.resolve();
            }}
            return fetch('/detections', {{ cache: 'no-store' }})
                .then(r => r.json())
                .then(data => {{
                    if (dashboardBackgroundPaused) {{
                        return;
                    }}
                    detectionPollDelay = detectionPollBaseDelay;
                    document.getElementById('total-detections').textContent = data.total;
                    if (data.recent.length > 0) {{
                        const detectionsKey = data.recent.map(d =>
                            `${{d.camera}}|${{d.time}}|${{d.confidence}}|${{d.image}}|${{d.mp4}}|${{d.composite_original}}|${{d.label || ''}}`
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
                        updateLatestDetectionSummary(grouped);

                        const cameraOrder = cameras.map(cam => cam.name).filter(name => grouped[name]);
                        Object.keys(grouped).forEach(name => {{
                            if (!cameraOrder.includes(name)) {{
                                cameraOrder.push(name);
                            }}
                        }});

                        cameraOrder.sort((a, b) => {{
                            const aMatch = a.match(/(\\d+)$/);
                            const bMatch = b.match(/(\\d+)$/);
                            if (aMatch && bMatch) {{
                                return Number(aMatch[1]) - Number(bMatch[1]);
                            }}
                            return a.localeCompare(b);
                        }});

                        const html = cameraOrder.map(camera => {{
                            const items = grouped[camera].map((d, idx) => {{
                                const thumb = d.image
                                    ? `<img class="detection-thumb" src="/image/${{encodeURI(d.image)}}" alt="${{camera}}" loading="lazy" onclick="showImage('${{d.image}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">`
                                    : '';
                                const normalizedLabel = d.label === 'post_detected' ? 'post_detected' : 'detected';
                                const radioName = `label-${{d.camera}}-${{d.time}}-${{idx}}`.replace(/[^a-zA-Z0-9_-]/g, '_');
                                return `
                                    <div class="detection-item">
                                        <div class="time">${{d.time}}</div>
                                        ${{thumb}}
                                        <div>信頼度: ${{d.confidence}}</div>
                                        <div class="detection-actions">
                                            <div class="detection-view-actions">
                                                <span class="detection-link" onclick="showVideo('${{d.mp4}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">VIDEO</span>
                                                <span class="detection-link" onclick="showImage('${{d.image}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">合成</span>
                                                <span class="detection-link" onclick="showImage('${{d.composite_original}}', '${{d.time}}', '${{d.camera}}', '${{d.confidence}}')">元画像</span>
                                            </div>
                                            <div class="detection-manage-actions">
                                                <div class="label-radios" data-label="${{normalizedLabel}}">
                                                    <label class="label-radio">
                                                        <input type="radio" name="${{radioName}}" value="detected" ${{normalizedLabel === 'detected' ? 'checked' : ''}}
                                                               onchange="updateDetectionLabel('${{d.camera}}', '${{d.time}}', 'detected', this)">
                                                        <span>流星</span>
                                                    </label>
                                                    <label class="label-radio">
                                                        <input type="radio" name="${{radioName}}" value="post_detected" ${{normalizedLabel === 'post_detected' ? 'checked' : ''}}
                                                               onchange="updateDetectionLabel('${{d.camera}}', '${{d.time}}', 'post_detected', this)">
                                                        <span>それ以外</span>
                                                    </label>
                                                </div>
                                                <button class="delete-btn" onclick="deleteDetection('${{d.camera}}', '${{d.time}}', event)">削除</button>
                                            </div>
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
                        updateLatestDetectionSummary(null);
                        document.getElementById('detection-list').innerHTML = '<div class="detection-item" style="color:#666">検出待機中...</div>';
                    }}
                }})
                .catch(err => {{
                    detectionPollDelay = Math.min(detectionPollDelay * 2, detectionPollMaxDelay);
                    console.warn('Detections fetch error:', err);
                    updateLatestDetectionSummary(null);
                }});
        }}

        function pollDetections() {{
            if (dashboardBackgroundPaused) {{
                return;
            }}
            if (detectionWindowState.enabled && !isWithinDetectionWindow()) {{
                scheduleDetectionPoll(detectionWindowIdleDelay);
                return;
            }}
            fetch('/detections_mtime', {{ cache: 'no-store' }})
                .then(r => r.json())
                .then(data => {{
                    detectionPollDelay = detectionPollBaseDelay;
                    const mtime = data.mtime || 0;
                    if (mtime !== lastDetectionsMtime) {{
                        lastDetectionsMtime = mtime;
                        return updateDetections();
                    }}
                }})
                .catch(err => {{
                    detectionPollDelay = Math.min(detectionPollDelay * 2, detectionPollMaxDelay);
                    console.warn('Detections mtime fetch error:', err);
                }})
                .finally(() => {{
                    scheduleDetectionPoll(detectionPollDelay);
                }});
        }}

        // 初回表示時は検出時間帯に関係なく一覧を取得し、その後差分ポーリングへ移行
        updateDetections()
            .finally(() => {{
                pollDetections();
            }});

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


def render_dashboard_settings_html(cameras, version):
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Meteor Dashboard Settings</title>
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            background: #111a30;
            color: #e6edff;
            margin: 0;
            padding: 22px;
        }}
        .container {{
            max-width: 980px;
            margin: 0 auto;
            background: #1b2645;
            border: 1px solid #2a3f6f;
            border-radius: 12px;
            padding: 18px;
        }}
        h1 {{
            margin: 0 0 8px;
            color: #00d4ff;
            font-size: 1.6em;
        }}
        .subtitle {{
            color: #9bb1d8;
            margin-bottom: 16px;
            font-size: 0.9em;
        }}
        .actions {{
            margin-bottom: 16px;
        }}
        .back-link {{
            color: #7bf3be;
            text-decoration: none;
            font-size: 0.9em;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 12px;
        }}
        .field {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .field label {{
            color: #a7badc;
            font-size: 0.8em;
        }}
        .field input, .field select {{
            background: #0f1730;
            color: #e6edff;
            border: 1px solid #2a3f6f;
            border-radius: 6px;
            padding: 8px;
        }}
        .checks {{
            margin-top: 10px;
            display: flex;
            gap: 14px;
            flex-wrap: wrap;
        }}
        .checks label {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            color: #c6d5f0;
            font-size: 0.9em;
        }}
        .submit-row {{
            margin-top: 14px;
            display: flex;
            gap: 12px;
            align-items: center;
        }}
        .apply-btn {{
            background: #2a3f6f;
            color: #00d4ff;
            border: 1px solid #00d4ff;
            border-radius: 6px;
            padding: 9px 14px;
            cursor: pointer;
        }}
        .apply-btn:hover {{
            background: #00d4ff;
            color: #0f1530;
        }}
        .apply-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .message {{
            color: #9bb1d8;
            font-size: 0.9em;
        }}
        .message.ok {{ color: #7bf3be; }}
        .message.error {{ color: #ff8c8c; }}
        .footer {{
            margin-top: 18px;
            color: #6f84ad;
            font-size: 0.82em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>全カメラ設定メニュー</h1>
        <div class="subtitle">対象カメラ数: {len(cameras)} / version {version}</div>
        <div class="actions"><a class="back-link" href="/">← ダッシュボードへ戻る</a></div>

        <div class="grid">
            <div class="field"><label>sensitivity</label><select id="sensitivity">
                <option value="low">low</option><option value="medium">medium</option>
                <option value="high">high</option><option value="fireball">fireball</option>
            </select></div>
            <div class="field"><label>diff_threshold</label><input id="diff_threshold" type="number" min="1" max="255" value="30"></div>
            <div class="field"><label>min_brightness</label><input id="min_brightness" type="number" min="1" max="255" value="200"></div>
            <div class="field"><label>min_brightness_tracking</label><input id="min_brightness_tracking" type="number" min="1" max="255" value="160"></div>
            <div class="field"><label>min_length</label><input id="min_length" type="number" min="1" value="20"></div>
            <div class="field"><label>max_length</label><input id="max_length" type="number" min="1" value="5000"></div>
            <div class="field"><label>min_duration</label><input id="min_duration" type="number" step="0.01" min="0" value="0.1"></div>
            <div class="field"><label>max_duration</label><input id="max_duration" type="number" step="0.01" min="0.01" value="12.0"></div>
            <div class="field"><label>min_speed</label><input id="min_speed" type="number" step="0.1" min="0" value="50"></div>
            <div class="field"><label>min_linearity</label><input id="min_linearity" type="number" step="0.01" min="0" max="1" value="0.7"></div>
            <div class="field"><label>min_area</label><input id="min_area" type="number" min="1" value="5"></div>
            <div class="field"><label>max_area</label><input id="max_area" type="number" min="1" value="10000"></div>
            <div class="field"><label>max_gap_time</label><input id="max_gap_time" type="number" step="0.1" min="0" value="2.0"></div>
            <div class="field"><label>max_distance</label><input id="max_distance" type="number" step="0.1" min="1" value="80"></div>
            <div class="field"><label>merge_max_gap_time</label><input id="merge_max_gap_time" type="number" step="0.1" min="0" value="1.5"></div>
            <div class="field"><label>merge_max_distance</label><input id="merge_max_distance" type="number" step="0.1" min="1" value="80"></div>
            <div class="field"><label>merge_max_speed_ratio</label><input id="merge_max_speed_ratio" type="number" step="0.01" min="0" value="0.5"></div>
            <div class="field"><label>exclude_bottom</label><input id="exclude_bottom" type="number" step="0.01" min="0" max="0.5" value="0.0625"></div>
            <div class="field"><label>scale (再起動で有効)</label><input id="scale" type="number" step="0.01" min="0.1" max="1.0" value="0.5"></div>
            <div class="field"><label>buffer (再起動で有効)</label><input id="buffer" type="number" step="0.1" min="1" value="12"></div>
            <div class="field"><label>mask_dilate</label><input id="mask_dilate" type="number" min="0" value="20"></div>
        </div>

        <div class="checks">
            <label><input id="extract_clips" type="checkbox" checked> extract_clips</label>
            <label><input id="fb_normalize" type="checkbox"> fb_normalize</label>
            <label><input id="fb_delete_mov" type="checkbox"> fb_delete_mov</label>
        </div>

        <div class="submit-row">
            <button class="apply-btn" id="apply-btn" onclick="applyAll()">全カメラへ反映</button>
            <div class="message" id="msg"></div>
        </div>
        <div class="footer">注: scale/buffer は再起動後に有効になります。</div>
    </div>
    <script>
        function setMsg(text, cls='') {{
            const el = document.getElementById('msg');
            el.textContent = text || '';
            el.className = 'message' + (cls ? (' ' + cls) : '');
        }}
        function num(id) {{
            return Number(document.getElementById(id).value);
        }}
        function applyAll() {{
            const btn = document.getElementById('apply-btn');
            const payload = {{
                sensitivity: document.getElementById('sensitivity').value,
                diff_threshold: num('diff_threshold'),
                min_brightness: num('min_brightness'),
                min_brightness_tracking: num('min_brightness_tracking'),
                min_length: num('min_length'),
                max_length: num('max_length'),
                min_duration: num('min_duration'),
                max_duration: num('max_duration'),
                min_speed: num('min_speed'),
                min_linearity: num('min_linearity'),
                min_area: num('min_area'),
                max_area: num('max_area'),
                max_gap_time: num('max_gap_time'),
                max_distance: num('max_distance'),
                merge_max_gap_time: num('merge_max_gap_time'),
                merge_max_distance: num('merge_max_distance'),
                merge_max_speed_ratio: num('merge_max_speed_ratio'),
                exclude_bottom: num('exclude_bottom'),
                scale: num('scale'),
                buffer: num('buffer'),
                mask_dilate: num('mask_dilate'),
                extract_clips: document.getElementById('extract_clips').checked,
                fb_normalize: document.getElementById('fb_normalize').checked,
                fb_delete_mov: document.getElementById('fb_delete_mov').checked,
            }};
            btn.disabled = true;
            btn.textContent = '反映中...';
            setMsg('全カメラへ反映中...');
            fetch('/apply_settings_all', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload),
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    setMsg('反映完了 (' + data.success_count + '/' + data.total + ')', 'ok');
                }} else {{
                    const failed = Array.isArray(data.results) ? data.results.filter(x => !x.success).map(x => x.camera).join(', ') : '';
                    setMsg('一部失敗 (' + (data.success_count || 0) + '/' + (data.total || 0) + ')' + (failed ? (' ' + failed) : ''), 'error');
                }}
            }})
            .catch((err) => {{
                setMsg('反映失敗: ' + err.message, 'error');
            }})
            .finally(() => {{
                btn.disabled = false;
                btn.textContent = '全カメラへ反映';
            }});
        }}
        // 初期値はcamera_stats/0のsettingsを使う
        fetch('/camera_stats/0', {{ cache: 'no-store' }})
            .then(r => r.json())
            .then(data => {{
                const s = data && data.settings ? data.settings : null;
                if (!s) return;
                const setVal = (id, key) => {{
                    const el = document.getElementById(id);
                    if (!el || !(key in s)) return;
                    if (el.type === 'checkbox') el.checked = !!s[key];
                    else el.value = s[key];
                }};
                [
                    'sensitivity','diff_threshold','min_brightness','min_brightness_tracking',
                    'min_length','max_length','min_duration','max_duration','min_speed',
                    'min_linearity','min_area','max_area','max_gap_time','max_distance',
                    'merge_max_gap_time','merge_max_distance','merge_max_speed_ratio',
                    'exclude_bottom','scale','buffer','mask_dilate','extract_clips',
                    'fb_normalize','fb_delete_mov'
                ].forEach((k) => setVal(k, k));
            }})
            .catch(() => {{}});
    </script>
</body>
</html>'''
