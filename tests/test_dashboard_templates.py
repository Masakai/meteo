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
    )
    assert "常時表示" in html
    assert "toggleStreamEnabled(0, this.checked)" in html
