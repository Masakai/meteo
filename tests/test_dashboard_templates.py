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


def test_render_dashboard_includes_settings_link():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert 'href="/settings"' in html


def test_render_dashboard_includes_global_detection_controls():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert "setGlobalDetectionEnabled(false)" in html
    assert "setGlobalDetectionEnabled(true)" in html
    assert 'id="global-detection-control-status"' in html


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


def test_render_dashboard_includes_runtime_fps_warning_logic():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="cameras",
    )
    assert "sourceFps * 0.8" in html
    assert "80%未満" in html
    assert "param-fps-warning" in html


def test_render_dashboard_supports_webrtc_camera_embed():
    html = render_dashboard_html(
        cameras=[
            {
                "name": "cam1",
                "url": "http://localhost:8081",
                "stream_url": "http://localhost:1984/stream.html?src=camera1&mode=webrtc&mode=mse",
                "stream_kind": "webrtc",
            }
        ],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="cameras",
    )
    assert 'id="stream-frame0"' in html
    assert "function isWebRTCStream(i)" in html
    assert "function bindStreamEventHandlers(i)" in html
    assert "stream.html?src=camera1&mode=webrtc&mode=mse" in html


def test_render_dashboard_includes_recording_controls():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
        page_mode="cameras",
    )
    assert "録画予約" in html
    assert 'id="recording-panel0"' in html
    assert "function scheduleRecording(i)" in html
    assert "function stopRecording(i)" in html
    assert "camera_recording_schedule" in html


def test_render_dashboard_detection_view_supports_manual_recordings():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert "const isManualRecording = d.source_type === 'manual_recording';" in html
    assert "種別: 手動録画" in html
    assert "deleteManualRecording" in html
    assert "プレビュー" in html
