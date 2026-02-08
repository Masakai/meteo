from dashboard_templates import render_dashboard_html


def test_render_dashboard_includes_auto_restart_and_failure_dialog():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert "fetch('/camera_restart/' + i, { method: 'POST' })" in html
    assert "alert('カメラの電源が入っていないかハングアップしています');" in html


def test_render_dashboard_includes_stream_toggle_controls():
    html = render_dashboard_html(
        cameras=[{"name": "cam1", "url": "http://localhost:8081"}],
        version="0.0.0",
        server_start_time=0.0,
    )
    assert "常時表示" in html
    assert "toggleStreamEnabled(0, this.checked)" in html
