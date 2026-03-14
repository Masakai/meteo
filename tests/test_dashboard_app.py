import dashboard


def test_create_app_health_endpoint(monkeypatch):
    monkeypatch.setattr(dashboard, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])
    monkeypatch.setattr(dashboard, "VERSION", "9.9.9")
    monkeypatch.setattr(dashboard, "_started", True)

    app = dashboard.create_app()
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "version": "9.9.9",
        "camera_count": 1,
    }
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_create_app_dashboard_page_has_no_cache_headers(monkeypatch):
    monkeypatch.setattr(dashboard, "_started", True)
    monkeypatch.setattr(dashboard, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])
    monkeypatch.setattr(dashboard, "VERSION", "1.2.3")
    monkeypatch.setattr(dashboard.routes, "_SERVER_START_TIME", 123.0)

    app = dashboard.create_app()
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert "最近の検出" in response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_monitors_start_once_when_served_via_wsgi(monkeypatch):
    calls = {"detection": 0, "camera": 0}

    def _start_detection_monitor():
        calls["detection"] += 1

    def _start_camera_monitor():
        calls["camera"] += 1

    monkeypatch.setattr(dashboard, "_started", False)
    monkeypatch.setattr(dashboard.routes, "start_detection_monitor", _start_detection_monitor)
    monkeypatch.setattr(dashboard.routes, "start_camera_monitor", _start_camera_monitor)
    monkeypatch.setattr(dashboard, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])

    app = dashboard.create_app()
    client = app.test_client()

    first = client.get("/health")
    second = client.get("/health")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == {"detection": 1, "camera": 1}
