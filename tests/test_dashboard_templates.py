from dashboard_templates import render_dashboard_html


def test_render_dashboard_uses_server_side_monitoring_ui():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert "document.addEventListener('visibilitychange', syncDashboardVisibilityState);" in html
    assert "function evaluateAutoRecovery" not in html
    assert "triggerStreamToggleRecovery" not in html
    assert "console.warn('[auto-recovery]'" not in html


def test_render_dashboard_includes_rtsp_web_controls():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert "rtsp_web 操作パネル" in html
    assert "タブ起動 (:8081)" in html
    assert "openCameraTab(0)" in html
    assert 'id="control-url0"' in html
    assert 'id="latest-time0"' in html
    assert "最終検出時刻" in html
    assert "全カメラ設定" in html
    assert "applySettingsAll()" in html
    assert "マスクリセット" in html
    assert "resetMask(0)" in html
    assert 'id="meteor-lamp0"' in html
    assert "視野内検出 OFF" in html
    assert "/apply_settings_all" in html
    assert "resolveCameraTabUrl" in html
    assert "window.location.hostname" in html
    assert "window.location.href = target;" in html
