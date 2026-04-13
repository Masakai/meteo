"""Dashboard HTML rendering."""

import base64
import json
from pathlib import Path

from dashboard_templates_settings import render_settings_html


def _sanitize_cameras_for_js(cameras):
    """ブラウザに送るカメラ情報からsecret(youtube_key等)を除去する"""
    result = []
    for cam in cameras:
        safe = {k: v for k, v in cam.items() if k not in ("youtube_key", "rtsp_url")}
        if cam.get("youtube_key"):
            safe["has_youtube_key"] = True
        result.append(safe)
    return result


def render_stats_html(version):
    logotype_path = Path(__file__).parent / "documents" / "assets" / "meteo-logotype.svg"
    logotype_src = ""
    if logotype_path.exists():
        logotype_bytes = logotype_path.read_bytes()
        logotype_src = "data:image/svg+xml;base64," + base64.b64encode(logotype_bytes).decode("ascii")
    brand_logo_html = f'<img src="{logotype_src}" alt="METEO">' if logotype_src else ""

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <title>流星検出ダッシュボード - 統計</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', system-ui, sans-serif;
            background: #eef2f7;
            color: #192333;
            min-height: 100vh;
            padding: 20px 20px 20px 240px;
            line-height: 1.6;
        }}
        .topnav {{
            display: flex;
            flex-direction: column;
            align-items: stretch;
            gap: 0;
            padding: 24px 14px 20px;
            width: 220px;
            min-height: 100vh;
            background: #0f1c2d;
            border-right: 2px solid #f5a41f;
            position: fixed;
            left: 0;
            top: 0;
            z-index: 100;
            margin: 0;
            overflow-y: auto;
        }}
        .brand-link {{
            display: flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
            flex-shrink: 0;
            margin-bottom: 28px;
            padding: 4px 0;
        }}
        .brand-link img {{
            width: 100%;
            max-width: 160px;
            height: auto;
            display: block;
        }}
        .brand-text {{
            font-family: 'Orbitron', sans-serif;
            color: #dce8f5;
            font-size: 1.2em;
            font-weight: 800;
            letter-spacing: 0.1em;
        }}
        .nav-links {{
            display: flex;
            flex-direction: column;
            gap: 2px;
            flex: 1;
        }}
        .nav-link {{
            display: flex;
            align-items: center;
            padding: 10px 14px;
            border-radius: 7px;
            color: #6a8aaa;
            text-decoration: none;
            font-size: 0.88em;
            font-weight: 500;
            letter-spacing: 0.02em;
            transition: color 0.15s, background 0.15s;
            white-space: nowrap;
            min-height: 40px;
            cursor: pointer;
        }}
        .nav-link:hover {{
            color: #dce8f5;
            background: rgba(255,255,255,0.05);
        }}
        .nav-active {{
            color: #f5a41f;
            font-weight: 600;
            background: rgba(245, 164, 31, 0.10);
        }}
        .page-header {{
            text-align: center;
            padding: 16px 0 20px;
        }}
        .page-header h1 {{
            font-family: 'Orbitron', sans-serif;
            color: #192333;
            font-size: 1.5em;
            font-weight: 600;
            letter-spacing: 0.06em;
            margin-bottom: 8px;
        }}
        .stats-summary {{
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 24px;
            padding: 0;
            background: transparent;
            border-radius: 0;
        }}
        .stats-summary .stat {{
            min-width: 140px;
            padding: 14px 20px 14px 16px;
            background: #ffffff;
            border-radius: 10px;
            border: 1px solid #d0dce8;
            border-left: 3px solid #d4860a;
            box-shadow: 0 1px 4px rgba(0,20,50,0.08);
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .stats-summary .stat-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.9em;
            font-weight: 600;
            color: #d4860a;
            line-height: 1.1;
            white-space: nowrap;
        }}
        .stats-summary .stat-label {{
            color: #7a96b0;
            font-size: 0.82em;
        }}
        .stats-controls {{
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .range-btn {{
            padding: 7px 16px;
            border-radius: 6px;
            border: 1px solid #1a8fc4;
            color: #1a8fc4;
            background: #ffffff;
            font-size: 0.85em;
            cursor: pointer;
            min-height: 44px;
        }}
        .range-btn:hover, .range-btn.active {{
            background: #1a8fc4;
            color: #ffffff;
        }}
        .stats-table-wrap {{
            width: 100%;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9em;
        }}
        thead th {{
            background: #f4f8fb;
            color: #1a8fc4;
            padding: 10px 14px;
            text-align: right;
            border-bottom: 2px solid #d0dce8;
            white-space: nowrap;
        }}
        thead th:first-child {{
            text-align: left;
        }}
        tbody tr {{
            border-bottom: 1px solid #e8eff6;
        }}
        tbody tr:hover {{
            background: rgba(26, 143, 196, 0.06);
        }}
        tbody tr.night-zero {{
            opacity: 0.38;
        }}
        tbody tr.night-ongoing td.night-date::after {{
            content: ' (進行中)';
            color: #d4860a;
            font-size: 0.85em;
        }}
        tbody td {{
            padding: 9px 14px;
            text-align: right;
            font-family: 'JetBrains Mono', monospace;
            color: #192333;
            white-space: nowrap;
        }}
        tbody td:first-child {{
            text-align: left;
            color: #4e6880;
        }}
        .count-total {{
            font-weight: bold;
            color: #d4860a;
        }}
        .loading-msg {{
            text-align: center;
            padding: 40px;
            color: #7a96b0;
        }}
        .chart-wrap {{
            width: 100%;
            margin: 0 0 30px;
            background: #ffffff;
            border: 1px solid #d0dce8;
            box-shadow: 0 1px 4px rgba(0,20,50,0.08);
            border-radius: 10px;
            padding: 16px;
            box-sizing: border-box;
        }}
        .chart-section-label {{
            font-size: 0.85em;
            color: #4e6880;
            font-weight: 600;
            margin: 24px 0 8px;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
        .footer {{
            text-align: center;
            padding: 24px 30px;
            color: #7a96b0;
            font-size: 0.82em;
            border-top: 1px solid #d8e4ef;
            margin-top: 40px;
        }}
        :focus-visible {{
            outline: 2px solid #1a8fc4;
            outline-offset: 2px;
            border-radius: 3px;
        }}
    </style>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
</head>
<body>
    <nav class="topnav">
        <a href="/" class="brand-link">{brand_logo_html}</a>
        <div class="nav-links">
            <a class="nav-link" href="/">検出一覧</a>
            <a class="nav-link" href="/cameras">カメラ</a>
            <a class="nav-link nav-active" href="/stats" aria-current="page">統計</a>
            <a class="nav-link" href="/settings">設定</a>
        </div>
    </nav>
    <div class="page-header">
        <h1>夜別検出統計</h1>
    </div>

    <main>
    <div class="stats-summary">
        <div class="stat">
            <div class="stat-value" id="stat-total-events">-</div>
            <div class="stat-label">総検出数（重複除去後）</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="stat-nights">-</div>
            <div class="stat-label">集計夜数</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="stat-duplicates">-</div>
            <div class="stat-label">重複除去数</div>
        </div>
    </div>

    <div class="stats-controls">
        <button class="range-btn active" data-days="30" onclick="loadStats(30, this)">30夜</button>
        <button class="range-btn" data-days="90" onclick="loadStats(90, this)">90夜</button>
        <button class="range-btn" data-days="180" onclick="loadStats(180, this)">180夜</button>
        <button class="range-btn" data-days="365" onclick="loadStats(365, this)">1年</button>
    </div>

    <div class="chart-wrap" id="chart-wrap" style="display:none">
        <div id="stats-chart" style="width:100%;"></div>
    </div>
    <div class="chart-section-label">時間帯別検出数</div>
    <div class="chart-wrap" id="hourly-chart-wrap" style="display:none">
        <div id="hourly-chart" style="width:100%;"></div>
    </div>

    <div class="stats-table-wrap">
        <div class="loading-msg" id="loading-msg">読み込み中...</div>
        <table id="stats-table" style="display:none">
            <thead>
                <tr id="stats-thead-row">
                    <th>夜（日没日）</th>
                    <th>日没</th>
                    <th>日の出</th>
                    <th id="th-total">合計</th>
                </tr>
            </thead>
            <tbody id="stats-tbody"></tbody>
        </table>
    </div>

    <div class="footer">
        Meteor Detection System v{version}
    </div>

    <script>
        let _currentDays = 30;

        function loadStats(days, btn) {{
            _currentDays = days;
            document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');

            document.getElementById('loading-msg').style.display = '';
            document.getElementById('stats-table').style.display = 'none';

            fetch('/stats_data?days=' + days, {{ cache: 'no-store' }})
                .then(r => r.json())
                .then(data => renderStats(data))
                .catch(err => {{
                    document.getElementById('loading-msg').textContent = '読み込みに失敗しました: ' + err;
                }});
        }}

        function renderStats(data) {{
            const nights = data.nights || [];
            const cameras = data.cameras || [];
            const totalEvents = data.total_events || 0;

            // ヘッダー更新
            const theadRow = document.getElementById('stats-thead-row');
            // カメラ列を再構築
            const fixedCols = 4; // 夜・日没・日の出・合計
            while (theadRow.children.length > fixedCols) {{
                theadRow.removeChild(theadRow.children[fixedCols - 1]);
            }}
            // 合計の前にカメラ列を挿入
            const thTotal = document.getElementById('th-total');
            cameras.forEach(cam => {{
                const th = document.createElement('th');
                th.textContent = cam;
                theadRow.insertBefore(th, thTotal);
            }});

            // サマリー
            const totalDups = nights.reduce((s, n) => s + (n.duplicates || 0), 0);
            document.getElementById('stat-total-events').textContent = totalEvents;
            document.getElementById('stat-nights').textContent = nights.length;
            document.getElementById('stat-duplicates').textContent = totalDups;

            // 行生成
            const tbody = document.getElementById('stats-tbody');
            tbody.innerHTML = '';
            nights.forEach(night => {{
                const tr = document.createElement('tr');
                if (night.total === 0) tr.classList.add('night-zero');
                if (night.ongoing) tr.classList.add('night-ongoing');

                const tdDate = document.createElement('td');
                tdDate.className = 'night-date';
                tdDate.textContent = night.date;
                tr.appendChild(tdDate);

                const tdSunset = document.createElement('td');
                tdSunset.textContent = night.sunset ? night.sunset.slice(11) : '';
                tr.appendChild(tdSunset);

                const tdSunrise = document.createElement('td');
                tdSunrise.textContent = night.sunrise ? night.sunrise.slice(11) : '';
                tr.appendChild(tdSunrise);

                cameras.forEach(cam => {{
                    const td = document.createElement('td');
                    td.textContent = (night.by_camera && night.by_camera[cam] != null)
                        ? night.by_camera[cam] : 0;
                    tr.appendChild(td);
                }});

                const tdTotal = document.createElement('td');
                tdTotal.className = 'count-total';
                tdTotal.textContent = night.total;
                tr.appendChild(tdTotal);

                tbody.appendChild(tr);
            }});

            document.getElementById('loading-msg').style.display = 'none';
            document.getElementById('stats-table').style.display = '';

            // Plotly 積み重ねグラフ
            renderChart(nights, cameras);
            renderHourlyChart(data.hourly);
        }}

        const CAMERA_COLORS = ['#1a8fc4', '#d4860a', '#1d9e60', '#cc3333', '#7b4dc4'];

        function renderChart(nights, cameras) {{
            const chartEl = document.getElementById('stats-chart');
            // 日付昇順（左が古い）
            const sorted = nights.slice().reverse();
            const dates = sorted.map(n => n.date);

            const traces = cameras.map((cam, i) => ({{
                x: dates,
                y: sorted.map(n => (n.by_camera && n.by_camera[cam] != null) ? n.by_camera[cam] : 0),
                name: cam,
                type: 'bar',
                marker: {{ color: CAMERA_COLORS[i % CAMERA_COLORS.length] }},
            }}));

            const layout = {{
                barmode: 'stack',
                autosize: true,
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: {{ color: '#4e6880', size: 12 }},
                xaxis: {{
                    type: 'category',
                    tickangle: -45,
                    tickfont: {{ size: 11 }},
                    gridcolor: '#d8e4ef',
                    linecolor: '#d8e4ef',
                }},
                yaxis: {{
                    title: '検出数',
                    gridcolor: '#d8e4ef',
                    linecolor: '#d8e4ef',
                    dtick: 1,
                }},
                legend: {{ orientation: 'h', x: 0, y: 1.12 }},
                margin: {{ t: 40, b: 80, l: 50, r: 20 }},
                height: 280,
            }};

            Plotly.react(chartEl, traces, layout, {{ responsive: true, useResizeHandler: true, displayModeBar: false }});
            Plotly.Plots.resize(chartEl);
            document.getElementById('chart-wrap').style.display = '';
        }}

        function renderHourlyChart(hourly) {{
            if (!hourly || !hourly.cameras || hourly.cameras.length === 0) return;
            const chartEl = document.getElementById('hourly-chart');
            const hours = hourly.hours || [...Array(24).keys()];
            const hourLabels = hours.map(h => h + '時');
            const traces = hourly.cameras.map((cam, i) => ({{
                x: hourLabels,
                y: hourly.by_hour[cam] || new Array(24).fill(0),
                name: cam,
                type: 'bar',
                marker: {{ color: CAMERA_COLORS[i % CAMERA_COLORS.length] }},
            }}));
            const layout = {{
                barmode: 'group',
                autosize: true,
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: {{ color: '#4e6880', size: 12 }},
                xaxis: {{
                    type: 'category',
                    tickfont: {{ size: 11 }},
                    gridcolor: '#d8e4ef',
                    linecolor: '#d8e4ef',
                }},
                yaxis: {{
                    title: '検出数',
                    gridcolor: '#d8e4ef',
                    linecolor: '#d8e4ef',
                    dtick: 1,
                }},
                legend: {{ orientation: 'h', x: 0, y: 1.12 }},
                margin: {{ t: 40, b: 60, l: 50, r: 20 }},
                height: 240,
            }};
            Plotly.react(chartEl, traces, layout,
                {{ responsive: true, useResizeHandler: true, displayModeBar: false }});
            Plotly.Plots.resize(chartEl);
            document.getElementById('hourly-chart-wrap').style.display = '';
        }}

        loadStats(30, document.querySelector('.range-btn[data-days="30"]'));
    </script>
    </main>
</body>
</html>'''


def render_dashboard_html(cameras, version, server_start_time, page_mode="detections"):
    fps_warning_ratio = 0.8
    is_camera_page = page_mode == "cameras"
    is_detections_page = not is_camera_page
    logotype_path = Path(__file__).parent / "documents" / "assets" / "meteo-logotype.svg"
    logotype_src = ""
    if logotype_path.exists():
        logotype_bytes = logotype_path.read_bytes()
        logotype_src = "data:image/svg+xml;base64," + base64.b64encode(logotype_bytes).decode("ascii")
    brand_logo_html = f'<img src="{logotype_src}" alt="METEO">' if logotype_src else ""
    # カメラグリッドを生成
    camera_cards = ""
    if is_camera_page:
        for i, cam in enumerate(cameras):
            display_name = cam.get('display_name', cam['name'])
            stream_kind = cam.get('stream_kind', 'webrtc')
            stream_view = f'''
                        <img id="stream{i}" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==" alt="{cam['name']}"
                             data-stream-kind="{stream_kind}">
                        <iframe class="camera-stream-frame" id="stream-frame{i}" title="{display_name} WebRTC"
                                data-stream-kind="{stream_kind}" allow="autoplay; fullscreen; camera; microphone"
                                referrerpolicy="no-referrer" loading="lazy"></iframe>
            '''
            camera_cards += f'''
                <div class="camera-card">
                    <div class="camera-header">
                        <span class="camera-name">{display_name}</span>
                        {'<button class="youtube-btn youtube-btn-header" id="youtube-btn' + str(i) + '" onclick="toggleYouTube(' + str(i) + ')">YouTube Live</button>' if cam.get("youtube_key") else '<button class="youtube-btn youtube-btn-header" disabled aria-disabled="true" title="YouTube配信未設定" style="opacity:0.3;cursor:default;">YouTube Live</button>'}
                        <div class="status-indicators">
                            <span class="camera-status indicator-help" id="status{i}" role="img" aria-label="ストリーム接続状態" title="ストリーム接続" data-help="ストリーム接続状態（緑: 接続中 / 赤: 切断 / 灰: 常時表示オフ）">●</span>
                            <span class="server-status unknown indicator-help" id="server-status{i}" role="img" aria-label="カメラサーバ状態" title="カメラサーバ生存" data-help="カメラサーバ生存状態（緑: 応答あり / 赤: 応答なし / 灰: 判定保留）">●</span>
                            <span class="detection-status indicator-help" id="detection{i}" role="img" aria-label="検出処理状態" title="検出処理" data-help="検出処理状態（赤点滅: 検出中 / 緑: 期間外 / 黄: 期間内だが停止疑い / 灰: 状態確認中）">●</span>
                            <span class="mask-status indicator-help" id="mask-status{i}" role="img" aria-label="マスク適用状態" title="マスク適用" data-help="マスク適用状態（赤: マスク有効 / 灰: マスク無効）">MASK</span>
                        </div>
                    </div>
                    <div class="camera-actions">
                        <label class="stream-toggle-label" title="ON時は常時ライブ表示します">
                            <input type="checkbox" id="stream-toggle{i}" checked onchange="toggleStreamEnabled({i}, this.checked)">
                            <span>常時表示</span>
                        </label>
                        <button class="record-btn" id="record-btn{i}" onclick="toggleRecordingPanel({i})">録画予約</button>
                        <button class="mask-btn" onclick="updateMask({i})">マスク更新</button>
                        <button class="snapshot-btn" onclick="downloadSnapshot({i})">スナップショット保存</button>
                        <button class="restart-btn" onclick="restartCamera({i})">再起動</button>
                        <button class="mask-preview-btn" id="mask-btn{i}" onclick="toggleMask({i})">マスク表示</button>
                    </div>
                    <div class="recording-panel" id="recording-panel{i}" hidden>
                        <div class="recording-form">
                            <label>
                                <span>開始</span>
                                <input type="datetime-local" id="recording-start{i}" step="1">
                            </label>
                            <label>
                                <span>秒数</span>
                                <input type="number" id="recording-duration{i}" min="1" max="86400" step="1" value="60">
                            </label>
                            <button class="record-now-btn" type="button" onclick="setRecordingStartNow({i})">今すぐ</button>
                            <button class="record-submit-btn" type="button" id="recording-submit{i}" onclick="scheduleRecording({i})">実行</button>
                            <button class="record-stop-btn" type="button" id="recording-stop{i}" onclick="stopRecording({i})">停止</button>
                        </div>
                        <div class="recording-status" id="recording-status{i}">録画待機</div>
                    </div>
                    <div class="camera-video">
{stream_view}
                        <img class="mask-overlay" id="mask{i}" data-src="/camera_mask_image/{i}" alt="mask"
                             onerror="this.style.display='none'; this.dataset.visible='';">
                        <div class="camera-error" id="error{i}">
                            <span>接続中...</span>
                        </div>
                    </div>
                    <div class="camera-stats">
                        <span>検出: <b id="count{i}">-</b></span>
                        <span class="recording-summary" id="recording-summary{i}">録画: 待機</span>
                        <span class="camera-params" id="params{i}"></span>
                    </div>
                </div>
                '''

    page_title = "流星検出ダッシュボード - カメラ" if is_camera_page else "流星検出ダッシュボード - 検出一覧"
    page_heading = "カメラライブ" if is_camera_page else "最近の検出"
    _active_detections = '' if is_camera_page else ' nav-active'
    _active_cameras = ' nav-active' if is_camera_page else ''
    _aria_detections = ' aria-current="page"' if not is_camera_page else ''
    _aria_cameras = ' aria-current="page"' if is_camera_page else ''
    nav_items_html = f'''<a class="nav-link{_active_detections}" href="/"{ _aria_detections}>検出一覧</a>
                <a class="nav-link{_active_cameras}" href="/cameras"{ _aria_cameras}>カメラ</a>
                <a class="nav-link" href="/stats">統計</a>
                <a class="nav-link" href="/settings">設定</a>'''
    nav_actions_html = '''<div class="nav-actions">
        <button class="nav-action-btn" type="button" onclick="setGlobalDetectionEnabled(false)">停止</button>
        <button class="nav-action-btn" type="button" onclick="setGlobalDetectionEnabled(true)">再開</button>
    </div>'''
    stats_primary = (
        f'''
        <div class="stat">
            <div class="stat-value" id="active-cameras">{len(cameras)}</div>
            <div class="stat-label">カメラ数</div>
        </div>
        '''
        if is_camera_page
        else '''
        <div class="stat">
            <div class="stat-value" id="total-detections">0</div>
            <div class="stat-label">総検出数</div>
        </div>
        '''
    )
    camera_grid_html = (
        f'''
    <div class="camera-grid">
        {camera_cards}
    </div>
        '''
        if is_camera_page
        else ""
    )
    detections_section_html = (
        '''
    <div class="recent-detections">
        <h3>最近の検出</h3>
        <div class="detection-calendar-toolbar">
            <div class="detection-range-switch" id="detection-range-switch">
                <button type="button" class="range-btn active" data-range="current">今月</button>
                <button type="button" class="range-btn" data-range="previous">先月</button>
                <button type="button" class="range-btn" data-range="3m">過去3ヶ月</button>
                <button type="button" class="range-btn" data-range="6m">過去6ヶ月</button>
                <button type="button" class="range-btn" data-range="1y">過去1年</button>
                <button type="button" class="range-btn" data-range="year">年指定</button>
            </div>
            <label class="year-select-wrap">
                <span>年</span>
                <select id="detection-year-select"></select>
            </label>
        </div>
        <div class="calendar-summary" id="calendar-summary">読み込み中...</div>
        <div class="calendar-grid" id="detection-calendar-grid"></div>
        <h4 class="selected-date-title" id="selected-date-title">日付を選択してください</h4>
        <div class="detection-list" id="detection-list">
            <div class="detection-item" style="color:#94a3b8">検出待機中...</div>
        </div>
    </div>
        '''
        if is_detections_page
        else ""
    )

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <title>{page_title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', system-ui, sans-serif;
            background: #eef2f7;
            color: #192333;
            min-height: 100vh;
            padding: 20px 20px 20px 240px;
            line-height: 1.6;
        }}
        .topnav {{
            display: flex;
            flex-direction: column;
            align-items: stretch;
            gap: 0;
            padding: 24px 14px 20px;
            width: 220px;
            min-height: 100vh;
            background: #0f1c2d;
            border-right: 2px solid #f5a41f;
            position: fixed;
            left: 0;
            top: 0;
            z-index: 100;
            margin: 0;
            overflow-y: auto;
        }}
        .brand-link {{
            display: flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
            flex-shrink: 0;
            margin-bottom: 28px;
            padding: 4px 0;
        }}
        .brand-link img {{
            width: 100%;
            max-width: 160px;
            height: auto;
            display: block;
        }}
        .brand-text {{
            font-family: 'Orbitron', sans-serif;
            color: #dce8f5;
            font-size: 1.2em;
            font-weight: 800;
            letter-spacing: 0.1em;
        }}
        .nav-links {{
            display: flex;
            flex-direction: column;
            gap: 2px;
            flex: 1;
        }}
        .nav-link {{
            display: flex;
            align-items: center;
            padding: 10px 14px;
            border-radius: 7px;
            color: #6a8aaa;
            text-decoration: none;
            font-size: 0.88em;
            font-weight: 500;
            letter-spacing: 0.02em;
            transition: color 0.15s, background 0.15s;
            white-space: nowrap;
            min-height: 40px;
            cursor: pointer;
        }}
        .nav-link:hover {{
            color: #dce8f5;
            background: rgba(255,255,255,0.05);
        }}
        .nav-active {{
            color: #f5a41f;
            font-weight: 600;
            background: rgba(245, 164, 31, 0.10);
        }}
        .nav-actions {{
            display: flex;
            flex-direction: column;
            gap: 6px;
            flex-shrink: 0;
            margin-top: auto;
            padding-top: 20px;
            border-top: 1px solid #2a4a6a;
        }}
        .nav-action-btn {{
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 0.82em;
            cursor: pointer;
            min-height: 36px;
            border: 1px solid #2a4a6a;
            background: #122440;
            color: #6a8aaa;
            transition: all 0.15s;
            width: 100%;
            text-align: left;
        }}
        .nav-action-btn:hover {{
            border-color: #5ab4e0;
            color: #dce8f5;
        }}
        .page-header {{
            text-align: center;
            padding: 16px 0 20px;
        }}
        .page-header h1 {{
            font-family: 'Orbitron', sans-serif;
            color: #192333;
            font-size: 1.5em;
            font-weight: 600;
            letter-spacing: 0.06em;
            margin-bottom: 8px;
        }}
        .hero-clock {{
            color: #d4860a;
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.15em;
            font-variant-numeric: tabular-nums;
            letter-spacing: 0.04em;
        }}
        .stats-bar {{
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 24px;
            padding: 0;
            background: transparent;
            border-radius: 0;
            align-items: stretch;
        }}
        .stats-bar .stat {{
            min-width: 140px;
            padding: 14px 20px 14px 16px;
            background: #ffffff;
            border-radius: 10px;
            border: 1px solid #d0dce8;
            border-left: 3px solid #d4860a;
            box-shadow: 0 1px 4px rgba(0,20,50,0.08);
            display: flex;
            flex-direction: column;
            gap: 4px;
            justify-content: flex-end;
        }}
        .stats-bar .stat-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.9em;
            font-weight: 600;
            color: #d4860a;
            line-height: 1.1;
            white-space: nowrap;
        }}
        #detection-window {{
            font-size: 1.5em;
            white-space: nowrap;
        }}
        .stat-wide {{
            min-width: 200px;
        }}
        .stats-bar .stat-label {{
            color: #7a96b0;
            font-size: 0.82em;
        }}
        .camera-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            max-width: 1800px;
            margin: 0 auto;
        }}
        .camera-card {{
            background: #ffffff;
            border-radius: 10px;
            overflow: hidden;
            border: 1px solid #d0dce8;
            box-shadow: 0 1px 4px rgba(0,20,50,0.08);
        }}
        .camera-header {{
            display: flex;
            justify-content: flex-start;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            background: #f4f8fb;
            border-bottom: 1px solid #d8e4ef;
        }}
        .camera-name {{
            font-family: 'Orbitron', sans-serif;
            font-weight: bold;
            color: #1a8fc4;
        }}
        .status-indicators {{
            display: flex;
            gap: 8px;
            margin-left: auto;
        }}
        .youtube-btn-header {{
            padding: 2px 8px;
            font-size: 0.72em;
            line-height: 1;
            border-radius: 4px;
            flex-shrink: 0;
            vertical-align: middle;
        }}
        .indicator-help {{
            position: relative;
            cursor: help;
        }}
        .indicator-help:hover::after {{
            content: attr(data-help);
            position: absolute;
            top: calc(100% + 6px);
            right: 0;
            min-width: 220px;
            max-width: 320px;
            padding: 8px 10px;
            border-radius: 6px;
            background: rgba(15, 28, 45, 0.95);
            border: 1px solid #2a4a6a;
            color: #f0f6ff;
            font-size: 12px;
            line-height: 1.45;
            white-space: normal;
            z-index: 20;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
            pointer-events: none;
        }}
        .camera-status {{
            color: #3dd68c;
            font-size: 0.8em;
        }}
        .camera-status.offline {{
            color: #ff4444;
        }}
        .camera-status.paused {{
            color: #6a8aaa;
        }}
        .server-status {{
            color: #3dd68c;
            font-size: 0.8em;
        }}
        .server-status.offline {{
            color: #ff4444;
        }}
        .server-status.unknown {{
            color: #6a8aaa;
        }}
        .detection-status {{
            color: #6a8aaa;
            font-size: 0.8em;
        }}
        .detection-status.detecting {{
            color: #ff4444;
            animation: blink 1s infinite;
        }}
        .detection-status.inactive {{
            color: #58d68d;
        }}
        .detection-status.paused {{
            color: #f5b041;
        }}
        .detection-status.warning {{
            color: #f4d03f;
        }}
        .detection-status.unknown {{
            color: #6a8aaa;
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
            background: #f4f8fb;
            border-bottom: 1px solid #d8e4ef;
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }}
        .stream-toggle-label {{
            margin-right: auto;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            color: #4e6880;
            font-size: 0.78em;
            cursor: pointer;
            user-select: none;
        }}
        .stream-toggle-label input {{
            accent-color: #1a8fc4;
            cursor: pointer;
        }}
        .mask-btn {{
            background: #f0f7fc;
            border: 1px solid #1a8fc4;
            color: #1a8fc4;
            padding: 8px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
            min-height: 44px;
        }}
        .mask-btn:hover {{
            background: #1a8fc4;
            color: #ffffff;
        }}
        .mask-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .record-btn {{
            background: #fef8ed;
            border: 1px solid #d4860a;
            color: #8a5800;
            padding: 8px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
            min-height: 44px;
        }}
        .record-btn:hover {{
            background: #d4860a;
            color: #ffffff;
        }}
        .recording-panel {{
            padding: 10px 12px;
            background: #f4f8fb;
            border-bottom: 1px solid #d8e4ef;
        }}
        .recording-form {{
            display: flex;
            gap: 8px;
            align-items: flex-end;
            flex-wrap: wrap;
        }}
        .recording-form label {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            color: #4e6880;
            font-size: 0.78em;
        }}
        .recording-form input {{
            min-width: 150px;
            padding: 6px 8px;
            border-radius: 6px;
            border: 1px solid #d0dce8;
            background: #ffffff;
            color: #192333;
        }}
        .record-now-btn,
        .record-submit-btn,
        .record-stop-btn {{
            padding: 6px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
            min-height: 44px;
        }}
        .record-now-btn {{
            background: #f0f7fc;
            border: 1px solid #1a8fc4;
            color: #1a6090;
        }}
        .record-submit-btn {{
            background: #f0faf3;
            border: 1px solid #1d9e60;
            color: #0e5c30;
        }}
        .record-stop-btn {{
            background: #fff0f0;
            border: 1px solid #cc3333;
            color: #991111;
        }}
        .recording-status {{
            margin-top: 8px;
            color: #4e6880;
            font-size: 0.8em;
        }}
        .recording-status.scheduled {{
            color: #d4860a;
        }}
        .recording-status.recording {{
            color: #cc3333;
        }}
        .recording-status.completed {{
            color: #1d9e60;
        }}
        .recording-status.failed,
        .recording-status.stopped {{
            color: #ff9d9d;
        }}
        .snapshot-btn {{
            background: #f0faf8;
            border: 1px solid #1d9e80;
            color: #0e5c4a;
            padding: 8px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
            min-height: 44px;
        }}
        .snapshot-btn:hover {{
            background: #1d9e80;
            color: #ffffff;
        }}
        .snapshot-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .restart-btn {{
            background: #fff0f0;
            border: 1px solid #cc3333;
            color: #991111;
            padding: 8px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
            min-height: 44px;
        }}
        .restart-btn:hover {{
            background: #cc3333;
            color: #ffffff;
        }}
        .restart-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .youtube-btn {{
            background: #fff0f0;
            border: 1px solid #cc2222;
            color: #991111;
            padding: 8px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
            min-height: 44px;
        }}
        .youtube-btn:hover {{
            background: #ff4444;
            color: #fff;
        }}
        .youtube-btn.active {{
            background: #ff4444;
            color: #fff;
            animation: youtube-pulse 2s infinite;
        }}
        .youtube-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        @keyframes youtube-pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            @keyframes blink {{ 0%, 100% {{ opacity: 1; }} }}
            .detection-status.detecting {{ animation: none; opacity: 0.75; }}
            @keyframes youtube-pulse {{ 0%, 100% {{ opacity: 1; }} }}
            .youtube-btn.active {{ animation: none; }}
        }}
        .mask-preview-btn {{
            background: #fff0f0;
            border: 1px solid #cc3333;
            color: #cc3333;
            padding: 8px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8em;
            min-height: 44px;
        }}
        .mask-preview-btn:hover {{
            background: #cc3333;
            color: #ffffff;
        }}
        .mask-preview-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        .camera-video img,
        .camera-video iframe {{
            width: 100%;
            height: 100%;
            object-fit: contain;
            border: 0;
        }}
        .camera-stream-frame {{
            display: none;
            background: #000;
        }}
        .mask-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: none;
            pointer-events: none;
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
            color: #6a8aaa;
        }}
        .camera-stats {{
            padding: 10px 15px;
            background: #f4f8fb;
            font-size: 0.9em;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .camera-stats b {{
            color: #d4860a;
        }}
        .camera-params {{
            font-size: 0.8em;
            color: #6a8aaa;
        }}
        .recording-summary {{
            color: #cbd9f8;
            font-size: 0.8em;
        }}
        .camera-params .param {{
            display: inline-block;
            background: #e8f0f8;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 4px;
        }}
        .camera-params .param-clip {{
            color: #1d9e60;
        }}
        .camera-params .param-no-clip {{
            color: #d4500a;
        }}
        .camera-params .param-fps-warning {{
            background: #fef3cd;
            color: #8a5800;
        }}
        .mask-status {{
            color: #7a96b0;
            border: 1px solid #7a96b0;
            font-size: 0.65em;
            padding: 1px 4px;
            border-radius: 4px;
        }}
        .mask-status.active {{
            color: #cc2222;
            border-color: #cc2222;
        }}
        .recent-detections {{
            max-width: 1800px;
            margin: 30px auto 0;
            padding: 20px;
            background: #ffffff;
            border: 1px solid #d0dce8;
            box-shadow: 0 1px 4px rgba(0,20,50,0.08);
            border-radius: 12px;
        }}
        .recent-detections h3 {{
            color: #192333;
            font-family: 'Orbitron', sans-serif;
            font-size: 0.95em;
            letter-spacing: 0.06em;
            margin-bottom: 15px;
        }}
        .detection-calendar-toolbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
            margin-bottom: 14px;
        }}
        .detection-range-switch {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .range-btn {{
            background: #ffffff;
            border: 1px solid #d0dce8;
            color: #4e6880;
            padding: 8px 12px;
            border-radius: 999px;
            cursor: pointer;
            font-size: 0.85em;
            min-height: 44px;
        }}
        .range-btn.active {{
            background: #1a8fc4;
            color: #ffffff;
            border-color: #1a8fc4;
            font-weight: bold;
        }}
        .year-select-wrap {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #4e6880;
            font-size: 0.9em;
        }}
        .year-select-wrap select {{
            background: #ffffff;
            border: 1px solid #d0dce8;
            color: #192333;
            border-radius: 8px;
            padding: 8px 10px;
        }}
        .calendar-summary {{
            color: #7a9ab8;
            margin-bottom: 14px;
            font-size: 0.9em;
        }}
        .calendar-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin-bottom: 22px;
        }}
        .calendar-month {{
            background: #f8fafc;
            border: 1px solid #d0dce8;
            border-radius: 12px;
            padding: 14px;
        }}
        .calendar-month-title {{
            color: #1a8fc4;
            font-weight: bold;
            margin-bottom: 10px;
            text-align: center;
        }}
        .calendar-weekdays,
        .calendar-days {{
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 6px;
        }}
        .calendar-weekdays span {{
            text-align: center;
            color: #7f96bc;
            font-size: 0.78em;
        }}
        .calendar-day,
        .calendar-day-empty {{
            min-height: 38px;
            border-radius: 8px;
        }}
        .calendar-day-empty {{
            background: rgba(0, 0, 0, 0.02);
        }}
        .calendar-day {{
            position: relative;
            border: 1px solid #d8e4ef;
            background: #f0f4f8;
            color: #4e6880;
            cursor: pointer;
            font-size: 0.85em;
        }}
        .calendar-day.has-data {{
            background: #e6f7f0;
            border-color: #2da870;
            color: #0e4d2e;
            font-weight: bold;
        }}
        .calendar-day.selected {{
            outline: 2px solid #1a8fc4;
            outline-offset: 1px;
        }}
        .calendar-day:hover {{
            transform: translateY(-1px);
        }}
        .calendar-day.has-data::after {{
            content: attr(data-count-label);
            position: absolute;
            left: 50%;
            bottom: calc(100% + 8px);
            transform: translateX(-50%);
            background: rgba(15, 28, 45, 0.92);
            color: #f0f8ff;
            border: 1px solid #2da870;
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 0.75em;
            white-space: nowrap;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.15s ease;
            z-index: 5;
        }}
        .calendar-day.has-data:hover::after {{
            opacity: 1;
        }}
        .selected-date-title {{
            color: #1a8fc4;
            margin-bottom: 12px;
            font-size: 1em;
        }}
        .detection-list {{
            display: block;
            max-height: 60vh;
            overflow-y: auto;
            padding-right: 6px;
        }}
        .date-group {{
            border: 1px solid #d0dce8;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 20px;
            background: #f8fafc;
        }}
        .date-group:last-child {{
            margin-bottom: 0;
        }}
        .date-group-header {{
            color: #1a8fc4;
            font-weight: bold;
            font-size: 1.1em;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #d0dce8;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .detection-group {{
            margin-bottom: 16px;
        }}
        .detection-group:last-child {{
            margin-bottom: 0;
        }}
        .detection-group-title {{
            color: #d4860a;
            font-weight: bold;
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1px solid #d0dce8;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .bulk-delete-btn {{
            background: #ff6b6b;
            border: 1px solid #ff4444;
            color: white;
            padding: 5px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.75em;
            transition: background 0.2s;
            white-space: nowrap;
        }}
        .bulk-delete-btn:hover {{
            background: #ff4444;
        }}
        .bulk-delete-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}

        .select-all-btn {{
            background: #f0f7fc;
            border: 1px solid #1a8fc4;
            color: #1a6090;
            padding: 4px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.82em;
            transition: background 0.2s;
            white-space: nowrap;
        }}
        .select-all-btn:hover {{
            background: #1a8fc4;
            color: #ffffff;
        }}
        .select-delete-btn {{
            background: #cc3333;
            border: 1px solid #ff4444;
            color: white;
            padding: 5px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85em;
            font-weight: bold;
            transition: background 0.2s;
            white-space: nowrap;
        }}
        .select-delete-btn:hover {{
            background: #ff4444;
        }}
        .select-delete-btn:disabled {{
            opacity: 0.6;
            cursor: wait;
        }}
        .detection-item.sel-selected {{
            background: #e0eff8;
            outline: 2px solid #1a8fc4;
        }}
        .detection-item-select-wrap {{
            display: flex;
            align-items: flex-start;
            gap: 8px;
        }}
        .detection-select-cb {{
            margin-top: 3px;
            width: 18px;
            height: 18px;
            cursor: pointer;
            flex-shrink: 0;
            accent-color: #1a8fc4;
        }}
        .detection-item-body {{
            flex: 1;
            min-width: 0;
        }}
        .detection-group-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 10px;
        }}
        .detection-item {{
            padding: 12px;
            background: #f8fafc;
            border: 1px solid #e4edf5;
            border-radius: 8px;
            font-size: 0.85em;
            transition: background 0.2s;
        }}
        .detection-item:hover {{
            background: #eef4fa;
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
            color: #1a8fc4;
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
            background: #f0f7fc;
            border: 1px solid #1a8fc4;
            color: #1a8fc4;
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
            background: #1a8fc4;
            color: #ffffff;
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
            border: 1px solid #d0dce8;
            background: #f4f8fb;
            color: #4e6880;
            font-size: 0.8em;
            user-select: none;
        }}
        .label-radio input:checked + span {{
            border-color: #1d9e60;
            color: #0e5c30;
            background: #e6f7ef;
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
            color: #1a8fc4;
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
            color: #4db8e8;
            text-decoration: none;
            font-size: 0.9em;
        }}
        .modal-downloads a:hover {{
            text-decoration: underline;
        }}
        .footer {{
            text-align: center;
            padding: 24px 30px;
            color: #7a96b0;
            font-size: 0.82em;
            border-top: 1px solid #d8e4ef;
            margin-top: 40px;
        }}
        .version-link {{
            color: #1a8fc4;
            text-decoration: none;
            cursor: pointer;
            transition: color 0.2s;
        }}
        .version-link:hover {{
            color: #d4860a;
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
            background: #ffffff;
            padding: 30px;
            border-radius: 12px;
            position: relative;
            color: #192333;
        }}
        .changelog-content h1, .changelog-content h2 {{
            color: #1a8fc4;
        }}
        .changelog-content h3 {{
            color: #f5a41f;
        }}
        .changelog-content pre {{
            background: #f4f8fb;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        :focus-visible {{
            outline: 2px solid #1a8fc4;
            outline-offset: 2px;
            border-radius: 3px;
        }}
    </style>
</head>
<body>
    <nav class="topnav">
        <a href="/" class="brand-link">{brand_logo_html}</a>
        <div class="nav-links">
            {nav_items_html}
        </div>
        {nav_actions_html}
    </nav>
    <div class="page-header">
        <h1>{page_heading}</h1>
        <div class="hero-clock" id="hero-clock">----/--/-- --:--:--</div>
        <div class="subtitle" id="global-detection-control-status"></div>
    </div>

    <main>
    <div class="stats-bar">
        {stats_primary}
        <div class="stat">
            <div class="stat-value" id="dashboard-cpu">--</div>
            <div class="stat-label">システム CPU</div>
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

    {camera_grid_html}

    {detections_section_html}

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
        const cameras = {json.dumps(_sanitize_cameras_for_js(cameras))};
        const cameraPageEnabled = {str(is_camera_page).lower()};
        const detectionsPageEnabled = {str(is_detections_page).lower()};
        const serverStartTime = {int(server_start_time * 1000)};
        const streamPlaceholderSrc = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
        const streamSelectionStorageKey = 'dashboard_stream_enabled_v1';
        const heroClockFormatter = new Intl.DateTimeFormat('ja-JP', {{
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        }});

        // 稼働時間を更新
        setInterval(() => {{
            const elapsed = Math.floor((Date.now() - serverStartTime) / 1000);
            const hours = Math.floor(elapsed / 3600);
            const mins = Math.floor((elapsed % 3600) / 60);
            document.getElementById('uptime').textContent =
                hours > 0 ? hours + ':' + String(mins).padStart(2,'0') + 'h' : mins + 'm';
        }}, 1000);

        function updateHeroClock() {{
            const el = document.getElementById('hero-clock');
            if (!el) {{
                return;
            }}
            el.textContent = heroClockFormatter.format(new Date());
        }}
        updateHeroClock();
        setInterval(updateHeroClock, 1000);

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
            end: null,
            loaded: false
        }};

        function parseDetectionWindowTime(value) {{
            if (!value) return null;
            const iso = value.replace(' ', 'T');
            const dt = new Date(iso);
            return Number.isNaN(dt.getTime()) ? null : dt;
        }}

        function isWithinDetectionWindow() {{
            if (!detectionWindowState.loaded) return null;
            if (!detectionWindowState.enabled) return true;
            if (!detectionWindowState.start || !detectionWindowState.end) return true;
            const now = new Date();
            return now >= detectionWindowState.start && now <= detectionWindowState.end;
        }}

        function setDetectionIndicatorState(i, state, helpText) {{
            const detectionEl = document.getElementById('detection' + i);
            if (!detectionEl) {{
                return;
            }}
            detectionEl.className = 'detection-status indicator-help' + (state ? ' ' + state : '');
            detectionEl.title = '検出処理';
            detectionEl.dataset.help = helpText;
        }}

        function updateDetectionIndicator(i, data, statsFetchOk) {{
            if (!statsFetchOk) {{
                setDetectionIndicatorState(i, 'unknown', '検出処理状態（灰: カメラ統計の取得失敗または確認中）');
                return;
            }}

            const withinWindow = isWithinDetectionWindow();
            const streamAlive = data.stream_alive !== false;
            const stopReason = String(data.monitor_stop_reason || '');
            const statsFailures = Number(data.monitor_stats_failures || 0);
            const failThreshold = Number(data.monitor_fail_threshold || 8);
            const statsUnavailable = stopReason === 'stats_unreachable' || stopReason === 'stats_unreachable_transient';
            const likelyError = !streamAlive || statsUnavailable || (stopReason && stopReason !== 'none' && stopReason !== 'unknown');
            const sourceFps = Number(data?.settings?.source_fps || 0);
            const runtimeFps = Number(data.runtime_fps || 0);
            const fpsLow = sourceFps > 0 && runtimeFps > 0 && runtimeFps < (sourceFps * {fps_warning_ratio});

            if (withinWindow === null) {{
                setDetectionIndicatorState(i, 'unknown', '検出処理状態（灰: 検出時間帯を確認中）');
                return;
            }}

            if (data.detection_enabled === false) {{
                setDetectionIndicatorState(i, 'paused', '検出処理状態（橙: 手動停止中）');
                return;
            }}

            if (data.is_detecting === true) {{
                setDetectionIndicatorState(i, 'detecting', '検出処理状態（赤点滅: 検出期間内で処理中）');
                return;
            }}

            if (!withinWindow) {{
                setDetectionIndicatorState(i, 'inactive', '検出処理状態（緑: 検出期間外）');
                return;
            }}

            if (likelyError) {{
                const detail = statsUnavailable
                    ? `統計取得失敗 ${{statsFailures}}/${{failThreshold}}`
                    : (!streamAlive ? '映像更新停止' : `停止理由: ${{stopReason}}`);
                setDetectionIndicatorState(i, 'warning', `検出処理状態（黄: 検出期間内だが停止疑い / ${{detail}}）`);
                return;
            }}

            if (fpsLow) {{
                setDetectionIndicatorState(i, 'warning', `検出処理状態（黄: runtime_fps=${{runtimeFps.toFixed(1)}} が source_fps=${{sourceFps.toFixed(1)}} の80%未満）`);
                return;
            }}

            setDetectionIndicatorState(i, 'unknown', '検出処理状態（灰: 検出期間内だが状態未確定）');
        }}

        // 検出時間帯を取得・更新
        function updateDetectionWindow() {{
            fetch('/detection_window')
                .then(r => r.json())
                .then(data => {{
                    detectionWindowState.loaded = true;
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
                    detectionWindowState.loaded = false;
                    detectionWindowState.enabled = false;
                    detectionWindowState.start = null;
                    detectionWindowState.end = null;
                }});
        }}
        updateDetectionWindow();
        setInterval(updateDetectionWindow, 60000);  // 1分ごとに更新

        // 各カメラの統計を取得
        let totalDetections = 0;
        const cameraStatsTimers = [];
        const cameraStatsState = [];
        const streamRetryState = [];
        const streamSelectionState = [];
        const recordingPanelState = [];
        const STREAM_RETRY_DELAY_MS = 3000;
        const CAMERA_STATS_FETCH_TIMEOUT_MS = 5000;
        const FOCUS_RECOVERY_COOLDOWN_MS = 8000;
        let dashboardBackgroundPaused = document.hidden === true;
        let lastForegroundRecoveryAt = 0;
        let detectionPollTimer = null;
        let cameraSectionStarted = false;

        function ensureStreamRetryState(i) {{
            if (!streamRetryState[i]) {{
                streamRetryState[i] = {{
                    timer: null,
                }};
            }}
            return streamRetryState[i];
        }}

        function recordingLocalDateTimeValue(date = new Date()) {{
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            const hour = String(date.getHours()).padStart(2, '0');
            const minute = String(date.getMinutes()).padStart(2, '0');
            const second = String(date.getSeconds()).padStart(2, '0');
            return `${{year}}-${{month}}-${{day}}T${{hour}}:${{minute}}:${{second}}`;
        }}

        function ensureRecordingDefaults(i) {{
            const startInput = document.getElementById('recording-start' + i);
            const durationInput = document.getElementById('recording-duration' + i);
            if (startInput && !startInput.value) {{
                startInput.value = recordingLocalDateTimeValue();
            }}
            if (durationInput && !durationInput.value) {{
                durationInput.value = '60';
            }}
        }}

        function loadStreamSelection() {{
            let saved = null;
            try {{
                saved = JSON.parse(localStorage.getItem(streamSelectionStorageKey) || 'null');
            }} catch (_) {{
                saved = null;
            }}
            cameras.forEach((_, i) => {{
                const enabled = Array.isArray(saved) && typeof saved[i] === 'boolean' ? saved[i] : true;
                streamSelectionState[i] = enabled;
            }});
        }}

        function saveStreamSelection() {{
            try {{
                localStorage.setItem(streamSelectionStorageKey, JSON.stringify(streamSelectionState));
            }} catch (_) {{
                // localStorage が使えない環境では保存をスキップ
            }}
        }}

        function isStreamEnabled(i) {{
            return streamSelectionState[i] !== false;
        }}

        function setStreamErrorMessage(i, message) {{
            const errorEl = document.getElementById('error' + i);
            if (!errorEl) return;
            const span = errorEl.querySelector('span');
            if (span) {{
                span.textContent = message;
            }}
        }}

        function isPlaceholderStreamSrc(img) {{
            if (!img) return false;
            const src = String(img.currentSrc || img.src || '');
            return src.startsWith(streamPlaceholderSrc);
        }}

        function getCameraStreamKind(i) {{
            const cam = cameras[i] || {{}};
            return String(cam.stream_kind || 'webrtc').toLowerCase();
        }}

        function isWebRTCStream(i) {{
            return getCameraStreamKind(i) === 'webrtc';
        }}

        function getStreamImageElement(i) {{
            return document.getElementById('stream' + i);
        }}

        function getStreamFrameElement(i) {{
            return document.getElementById('stream-frame' + i);
        }}

        function setStreamOverlayVisible(i, visible, message = '') {{
            const errorEl = document.getElementById('error' + i);
            if (!errorEl) {{
                return;
            }}
            if (message) {{
                setStreamErrorMessage(i, message);
            }}
            if (isWebRTCStream(i) && visible) {{
                errorEl.style.display = 'none';
                return;
            }}
            errorEl.style.display = visible ? 'flex' : 'none';
        }}

        function normalizeBrowserFacingUrl(rawUrl, streamKind) {{
            if (!rawUrl) {{
                return '';
            }}
            const host = window.location.hostname;
            const pageProtocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
            try {{
                const parsed = new URL(rawUrl, window.location.href);
                if (host && ['localhost', '127.0.0.1', '::1'].includes(parsed.hostname)) {{
                    parsed.hostname = host;
                }}
                if (streamKind === 'mjpeg') {{
                    parsed.protocol = pageProtocol;
                }}
                return parsed.toString();
            }} catch (_) {{
                return rawUrl;
            }}
        }}

        function resolveCameraStreamUrl(i) {{
            const cam = cameras[i];
            if (!cam) {{
                return '';
            }}
            const streamKind = getCameraStreamKind(i);
            if (streamKind === 'webrtc') {{
                return new URL('/camera_embed/' + i, window.location.href).toString();
            }}
            const rawStreamUrl = String(cam.stream_url || cam.url || '');
            if (!rawStreamUrl) {{
                return '';
            }}
            try {{
                const targetUrl = new URL('/stream', rawStreamUrl).toString();
                return normalizeBrowserFacingUrl(targetUrl, streamKind);
            }} catch (_) {{
                return '';
            }}
        }}

        function fetchJsonWithTimeout(url, timeoutMs, options = {{}}) {{
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
            return fetch(url, {{ ...options, signal: controller.signal }})
                .then((r) => r.json())
                .finally(() => clearTimeout(timeoutId));
        }}

        function applyStreamToggleUI(i) {{
            const checkbox = document.getElementById('stream-toggle' + i);
            if (checkbox) {{
                checkbox.checked = isStreamEnabled(i);
            }}
        }}

        function bindStreamEventHandlers(i) {{
            const img = getStreamImageElement(i);
            const frame = getStreamFrameElement(i);
            if (img && !img.dataset.handlersBound) {{
                img.addEventListener('error', () => handleStreamError(i));
                img.addEventListener('load', () => handleStreamLoad(i));
                img.dataset.handlersBound = '1';
            }}
            if (frame && !frame.dataset.handlersBound) {{
                frame.addEventListener('load', () => handleStreamLoad(i));
                frame.dataset.handlersBound = '1';
            }}
        }}

        function setStreamEnabled(i, enabled, persist = true) {{
            if (!cameraPageEnabled) {{
                return;
            }}
            streamSelectionState[i] = enabled === true;
            applyStreamToggleUI(i);
            clearStreamRetryTimer(i);

            const img = getStreamImageElement(i);
            const frame = getStreamFrameElement(i);
            const errorEl = document.getElementById('error' + i);
            const statusEl = document.getElementById('status' + i);
            if (!img || !frame || !errorEl || !statusEl) {{
                if (persist) saveStreamSelection();
                return;
            }}
            bindStreamEventHandlers(i);

            if (isStreamEnabled(i)) {{
                setStreamErrorMessage(i, '接続中...');
                statusEl.className = 'camera-status';
                connectStream(i);
            }} else {{
                img.removeAttribute('src');
                frame.removeAttribute('src');
                img.style.display = 'none';
                frame.style.display = 'none';
                errorEl.style.display = 'flex';
                setStreamErrorMessage(i, '常時表示オフ');
                statusEl.className = 'camera-status paused';
            }}

            if (persist) {{
                saveStreamSelection();
            }}
        }}

        function toggleStreamEnabled(i, enabled) {{
            setStreamEnabled(i, enabled, true);
        }}

        function clearStreamRetryTimer(i) {{
            const state = ensureStreamRetryState(i);
            if (state.timer) {{
                clearTimeout(state.timer);
                state.timer = null;
            }}
        }}

        function connectStream(i) {{
            if (dashboardBackgroundPaused || !isStreamEnabled(i)) {{
                return;
            }}
            clearStreamRetryTimer(i);
            const img = getStreamImageElement(i);
            const frame = getStreamFrameElement(i);
            if (!img || !frame) return;
            const targetUrl = resolveCameraStreamUrl(i);
            if (!targetUrl) {{
                setStreamOverlayVisible(i, true, '表示URL未設定');
                return;
            }}
            if (isWebRTCStream(i)) {{
                img.removeAttribute('src');
                img.style.display = 'none';
                frame.style.display = 'block';
                setStreamOverlayVisible(i, false);
                frame.src = targetUrl + (targetUrl.includes('?') ? '&' : '?') + 't=' + Date.now();
                return;
            }}
            frame.removeAttribute('src');
            frame.style.display = 'none';
            img.style.display = 'none';
            setStreamOverlayVisible(i, true, '接続中...');
            img.src = targetUrl + (targetUrl.includes('?') ? '&' : '?') + 't=' + Date.now();
        }}

        function scheduleStreamRetry(i, delay = STREAM_RETRY_DELAY_MS) {{
            if (dashboardBackgroundPaused || !isStreamEnabled(i)) {{
                return;
            }}
            const state = ensureStreamRetryState(i);
            clearStreamRetryTimer(i);
            state.timer = setTimeout(() => {{
                connectStream(i);
            }}, Math.max(0, delay));
        }}

        function handleStreamError(i) {{
            if (dashboardBackgroundPaused) {{
                return;
            }}
            if (!isStreamEnabled(i)) {{
                return;
            }}
            const img = getStreamImageElement(i);
            const frame = getStreamFrameElement(i);
            if (img) {{
                img.removeAttribute('src');
                img.style.display = 'none';
            }}
            if (frame) {{
                frame.removeAttribute('src');
                frame.style.display = 'none';
            }}
            setStreamOverlayVisible(i, true, '映像取得に失敗（再接続中）');
            scheduleStreamRetry(i);
        }}

        function handleStreamLoad(i) {{
            if (dashboardBackgroundPaused) {{
                return;
            }}
            if (!isStreamEnabled(i)) {{
                return;
            }}
            const img = getStreamImageElement(i);
            const frame = getStreamFrameElement(i);
            if (!isWebRTCStream(i) && isPlaceholderStreamSrc(img)) {{
                // プレースホルダ読込は正常接続ではないため無視する
                return;
            }}
            if (img) {{
                img.style.display = isWebRTCStream(i) ? 'none' : '';
            }}
            if (frame) {{
                frame.style.display = isWebRTCStream(i) ? 'block' : 'none';
            }}
            if (img && !isWebRTCStream(i)) {{
                img.style.display = '';
            }}
            setStreamOverlayVisible(i, false);
            clearStreamRetryTimer(i);
        }}

        function forceResetStreamElement(i) {{
            const img = getStreamImageElement(i);
            const frame = getStreamFrameElement(i);
            if (img) {{
                img.removeAttribute('src');
                img.style.display = 'none';
            }}
            if (frame) {{
                frame.removeAttribute('src');
                frame.style.display = 'none';
            }}
            setStreamOverlayVisible(i, true, '接続待機...');
        }}

        function startCameraStreams() {{
            cameras.forEach((_, i) => {{
                applyStreamToggleUI(i);
                if (isStreamEnabled(i)) {{
                    connectStream(i);
                }} else {{
                    setStreamEnabled(i, false, false);
                }}
            }});
        }}

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
            if (!cameraPageEnabled) {{
                return;
            }}
            cameras.forEach((_, i) => {{
                clearStreamRetryTimer(i);
                const img = document.getElementById('stream' + i);
                const frame = document.getElementById('stream-frame' + i);
                const errorEl = document.getElementById('error' + i);
                const statusEl = document.getElementById('status' + i);
                const serverStatusEl = document.getElementById('server-status' + i);
                if (img) {{
                    img.removeAttribute('src');
                    img.style.display = 'none';
                }}
                if (frame) {{
                    frame.removeAttribute('src');
                    frame.style.display = 'none';
                }}
                setStreamOverlayVisible(i, !isWebRTCStream(i), 'バックグラウンド一時停止');
                if (statusEl) {{
                    statusEl.className = 'camera-status paused';
                }}
                if (serverStatusEl) {{
                    serverStatusEl.className = 'server-status unknown';
                }}
            }});
        }}

        function resumeDashboardActivity() {{
            if (!dashboardBackgroundPaused) {{
                return;
            }}
            dashboardBackgroundPaused = false;
            if (cameraPageEnabled) {{
                cameras.forEach((_, i) => {{
                    if (!isStreamEnabled(i)) {{
                        return;
                    }}
                    clearStreamRetryTimer(i);
                    const img = document.getElementById('stream' + i);
                    const frame = document.getElementById('stream-frame' + i);
                    const statusEl = document.getElementById('status' + i);
                    const serverStatusEl = document.getElementById('server-status' + i);
                    if (img) {{
                        img.removeAttribute('src');
                        img.style.display = 'none';
                    }}
                    if (frame) {{
                        frame.removeAttribute('src');
                        frame.style.display = 'none';
                    }}
                    if (statusEl) {{
                        statusEl.className = 'camera-status';
                    }}
                    if (serverStatusEl) {{
                        serverStatusEl.className = 'server-status unknown';
                    }}
                    setStreamOverlayVisible(i, !isWebRTCStream(i), '接続待機...');
                }});
                startCameraStreams();
                cameras.forEach((_, i) => {{
                    updateCameraStats(i);
                }});
            }}
            if (detectionsPageEnabled) {{
                pollDetections();
            }}
        }}

        function recoverForegroundActivity(reason = 'focus') {{
            if (document.hidden) {{
                return;
            }}
            const now = Date.now();
            if ((now - lastForegroundRecoveryAt) < FOCUS_RECOVERY_COOLDOWN_MS) {{
                return;
            }}
            lastForegroundRecoveryAt = now;

            if (dashboardBackgroundPaused) {{
                resumeDashboardActivity();
                return;
            }}

            if (cameraPageEnabled) {{
                cameras.forEach((_, i) => {{
                    if (!isStreamEnabled(i)) {{
                        return;
                    }}
                    clearStreamRetryTimer(i);
                    setStreamOverlayVisible(i, !isWebRTCStream(i), `再同期待機... (${{reason}})`);
                }});
                startCameraStreams();
                cameras.forEach((_, i) => {{
                    updateCameraStats(i);
                }});
            }}
            if (detectionsPageEnabled) {{
                pollDetections();
            }}
        }}

        function syncDashboardVisibilityState() {{
            if (document.hidden) {{
                pauseDashboardActivity();
            }} else {{
                recoverForegroundActivity('visibility');
            }}
        }}

        function scheduleCameraStats(i, delay) {{
            if (!cameraPageEnabled) {{
                return;
            }}
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
            const clipClass = s.extract_clips ? 'param-clip' : 'param-no-clip';
            const clipText = s.extract_clips ? 'CLIP:ON' : 'CLIP:OFF';
            const detectText = data.detection_enabled === false ? 'DET:OFF' : 'DET:ON';
            const sourceFps = Number(s.source_fps || 0);
            const runtimeFps = Number(data.runtime_fps || 0);
            const fpsText = runtimeFps > 0 ? runtimeFps.toFixed(1) : (sourceFps > 0 ? sourceFps.toFixed(1) : '-');
            const fpsWarning = sourceFps > 0 && runtimeFps > 0 && runtimeFps < (sourceFps * {fps_warning_ratio});
            const fpsClass = fpsWarning ? 'param-fps-warning' : '';
            el.innerHTML =
                `<span class="param">${{s.sensitivity}}</span>` +
                `<span class="param">x${{s.scale}}</span>` +
                `<span class="param ${{fpsClass}}" title="${{fpsWarning ? 'runtime_fps が source_fps の 80% 未満' : '処理FPS'}}">FPS:${{fpsText}}</span>` +
                `<span class="param">${{detectText}}</span>` +
                `<span class="param ${{clipClass}}">${{clipText}}</span>`;
        }}

        function setGlobalDetectionControlStatus(message) {{
            const el = document.getElementById('global-detection-control-status');
            if (!el) {{
                return;
            }}
            el.textContent = message || '';
        }}

        async function setGlobalDetectionEnabled(enabled) {{
            const label = enabled ? '再開' : '停止';
            setGlobalDetectionControlStatus(`検出${{label}}を適用中...`);
            try {{
                const res = await fetch('/camera_settings/apply_all', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ detection_enabled: enabled }}),
                }});
                const data = await res.json();
                if (!res.ok || data.success === false) {{
                    throw new Error(data.error || ('HTTP ' + res.status));
                }}
                setGlobalDetectionControlStatus(`検出${{label}}完了: ${{data.applied_count}}/${{data.total}}台`);
                if (cameraPageEnabled) {{
                    cameras.forEach((_, i) => updateCameraStats(i));
                }}
            }} catch (e) {{
                setGlobalDetectionControlStatus(`検出${{label}}失敗: ${{e}}`);
            }}
        }}

        function updateCameraStats(i) {{
            if (!cameraPageEnabled) return;
            if (dashboardBackgroundPaused) return;
            const cam = cameras[i];
            if (!cam) return;
            const baseDelay = 5000;
            const maxDelay = 15000;
            if (!cameraStatsState[i]) {{
                cameraStatsState[i] = {{ delay: baseDelay }};
            }}

            fetchJsonWithTimeout('/camera_stats/' + i, CAMERA_STATS_FETCH_TIMEOUT_MS, {{ cache: 'no-store' }})
                .then(data => {{
                    if (dashboardBackgroundPaused) {{
                        return;
                    }}
                    cameraStatsState[i].delay = baseDelay;
                    document.getElementById('count' + i).textContent = data.detections;
                    renderCameraParams(i, data);
                    const serverStatusEl = document.getElementById('server-status' + i);
                    const monitorStopReason = String(data.monitor_stop_reason || '');
                    const monitorStatsFailures = Number(data.monitor_stats_failures || 0);
                    const monitorFailThreshold = Number(data.monitor_fail_threshold || 8);
                    if (serverStatusEl) {{
                        if (monitorStopReason === 'stats_unreachable') {{
                            serverStatusEl.className = monitorStatsFailures >= monitorFailThreshold ? 'server-status offline' : 'server-status unknown';
                        }} else if (monitorStopReason === 'stats_unreachable_transient') {{
                            serverStatusEl.className = 'server-status unknown';
                        }} else if (monitorStopReason === 'unknown') {{
                            serverStatusEl.className = 'server-status unknown';
                        }} else {{
                            serverStatusEl.className = 'server-status';
                        }}
                    }}
                    const streamEnabled = isStreamEnabled(i);
                    const streamAlive = data.stream_alive !== false;
                    if (!streamEnabled) {{
                        document.getElementById('status' + i).className = 'camera-status paused';
                    }} else if (!streamAlive) {{
                        document.getElementById('status' + i).className = 'camera-status offline';
                        setStreamErrorMessage(i, '映像更新待ち（再接続中）');
                    }} else {{
                        document.getElementById('status' + i).className = 'camera-status';
                    }}
                    updateDetectionIndicator(i, data, true);
                    const maskActive = data.mask_active === true;
                    const maskStatusEl = document.getElementById('mask-status' + i);
                    if (maskStatusEl) {{
                        maskStatusEl.className = maskActive ? 'mask-status active' : 'mask-status';
                    }}
                    const maskBtn = document.getElementById('mask-btn' + i);
                    if (maskBtn) {{
                        maskBtn.disabled = !maskActive;
                        if (!maskActive) {{
                            setMaskOverlay(i, false);
                        }}
                    }}
                    updateRecordingUI(i, data.recording || {{}});
                }})
                .catch(() => {{
                    if (dashboardBackgroundPaused) {{
                        return;
                    }}
                    cameraStatsState[i].delay = Math.min(cameraStatsState[i].delay * 2, maxDelay);
                    const serverStatusEl = document.getElementById('server-status' + i);
                    if (serverStatusEl) {{
                        serverStatusEl.className = 'server-status unknown';
                    }}
                    if (isStreamEnabled(i)) {{
                        document.getElementById('status' + i).className = 'camera-status';
                        setStreamErrorMessage(i, '通信状態を確認中...');
                    }} else {{
                        document.getElementById('status' + i).className = 'camera-status paused';
                    }}
                    updateDetectionIndicator(i, {{}}, false);
                    updateRecordingUI(i, {{
                        supported: true,
                        state: 'idle',
                    }});
                }})
                .finally(() => {{
                    scheduleCameraStats(i, cameraStatsState[i].delay);
                }});
        }}

        function startCameraSection() {{
            if (!cameraPageEnabled) {{
                return;
            }}
            if (cameraSectionStarted) {{
                return;
            }}
            cameraSectionStarted = true;
            loadStreamSelection();
            cameras.forEach((cam, i) => {{
                ensureRecordingDefaults(i);
                updateCameraStats(i);
            }});
            startCameraStreams();
            syncDashboardVisibilityState();
        }}

        function toggleRecordingPanel(i) {{
            const panel = document.getElementById('recording-panel' + i);
            if (!panel) return;
            const willShow = panel.hidden;
            panel.hidden = !willShow;
            recordingPanelState[i] = willShow;
            if (willShow) {{
                ensureRecordingDefaults(i);
            }}
        }}

        function setRecordingStartNow(i) {{
            const startInput = document.getElementById('recording-start' + i);
            if (!startInput) return;
            startInput.value = recordingLocalDateTimeValue();
        }}

        function formatRecordingTimestamp(value) {{
            if (!value) return '';
            const dt = new Date(value);
            if (Number.isNaN(dt.getTime())) {{
                return value;
            }}
            return dt.toLocaleString('ja-JP', {{
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            }});
        }}

        function renderRecordingText(recording) {{
            const rec = recording || {{}};
            const state = String(rec.state || 'idle');
            if (rec.supported === false) {{
                return '録画未対応';
            }}
            if (state === 'scheduled') {{
                return `予約中: ${{formatRecordingTimestamp(rec.start_at)}} / ${{rec.duration_sec || 0}}秒`;
            }}
            if (state === 'recording') {{
                return `録画中: 残り約${{Math.max(0, Number(rec.remaining_sec || 0))}}秒`;
            }}
            if (state === 'completed') {{
                return `完了: ${{formatRecordingTimestamp(rec.ended_at)}}`;
            }}
            if (state === 'failed') {{
                return `失敗: ${{rec.error || '不明なエラー'}}`;
            }}
            if (state === 'stopped') {{
                return '停止済み';
            }}
            return '録画待機';
        }}

        function updateRecordingUI(i, recording) {{
            const rec = recording || {{}};
            const statusEl = document.getElementById('recording-status' + i);
            const summaryEl = document.getElementById('recording-summary' + i);
            const stopBtn = document.getElementById('recording-stop' + i);
            const submitBtn = document.getElementById('recording-submit' + i);
            const text = renderRecordingText(rec);
            if (statusEl) {{
                statusEl.textContent = text;
                statusEl.className = 'recording-status ' + String(rec.state || 'idle');
            }}
            if (summaryEl) {{
                summaryEl.textContent = '録画: ' + text;
            }}
            if (stopBtn) {{
                stopBtn.disabled = !['scheduled', 'recording'].includes(String(rec.state || ''));
            }}
            if (submitBtn) {{
                submitBtn.disabled = rec.supported === false || ['scheduled', 'recording'].includes(String(rec.state || ''));
            }}
        }}

        function scheduleRecording(i) {{
            const startInput = document.getElementById('recording-start' + i);
            const durationInput = document.getElementById('recording-duration' + i);
            const submitBtn = document.getElementById('recording-submit' + i);
            if (!startInput || !durationInput || !submitBtn) return;
            const durationSec = Number(durationInput.value);
            if (!Number.isFinite(durationSec) || durationSec <= 0) {{
                alert('録画秒数は 1 以上で入力してください。');
                return;
            }}
            submitBtn.disabled = true;
            submitBtn.textContent = '予約中...';
            fetch('/camera_recording_schedule/' + i, {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{
                    start_at: startInput.value || '',
                    duration_sec: durationSec
                }})
            }})
                .then(r => r.json())
                .then(data => {{
                    if (!data.success) {{
                        throw new Error(data.error || 'schedule failed');
                    }}
                    updateRecordingUI(i, data.recording || {{}});
                }})
                .catch((err) => {{
                    alert('録画予約に失敗しました: ' + err.message);
                }})
                .finally(() => {{
                    submitBtn.textContent = '実行';
                    updateCameraStats(i);
                }});
        }}

        function stopRecording(i) {{
            const stopBtn = document.getElementById('recording-stop' + i);
            if (!stopBtn) return;
            stopBtn.disabled = true;
            stopBtn.textContent = '停止中...';
            fetch('/camera_recording_stop/' + i, {{
                method: 'POST'
            }})
                .then(r => r.json())
                .then(data => {{
                    if (!data.success) {{
                        throw new Error(data.error || 'stop failed');
                    }}
                    updateRecordingUI(i, data.recording || {{}});
                }})
                .catch((err) => {{
                    alert('録画停止に失敗しました: ' + err.message);
                }})
                .finally(() => {{
                    stopBtn.textContent = '停止';
                    updateCameraStats(i);
                }});
        }}

        // マスク更新
        function updateMask(i) {{
            const btn = document.querySelectorAll('.mask-btn')[i];
            if (!btn) return;
            const overlay = document.getElementById('mask' + i);
            const wasVisible = overlay && overlay.dataset.visible === '1';
            btn.disabled = true;
            btn.textContent = '更新中...';
            fetch('/camera_mask/' + i, {{ method: 'POST' }})
                .then(r => r.json())
                .then(async (data) => {{
                    if (!data.success) {{
                        btn.textContent = '失敗';
                        return;
                    }}
                    if (overlay) {{
                        overlay.dataset.src = '/camera_mask_image/' + i + '?pending=1';
                        setMaskOverlay(i, true);
                    }}
                    const apply = confirm('新しいマスクを表示しました。入れ替えを適用しますか？');
                    const endpoint = apply ? '/camera_mask_confirm/' + i : '/camera_mask_discard/' + i;
                    const applyResponse = await fetch(endpoint, {{ method: 'POST' }});
                    const applyData = await applyResponse.json();
                    btn.textContent = applyData.success ? (apply ? '更新完了' : '更新取消') : '失敗';
                    if (overlay) {{
                        overlay.dataset.src = '/camera_mask_image/' + i;
                        if (applyData.success) {{
                            if (wasVisible) {{
                                setMaskOverlay(i, true);
                            }} else {{
                                setMaskOverlay(i, false);
                            }}
                        }}
                    }}
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
                // 接続飽和を避けるため、必要なカメラだけ再接続する
                const streamImg = document.getElementById('stream' + i);
                if (streamImg && streamImg.style.display === 'none') {{
                    scheduleStreamRetry(i, 300);
                }}
                setTimeout(() => {{
                    btn.textContent = 'スナップショット保存';
                    btn.disabled = false;
                }}, 1500);
            }}
        }}

        function restartCamera(i) {{
            const cam = cameras[i];
            if (!cam) return;
            const displayName = cam.display_name || cam.name;
            if (!confirm(`カメラを再起動しますか?\n${{displayName}}`)) {{
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

        let _youtubePollingTimer = null;

        function _isAnyYoutubeActive() {{
            return cameras.some((cam, i) => {{
                if (!cam.has_youtube_key) return false;
                const btn = document.getElementById('youtube-btn' + i);
                return btn && btn.classList.contains('active');
            }});
        }}

        function _startYoutubePolling() {{
            if (_youtubePollingTimer) return;
            _youtubePollingTimer = setInterval(pollYouTubeStatus, 10000);
        }}

        function _stopYoutubePolling() {{
            if (_youtubePollingTimer) {{
                clearInterval(_youtubePollingTimer);
                _youtubePollingTimer = null;
            }}
        }}

        function toggleYouTube(i) {{
            const btn = document.getElementById('youtube-btn' + i);
            if (!btn) return;
            const cam = cameras[i];
            if (!cam) return;
            const isActive = btn.classList.contains('active');
            const action = isActive ? 'stop' : 'start';
            const displayName = cam.display_name || cam.name;
            const msg = isActive
                ? `YouTube配信を停止しますか?\n${{displayName}}`
                : `YouTube配信を開始しますか?\n${{displayName}}`;
            if (!confirm(msg)) return;
            btn.disabled = true;
            btn.textContent = isActive ? '停止中...' : '開始中...';
            fetch('/youtube_' + action + '/' + i, {{ method: 'POST' }})
                .then(r => r.json())
                .then(data => {{
                    if (data.success) {{
                        btn.classList.toggle('active');
                        btn.textContent = isActive ? 'YouTube配信' : '配信中 LIVE';
                        if (!isActive) {{
                            _startYoutubePolling();
                        }} else if (!_isAnyYoutubeActive()) {{
                            _stopYoutubePolling();
                        }}
                    }} else {{
                        btn.textContent = '失敗';
                    }}
                }})
                .catch(() => {{ btn.textContent = '失敗'; }})
                .finally(() => {{
                    setTimeout(() => {{ btn.disabled = false; }}, 1500);
                }});
        }}

        function pollYouTubeStatus() {{
            cameras.forEach((cam, i) => {{
                if (!cam.has_youtube_key) return;
                const btn = document.getElementById('youtube-btn' + i);
                if (!btn || !btn.classList.contains('active')) return;
                fetch('/youtube_status/' + i)
                    .then(r => r.json())
                    .then(data => {{
                        if (!btn || btn.disabled) return;
                        if (data.streaming) {{
                            btn.classList.add('active');
                            btn.textContent = '配信中 LIVE';
                        }} else {{
                            btn.classList.remove('active');
                            btn.textContent = 'YouTube配信';
                            if (!_isAnyYoutubeActive()) _stopYoutubePolling();
                        }}
                    }})
                    .catch(() => {{}});
            }});
        }}

        function setMaskOverlay(i, visible) {{
            const overlay = document.getElementById('mask' + i);
            const btn = document.getElementById('mask-btn' + i);
            if (!overlay || !btn) return;
            if (visible) {{
                const baseSrc = overlay.dataset.src || '';
                const sep = baseSrc.includes('?') ? '&' : '?';
                overlay.src = baseSrc + sep + 't=' + Date.now();
                overlay.style.display = 'block';
                overlay.dataset.visible = '1';
                btn.textContent = 'マスク非表示';
            }} else {{
                overlay.style.display = 'none';
                overlay.dataset.visible = '';
                btn.textContent = 'マスク表示';
            }}
        }}

        function toggleMask(i) {{
            const overlay = document.getElementById('mask' + i);
            if (!overlay) return;
            const visible = overlay.dataset.visible === '1';
            setMaskOverlay(i, !visible);
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
        function deleteDetection(camera, id, time, event) {{
            event.stopPropagation(); // 画像表示イベントを防止

            if (!confirm(`この検出を削除しますか?\n${{time}} - ${{camera}}`)) {{
                return;
            }}

            fetch(`/detection/${{encodeURIComponent(camera)}}/${{encodeURIComponent(id)}}`, {{
                method: 'DELETE'
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
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

        function deleteManualRecording(path, time, event) {{
            event.stopPropagation();

            if (!confirm(`この手動録画を削除しますか?\n${{time}}`)) {{
                return;
            }}

            fetch(`/manual_recording/${{encodeURI(path)}}`, {{
                method: 'DELETE'
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    updateDetections();
                }} else {{
                    alert('手動録画の削除に失敗しました: ' + (data.error || '不明なエラー'));
                }}
            }})
            .catch(err => {{
                alert('手動録画の削除に失敗しました: ' + err.message);
            }});
        }}

        // --- 選択 ---
        function toggleSelectItem(key, checked) {{
            if (checked) {{
                selectedDetectionIds.add(key);
            }} else {{
                selectedDetectionIds.delete(key);
            }}
            updateSelectDeleteButton();
        }}

        function updateSelectDeleteButton() {{
            const btn = document.getElementById('select-delete-btn');
            if (!btn) return;
            const n = selectedDetectionIds.size;
            btn.textContent = `選択した ${{n}} 件を削除`;
            btn.disabled = n === 0;
        }}

        function selectAll() {{
            const cbs = document.querySelectorAll('.detection-select-cb');
            const allChecked = cbs.length > 0 && [...cbs].every(cb => cb.checked);
            cbs.forEach(cb => {{
                cb.checked = !allChecked;
                const key = cb.dataset.key;
                if (!allChecked) {{
                    selectedDetectionIds.add(key);
                }} else {{
                    selectedDetectionIds.delete(key);
                }}
                const item = cb.closest('.detection-item');
                if (item) item.classList.toggle('sel-selected', !allChecked);
            }});
            updateSelectDeleteButton();
        }}

        async function deleteSelected() {{
            const n = selectedDetectionIds.size;
            if (n === 0) return;
            if (!confirm(`選択した ${{n}} 件を削除しますか?\n\nこの操作は取り消せません。`)) return;

            const btn = document.getElementById('select-delete-btn');
            if (btn) {{ btn.disabled = true; btn.textContent = '削除中...'; }}

            const ids = [...selectedDetectionIds];
            let failed = 0;
            for (const key of ids) {{
                try {{
                    let url;
                    if (key.startsWith('manual::')) {{
                        url = `/manual_recording/${{encodeURI(key.slice(8))}}`;
                    }} else {{
                        const sep = key.indexOf('::');
                        const camera = key.slice(0, sep);
                        const id = key.slice(sep + 2);
                        url = `/detection/${{encodeURIComponent(camera)}}/${{encodeURIComponent(id)}}`;
                    }}
                    const r = await fetch(url, {{ method: 'DELETE' }});
                    const data = await r.json();
                    if (data.success) {{
                        selectedDetectionIds.delete(key);
                    }} else {{
                        failed++;
                    }}
                }} catch (e) {{
                    failed++;
                }}
            }}

            if (failed > 0) {{
                alert(`${{failed}} 件の削除に失敗しました。`);
            }}
            selectedDetectionIds.clear();
            updateDetections();
        }}

        // それ以外を一括削除
        function bulkDeleteNonMeteor(camera, event) {{
            event.stopPropagation();

            if (!confirm(`${{camera}}の「それ以外」をすべて削除しますか?\n\nこの操作は取り消せません。`)) {{
                return;
            }}

            const btn = event.target;
            btn.disabled = true;
            btn.textContent = '削除中...';

            fetch(`/bulk_delete_non_meteor/${{encodeURIComponent(camera)}}`, {{
                method: 'POST'
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    updateDetections();
                }} else {{
                    alert('一括削除に失敗しました: ' + (data.error || '不明なエラー'));
                }}
            }})
            .catch(err => {{
                alert('一括削除に失敗しました: ' + err.message);
            }})
            .finally(() => {{
                btn.disabled = false;
                btn.textContent = 'それ以外を一括削除';
            }});
        }}

        function setDetectionLabelSelection(groupEl, label) {{
            const normalized = label === 'post_detected' ? 'post_detected' : 'detected';
            groupEl.dataset.label = normalized;
            groupEl.querySelectorAll('input[type="radio"]').forEach((radio) => {{
                radio.checked = radio.value === normalized;
            }});
        }}

        function updateBulkDeleteButton(camera) {{
            const groupEl = document.querySelector('.detection-group-title span');
            if (!groupEl) return;

            const detectionGroups = document.querySelectorAll('.detection-group');
            for (const group of detectionGroups) {{
                const titleSpan = group.querySelector('.detection-group-title span');
                if (titleSpan && titleSpan.textContent === camera) {{
                    const items = group.querySelectorAll('.detection-item');
                    let nonMeteorCount = 0;
                    items.forEach(item => {{
                        const labelRadios = item.querySelector('.label-radios');
                        if (labelRadios && labelRadios.dataset.label === 'post_detected') {{
                            nonMeteorCount++;
                        }}
                    }});

                    const existingBtn = group.querySelector('.bulk-delete-btn');
                    if (existingBtn) {{
                        existingBtn.remove();
                    }}

                    if (nonMeteorCount > 0) {{
                        const newBtn = document.createElement('button');
                        newBtn.className = 'bulk-delete-btn';
                        newBtn.textContent = `それ以外を一括削除 (${{nonMeteorCount}}件)`;
                        newBtn.onclick = (event) => bulkDeleteNonMeteor(camera, event);
                        group.querySelector('.detection-group-title').appendChild(newBtn);
                    }}
                    break;
                }}
            }}
        }}

        function updateDetectionLabel(camera, id, label, radioEl) {{
            const groupEl = radioEl.closest('.label-radios');
            if (!groupEl) return;
            const normalized = label === 'post_detected' ? 'post_detected' : 'detected';
            const previous = groupEl.dataset.label || 'detected';
            setDetectionLabelSelection(groupEl, normalized);
            const manageEl = groupEl.closest('.detection-manage-actions');
            const deleteBtn = manageEl ? manageEl.querySelector('.delete-btn') : null;
            if (deleteBtn) deleteBtn.style.display = normalized === 'detected' ? 'none' : '';
            fetch('/detection_label', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{ camera, id, label: normalized }})
            }})
            .then(r => r.json())
            .then(data => {{
                if (!data.success) {{
                    throw new Error(data.error || 'update failed');
                }}
                setDetectionLabelSelection(groupEl, normalized);
                updateBulkDeleteButton(camera);
                lastDetectionsKey = '';
            }})
            .catch((err) => {{
                alert('ラベル更新に失敗しました: ' + err.message);
                setDetectionLabelSelection(groupEl, previous);
                if (deleteBtn) deleteBtn.style.display = previous === 'detected' ? 'none' : '';
            }});
        }}

        let lastDetectionsKey = '';
        let lastDetectionsMtime = 0;
        let detectionRecords = [];
        let detectionCountsByDate = {{}};
        let detectionAvailableYears = [];
        let detectionCalendarRange = 'current';
        let selectedDetectionDate = '';
        let selectedDetectionIds = new Set(); // "camera::id" または "manual::path" 形式
        let detectionCalendarYear = new Date().getFullYear();
        const detectionPollBaseDelay = 5000;
        const detectionPollMaxDelay = 30000;
        const detectionWindowIdleDelay = 60000;
        let detectionPollDelay = detectionPollBaseDelay;
        detectionPollTimer = null;
        document.addEventListener('visibilitychange', syncDashboardVisibilityState);
        window.addEventListener('focus', () => recoverForegroundActivity('focus'));
        window.addEventListener('pageshow', () => recoverForegroundActivity('pageshow'));

        function scheduleDetectionPoll(delay) {{
            if (!detectionsPageEnabled) {{
                return;
            }}
            if (dashboardBackgroundPaused) {{
                return;
            }}
            if (detectionPollTimer) {{
                clearTimeout(detectionPollTimer);
            }}
            detectionPollTimer = setTimeout(pollDetections, delay);
        }}

        function dateLabel(dateStr) {{
            const [y, m, d] = dateStr.split('-').map(Number);
            return `${{y}}年${{m}}月${{d}}日`;
        }}

        function monthLabel(year, monthIndex) {{
            return `${{year}}年${{monthIndex + 1}}月`;
        }}

        function buildDetectionCounts(records) {{
            const counts = {{}};
            records.forEach((d) => {{
                const dateKey = d.time.split(' ')[0];
                counts[dateKey] = (counts[dateKey] || 0) + 1;
            }});
            return counts;
        }}

        function buildDetectionYearOptions(records) {{
            const years = new Set();
            records.forEach((d) => {{
                years.add(Number(d.time.slice(0, 4)));
            }});
            years.add(new Date().getFullYear());
            return Array.from(years).filter(Number.isFinite).sort((a, b) => b - a);
        }}

        function getCalendarMonths() {{
            const now = new Date();
            const current = new Date(now.getFullYear(), now.getMonth(), 1);
            const months = [];
            const pushMonth = (offset) => {{
                const dt = new Date(current.getFullYear(), current.getMonth() - offset, 1);
                months.push({{ year: dt.getFullYear(), month: dt.getMonth() }});
            }};
            if (detectionCalendarRange === 'previous') {{
                pushMonth(1);
            }} else if (detectionCalendarRange === '3m') {{
                for (let i = 2; i >= 0; i--) pushMonth(i);
            }} else if (detectionCalendarRange === '6m') {{
                for (let i = 5; i >= 0; i--) pushMonth(i);
            }} else if (detectionCalendarRange === '1y') {{
                for (let i = 11; i >= 0; i--) pushMonth(i);
            }} else if (detectionCalendarRange === 'year') {{
                for (let month = 0; month < 12; month++) {{
                    months.push({{ year: detectionCalendarYear, month }});
                }}
            }} else {{
                months.push({{ year: current.getFullYear(), month: current.getMonth() }});
            }}
            return months;
        }}

        function isDateInVisibleCalendar(dateStr) {{
            const monthKey = dateStr.slice(0, 7);
            return getCalendarMonths().some(({{ year, month }}) => {{
                const visibleKey = `${{year}}-${{String(month + 1).padStart(2, '0')}}`;
                return visibleKey === monthKey;
            }});
        }}

        function syncDetectionRangeControls() {{
            document.querySelectorAll('#detection-range-switch .range-btn').forEach((btn) => {{
                btn.classList.toggle('active', btn.dataset.range === detectionCalendarRange);
            }});
            const yearSelect = document.getElementById('detection-year-select');
            if (yearSelect) {{
                yearSelect.disabled = detectionCalendarRange !== 'year';
                yearSelect.value = String(detectionCalendarYear);
            }}
        }}

        function populateDetectionYearSelect() {{
            const yearSelect = document.getElementById('detection-year-select');
            if (!yearSelect) return;
            yearSelect.innerHTML = detectionAvailableYears
                .map((year) => `<option value="${{year}}">${{year}}年</option>`)
                .join('');
            if (!detectionAvailableYears.includes(detectionCalendarYear)) {{
                detectionCalendarYear = detectionAvailableYears[0] || new Date().getFullYear();
            }}
            yearSelect.value = String(detectionCalendarYear);
            syncDetectionRangeControls();
        }}

        function renderDetectionCalendar() {{
            const gridEl = document.getElementById('detection-calendar-grid');
            const summaryEl = document.getElementById('calendar-summary');
            if (!gridEl || !summaryEl) return;
            const months = getCalendarMonths();
            const activeDateCount = Object.keys(detectionCountsByDate)
                .filter((dateStr) => isDateInVisibleCalendar(dateStr))
                .length;
            if (months.length === 0) {{
                gridEl.innerHTML = '';
                summaryEl.textContent = '表示できる月がありません。';
                return;
            }}
            const monthNames = months.map((m) => monthLabel(m.year, m.month));
            summaryEl.textContent = `${{monthNames[0]}}${{monthNames.length > 1 ? ' 〜 ' + monthNames[monthNames.length - 1] : ''}} / 検出あり ${{activeDateCount}}日`;
            const weekdays = ['日', '月', '火', '水', '木', '金', '土'];
            const html = months.map(({{ year, month }}) => {{
                const firstDay = new Date(year, month, 1);
                const startWeekday = firstDay.getDay();
                const lastDate = new Date(year, month + 1, 0).getDate();
                const dayCells = [];
                for (let i = 0; i < startWeekday; i++) {{
                    dayCells.push('<div class="calendar-day-empty"></div>');
                }}
                for (let day = 1; day <= lastDate; day++) {{
                    const dateStr = `${{year}}-${{String(month + 1).padStart(2, '0')}}-${{String(day).padStart(2, '0')}}`;
                    const count = detectionCountsByDate[dateStr] || 0;
                    const classes = ['calendar-day'];
                    if (count > 0) classes.push('has-data');
                    if (dateStr === selectedDetectionDate) classes.push('selected');
                    dayCells.push(
                        `<button type="button" class="${{classes.join(' ')}}" data-date="${{dateStr}}" data-count-label="${{count}}件" title="${{count > 0 ? `${{dateLabel(dateStr)}}: ${{count}}件` : dateLabel(dateStr)}}">${{day}}</button>`
                    );
                }}
                return `
                    <div class="calendar-month">
                        <div class="calendar-month-title">${{monthLabel(year, month)}}</div>
                        <div class="calendar-weekdays">${{weekdays.map((d) => `<span>${{d}}</span>`).join('')}}</div>
                        <div class="calendar-days">${{dayCells.join('')}}</div>
                    </div>
                `;
            }}).join('');
            gridEl.innerHTML = html;
            gridEl.querySelectorAll('.calendar-day').forEach((btn) => {{
                btn.addEventListener('click', () => {{
                    selectedDetectionDate = btn.dataset.date || '';
                    renderDetectionCalendar();
                    renderSelectedDetections();
                }});
            }});
        }}

        function renderSelectedDetections() {{
            const listEl = document.getElementById('detection-list');
            const titleEl = document.getElementById('selected-date-title');
            if (!listEl || !titleEl) return;
            if (!selectedDetectionDate) {{
                titleEl.textContent = '日付を選択してください';
                listEl.innerHTML = '<div class="detection-item" style="color:#94a3b8">表示する日付を選択してください。</div>';
                return;
            }}
            const dateItems = detectionRecords
                .filter((d) => d.time.startsWith(selectedDetectionDate))
                .sort((a, b) => b.time.localeCompare(a.time));
            titleEl.textContent = `${{dateLabel(selectedDetectionDate)}} の検出`;
            if (dateItems.length === 0) {{
                listEl.innerHTML = '<div class="detection-item" style="color:#94a3b8">この日の検出はありません。</div>';
                return;
            }}

            const cameraNonMeteorCount = {{}};
            const cameraLabels = {{}};
            dateItems.forEach((d) => {{
                if (d.label === 'post_detected') {{
                    cameraNonMeteorCount[d.camera] = (cameraNonMeteorCount[d.camera] || 0) + 1;
                }}
                cameraLabels[d.camera] = d.camera_display || d.camera;
            }});

            const bulkDeleteButtons = Object.keys(cameraNonMeteorCount)
                .filter((camera) => cameraNonMeteorCount[camera] > 0)
                .map((camera) =>
                    `<button class="bulk-delete-btn" onclick="bulkDeleteNonMeteor('${{camera}}', event)">${{cameraLabels[camera] || camera}}: それ以外を一括削除 (${{cameraNonMeteorCount[camera]}}件)</button>`
                ).join('');

            const items = dateItems.map((d, idx) => {{
                const cameraKey = d.camera;
                const cameraLabel = d.camera_display || d.camera;
                const isManualRecording = d.source_type === 'manual_recording';
                const selKey = isManualRecording ? `manual::${{d.mp4}}` : `${{cameraKey}}::${{d.id}}`;
                const isSelected = selectedDetectionIds.has(selKey);
                const thumb = d.image
                    ? `<img class="detection-thumb" src="/image/${{encodeURI(d.image)}}" alt="${{cameraLabel}}" loading="lazy" onclick="showImage('${{d.image}}', '${{d.time}}', '${{cameraLabel}}', '${{d.confidence}}')">`
                    : '';
                const normalizedLabel = d.label === 'post_detected' ? 'post_detected' : 'detected';
                const radioName = `label-${{cameraKey}}-${{d.id || d.time}}-${{idx}}`.replace(/[^a-zA-Z0-9_-]/g, '_');
                const videoAction = d.mp4
                    ? `<span class="detection-link" onclick="showVideo('${{d.mp4}}', '${{d.time}}', '${{cameraLabel}}', '${{d.confidence}}')">${{isManualRecording ? 'プレビュー' : 'VIDEO'}}</span>`
                    : '';
                const imageAction = d.image
                    ? `<span class="detection-link" onclick="showImage('${{d.image}}', '${{d.time}}', '${{cameraLabel}}', '${{d.confidence}}')">画像</span>`
                    : '';
                const originalAction = d.composite_original
                    ? `<span class="detection-link" onclick="showImage('${{d.composite_original}}', '${{d.time}}', '${{cameraLabel}}', '${{d.confidence}}')">元画像</span>`
                    : '';
                const metaText = isManualRecording ? '種別: 手動録画' : `信頼度: ${{d.confidence}}`;
                const manageActions = isManualRecording ? `
                            <div class="detection-manage-actions">
                                <button class="delete-btn" onclick="deleteManualRecording('${{d.mp4}}', '${{d.time}}', event)">削除</button>
                            </div>
                ` : `
                            <div class="detection-manage-actions">
                                <div class="label-radios" data-label="${{normalizedLabel}}">
                                    <label class="label-radio">
                                        <input type="radio" name="${{radioName}}" value="detected" ${{normalizedLabel === 'detected' ? 'checked' : ''}}
                                               onchange="updateDetectionLabel('${{cameraKey}}', '${{d.id}}', 'detected', this)">
                                        <span>流星</span>
                                    </label>
                                    <label class="label-radio">
                                        <input type="radio" name="${{radioName}}" value="post_detected" ${{normalizedLabel === 'post_detected' ? 'checked' : ''}}
                                               onchange="updateDetectionLabel('${{cameraKey}}', '${{d.id}}', 'post_detected', this)">
                                        <span>それ以外</span>
                                    </label>
                                </div>
                                <button class="delete-btn" style="${{normalizedLabel === 'detected' ? 'display:none' : ''}}" onclick="deleteDetection('${{cameraKey}}', '${{d.id}}', '${{d.time}}', event)">削除</button>
                            </div>
                `;
                const cbHtml = `<input type="checkbox" class="detection-select-cb" data-key="${{selKey}}" ${{isSelected ? 'checked' : ''}}
                           onchange="toggleSelectItem('${{selKey}}', this.checked); this.closest('.detection-item').classList.toggle('sel-selected', this.checked)">`;
                const bodyContent = `
                        <div class="time">${{d.time}} | ${{cameraLabel}}</div>
                        ${{thumb}}
                        <div>${{metaText}}</div>
                        <div class="detection-actions">
                            <div class="detection-view-actions">
                                ${{videoAction}}
                                ${{imageAction}}
                                ${{originalAction}}
                            </div>
                            ${{manageActions}}
                        </div>
                `;
                return `
                    <div class="detection-item${{isSelected ? ' sel-selected' : ''}}">
                        <div class="detection-item-select-wrap">
                            ${{cbHtml}}
                            <div class="detection-item-body">${{bodyContent}}</div>
                        </div>
                    </div>
                `;
            }}).join('');

            listEl.innerHTML = `
                <div class="date-group">
                    <div class="date-group-header">
                        <span>${{dateLabel(selectedDetectionDate)}}</span>
                        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items:center;">
                            <button class="select-all-btn" onclick="selectAll()">全選択 / 全解除</button>
                            <button class="select-delete-btn" id="select-delete-btn" onclick="deleteSelected()" disabled>選択した 0 件を削除</button>
                            ${{bulkDeleteButtons}}
                        </div>
                    </div>
                    <div class="detection-group-grid">
                        ${{items}}
                    </div>
                </div>
            `;
        }}

        function syncSelectedDetectionDate() {{
            if (selectedDetectionDate && detectionCountsByDate[selectedDetectionDate]) {{
                return;
            }}
            const dates = Object.keys(detectionCountsByDate).sort((a, b) => b.localeCompare(a));
            selectedDetectionDate = dates[0] || '';
        }}

        function syncSelectedDateToCalendarRange() {{
            if (selectedDetectionDate && isDateInVisibleCalendar(selectedDetectionDate)) {{
                return;
            }}
            const visibleDates = Object.keys(detectionCountsByDate)
                .filter((dateStr) => isDateInVisibleCalendar(dateStr))
                .sort((a, b) => b.localeCompare(a));
            selectedDetectionDate = visibleDates[0] || '';
        }}

        function applyDetectionData(data) {{
            detectionRecords = Array.isArray(data.recent) ? data.recent.slice() : [];
            detectionCountsByDate = buildDetectionCounts(detectionRecords);
            detectionAvailableYears = buildDetectionYearOptions(detectionRecords);
            populateDetectionYearSelect();
            syncSelectedDetectionDate();
            syncSelectedDateToCalendarRange();
            renderDetectionCalendar();
            renderSelectedDetections();
        }}

        function updateDetections() {{
            if (!detectionsPageEnabled) {{
                return Promise.resolve();
            }}
            if (dashboardBackgroundPaused) {{
                return Promise.resolve();
            }}
            const totalEl = document.getElementById('total-detections');
            if (!totalEl) {{
                return Promise.resolve();
            }}
            return fetch('/detections', {{ cache: 'no-store' }})
                .then(r => r.json())
                .then(data => {{
                    if (dashboardBackgroundPaused) {{
                        return;
                    }}
                    detectionPollDelay = detectionPollBaseDelay;
                    totalEl.textContent = data.total;
                    const detectionsKey = (data.recent || []).map(d =>
                        `${{d.id || ''}}|${{d.camera}}|${{d.camera_display || d.camera}}|${{d.time}}|${{d.confidence}}|${{d.image}}|${{d.mp4}}|${{d.composite_original}}|${{d.label || ''}}|${{d.source_type || ''}}`
                    ).join('||');
                    if (detectionsKey === lastDetectionsKey) {{
                        return;
                    }}
                    lastDetectionsKey = detectionsKey;
                    applyDetectionData(data);
                }})
                .catch(err => {{
                    detectionPollDelay = Math.min(detectionPollDelay * 2, detectionPollMaxDelay);
                    console.warn('Detections fetch error:', err);
                }});
        }}

        function pollDetections() {{
            if (!detectionsPageEnabled) {{
                return;
            }}
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

        function bootDetectionSection() {{
            // 初回表示時はカメラ関連の接続より先に「最近の検出」を描画する。
            // サムネイル取得が始まるまでカメラストリーム開始を少し遅らせ、接続枠の競合を避ける。
            return updateDetections()
                .finally(() => {{
                    pollDetections();
                }});
        }}

        function setupDetectionCalendarControls() {{
            document.querySelectorAll('#detection-range-switch .range-btn').forEach((btn) => {{
                btn.addEventListener('click', () => {{
                    detectionCalendarRange = btn.dataset.range || 'current';
                    syncDetectionRangeControls();
                    syncSelectedDateToCalendarRange();
                    renderDetectionCalendar();
                    renderSelectedDetections();
                }});
            }});
            const yearSelect = document.getElementById('detection-year-select');
            if (yearSelect) {{
                yearSelect.addEventListener('change', (event) => {{
                    const nextYear = Number(event.target.value);
                    if (Number.isFinite(nextYear)) {{
                        detectionCalendarYear = nextYear;
                        detectionCalendarRange = 'year';
                        syncDetectionRangeControls();
                        syncSelectedDateToCalendarRange();
                        renderDetectionCalendar();
                        renderSelectedDetections();
                    }}
                }});
            }}
        }}

        if (detectionsPageEnabled) {{
            setupDetectionCalendarControls();
            bootDetectionSection();
        }}
        if (cameraPageEnabled) {{
            startCameraSection();
        }}

        // CHANGELOG表示
        function showChangelog() {{
            document.getElementById('changelog-modal').classList.add('active');
            fetch('/changelog')
                .then(r => r.text())
                .then(html => {{
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
    </main>
</body>
</html>'''
