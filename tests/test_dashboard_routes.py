import dashboard_routes as dr
import io


class _DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class _DummyHandler:
    def __init__(self, path):
        self.path = path
        self.headers = {}
        self.sent_headers = {}
        self.status = None
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.status = code

    def send_header(self, _name, _value):
        self.sent_headers[_name] = _value

    def end_headers(self):
        pass


def test_camera_url_for_proxy_localhost(monkeypatch):
    monkeypatch.setattr(dr, "_IN_DOCKER", False)
    url = "http://localhost:9000/foo"
    assert dr._camera_url_for_proxy(url, camera_index=0) == "http://host.docker.internal:9000/foo"


def test_camera_url_for_proxy_docker(monkeypatch):
    monkeypatch.setattr(dr, "_IN_DOCKER", True)
    url = "http://localhost:9000/foo"
    assert dr._camera_url_for_proxy(url, camera_index=1) == "http://camera2:8080"


def test_camera_url_for_proxy_non_localhost(monkeypatch):
    monkeypatch.setattr(dr, "_IN_DOCKER", False)
    url = "http://example.com:8080/stream"
    assert dr._camera_url_for_proxy(url, camera_index=0) == url


def test_handle_camera_restart_success(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])

    def _fake_urlopen(_req, timeout=0):
        assert timeout == 5
        return _DummyResponse(b'{"success": true}')

    monkeypatch.setattr(dr, "urlopen", _fake_urlopen)
    handler = _DummyHandler("/camera_restart/0")
    assert dr.handle_camera_restart(handler) is True
    assert handler.status == 202
    assert b'"success": true' in handler.wfile.getvalue()


def test_handle_camera_restart_invalid_index(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])
    handler = _DummyHandler("/camera_restart/99")
    assert dr.handle_camera_restart(handler) is True
    assert handler.status == 503
    assert b'"success": false' in handler.wfile.getvalue().lower()


def test_handle_camera_snapshot_success(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam-1", "url": "http://localhost:8081"}])

    def _fake_urlopen(_req, timeout=0):
        assert timeout == 5
        return _DummyResponse(b"JPEGDATA")

    monkeypatch.setattr(dr, "urlopen", _fake_urlopen)
    handler = _DummyHandler("/camera_snapshot/0?download=1")
    assert dr.handle_camera_snapshot(handler) is True
    assert handler.status == 200
    assert handler.sent_headers.get("Content-type") == "image/jpeg"
    assert "attachment; filename=" in handler.sent_headers.get("Content-Disposition", "")
    assert handler.wfile.getvalue() == b"JPEGDATA"


def test_handle_camera_snapshot_invalid_index(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])
    handler = _DummyHandler("/camera_snapshot/99")
    assert dr.handle_camera_snapshot(handler) is True
    assert handler.status == 503
