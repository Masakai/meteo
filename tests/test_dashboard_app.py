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


def test_create_app_camera_embed_page(monkeypatch):
    monkeypatch.setattr(dashboard, "_started", True)
    monkeypatch.setattr(
        dashboard,
        "CAMERAS",
        [
            {
                "name": "cam1",
                "url": "http://localhost:8081",
                "display_name": "東側",
                "stream_kind": "webrtc",
                "stream_url": "http://localhost:1984/stream.html?src=camera1&mode=webrtc",
            }
        ],
    )

    app = dashboard.create_app()
    client = app.test_client()

    response = client.get("/camera_embed/0")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "video-stream" in body
    assert "/go2rtc_asset/video-stream.js" in body
    assert "const go2rtcPort = 1984;" in body
    assert "const sourceName = 'camera1';" in body
    assert "const wsOrigin = `${wsScheme}//${hostname}:${go2rtcPort}`;" in body
    assert "player.media = 'video';" in body
    assert "player.src = wsUrl.toString();" in body


def test_create_app_go2rtc_asset_proxy(monkeypatch):
    monkeypatch.setattr(dashboard, "_started", True)
    monkeypatch.setattr(
        dashboard,
        "CAMERAS",
        [
            {
                "name": "cam1",
                "url": "http://localhost:8081",
                "display_name": "東側",
                "stream_kind": "webrtc",
                "stream_url": "http://localhost:1984/stream.html?src=camera1&mode=webrtc",
            }
        ],
    )

    class _DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"console.log('ok');"

    def _fake_urlopen(req, timeout=0):
        assert req.full_url == "http://localhost:1984/video-stream.js"
        assert timeout == 5
        return _DummyResponse()

    monkeypatch.setattr(dashboard, "urlopen", _fake_urlopen)

    app = dashboard.create_app()
    client = app.test_client()

    response = client.get("/go2rtc_asset/video-stream.js")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "console.log('ok');"


def test_create_app_go2rtc_asset_proxy_uses_container_host_inside_docker(monkeypatch):
    monkeypatch.setattr(dashboard, "_started", True)
    monkeypatch.setattr(
        dashboard,
        "CAMERAS",
        [
            {
                "name": "cam1",
                "url": "http://localhost:8081",
                "display_name": "東側",
                "stream_kind": "webrtc",
                "stream_url": "http://localhost:1984/stream.html?src=camera1&mode=webrtc",
            }
        ],
    )

    class _DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"console.log('ok');"

    def _fake_urlopen(req, timeout=0):
        assert req.full_url == "http://go2rtc:1984/video-stream.js"
        assert timeout == 5
        return _DummyResponse()

    monkeypatch.setattr(dashboard.os.path, "exists", lambda path: path == "/.dockerenv")
    monkeypatch.setattr(dashboard, "urlopen", _fake_urlopen)

    app = dashboard.create_app()
    client = app.test_client()

    response = client.get("/go2rtc_asset/video-stream.js")

    assert response.status_code == 200
