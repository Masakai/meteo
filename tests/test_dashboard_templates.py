from dashboard_templates import render_dashboard_html


def test_render_dashboard_uses_server_side_monitoring_ui():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert "document.addEventListener('visibilitychange', syncDashboardVisibilityState);" in html
    assert "バックグラウンド一時停止" in html
    assert "function evaluateAutoRecovery" not in html
    assert "triggerStreamToggleRecovery" not in html
    assert "console.warn('[auto-recovery]'" not in html


def test_render_dashboard_includes_stream_toggle_controls():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="cameras",
    )
    assert "常時表示" in html
    assert "toggleStreamEnabled(0, this.checked)" in html


def test_render_dashboard_camera_image_opens_camera_server():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="cameras",
    )
    assert 'onclick="openCameraServer(0)"' in html
    assert 'title="クリックでカメラサーバを開く"' in html
    assert "function getCameraBrowserBaseUrl(i)" in html
    assert "function openCameraServer(i)" in html
    assert "window.open(url, '_blank', 'noopener,noreferrer');" in html


def test_render_dashboard_includes_settings_link():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert 'href="/settings"' in html


def test_render_dashboard_includes_camera_server_alive_indicator():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="cameras",
    )
    assert 'id="server-status0"' in html
    assert 'title="カメラサーバ生存"' in html


def test_render_dashboard_includes_indicator_help_messages():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="cameras",
    )
    assert "ストリーム接続状態（緑: 接続中 / 赤: 切断 / 灰: 常時表示オフ）" in html
    assert "カメラサーバ生存状態（緑: 応答あり / 赤: 応答なし / 灰: 判定保留）" in html
    assert "検出処理状態（赤点滅: 検出中 / 緑: 期間外 / 黄: 期間内だが停止疑い / 灰: 状態確認中）" in html
    assert "マスク適用状態（赤: マスク有効 / 灰: マスク無効）" in html


def test_render_dashboard_includes_detection_indicator_state_logic():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="cameras",
    )
    assert "function updateDetectionIndicator(i, data, statsFetchOk)" in html
    assert "検出処理状態（黄: 検出期間内だが停止疑い" in html
    assert "検出処理状態（緑: 検出期間外）" in html


def test_render_dashboard_includes_youtube_upload_ui():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="detections",
    )
    assert "function loadYoutubeStatus()" in html
    assert "function uploadDetectionToYoutube(camera, detectionId, cameraLabel, time, event)" in html
    assert "YOUTUBE" in html


def test_render_dashboard_includes_meteor_calendar_data_and_styles():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="detections",
    )
    assert "const meteorCalendarEntries =" in html
    assert "しぶんぎ座流星群" in html
    assert ".calendar-day.meteor-active" in html
    assert ".calendar-day.meteor-peak" in html
    assert "function getMeteorShowersForDate(dateStr)" in html
    assert "function buildCalendarTooltip(count, meteorInfo)" in html
