import dashboard_routes as dr
import io
import json


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
    def __init__(self, path, body=b"", headers=None):
        self.path = path
        self.headers = headers.copy() if headers else {}
        if "Content-Length" not in self.headers:
            self.headers["Content-Length"] = str(len(body))
        self.sent_headers = {}
        self.status = None
        self.rfile = io.BytesIO(body)
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


def test_parse_camera_index_with_query(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])
    assert dr._parse_camera_index("/camera_stream/0?t=12345") == 0


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


def test_handle_set_detection_label_success(monkeypatch, tmp_path):
    monkeypatch.setattr(dr, "DETECTIONS_DIR", str(tmp_path))
    body = json.dumps(
        {"camera": "camera1", "time": "2026-02-07 22:00:00", "label": "post_detected"}
    ).encode("utf-8")
    handler = _DummyHandler("/detection_label", body=body, headers={"Content-Type": "application/json"})

    assert dr.handle_set_detection_label(handler) is True
    assert handler.status == 200
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["success"] is True
    saved = json.loads((tmp_path / "detection_labels.json").read_text(encoding="utf-8"))
    assert saved["camera1|2026-02-07 22:00:00"] == "post_detected"


def test_handle_detections_includes_label(monkeypatch, tmp_path):
    monkeypatch.setattr(dr, "DETECTIONS_DIR", str(tmp_path))
    cam_dir = tmp_path / "camera1"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "detections.jsonl").write_text(
        json.dumps({"timestamp": "2026-02-07T22:00:00", "confidence": 0.9}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "detection_labels.json").write_text(
        json.dumps({"camera1|2026-02-07 22:00:00": "post_detected"}),
        encoding="utf-8",
    )

    handler = _DummyHandler("/detections")
    assert dr.handle_detections(handler) is None
    assert handler.status == 200
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["recent"][0]["label"] == "post_detected"


def test_handle_detections_normalizes_legacy_label(monkeypatch, tmp_path):
    monkeypatch.setattr(dr, "DETECTIONS_DIR", str(tmp_path))
    cam_dir = tmp_path / "camera1"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "detections.jsonl").write_text(
        json.dumps({"timestamp": "2026-02-07T22:00:00", "confidence": 0.9}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "detection_labels.json").write_text(
        json.dumps({"camera1|2026-02-07 22:00:00": "review"}),
        encoding="utf-8",
    )

    handler = _DummyHandler("/detections")
    assert dr.handle_detections(handler) is None
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["recent"][0]["label"] == "detected"


def test_handle_dashboard_stats(monkeypatch):
    monkeypatch.setattr(dr, "get_dashboard_cpu_snapshot", lambda refresh=True: {"cpu_percent": 12.3})
    handler = _DummyHandler("/dashboard_stats")
    assert dr.handle_dashboard_stats(handler) is True
    assert handler.status == 200
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["cpu_percent"] == 12.3


def test_handle_camera_stats_returns_monitor_snapshot(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])
    monkeypatch.setattr(
        dr,
        "_camera_monitor_state",
        {
            0: {
                "camera": "cam1",
                "stream_alive": True,
                "monitor_enabled": True,
                "monitor_stop_reason": "none",
                "monitor_checked_at": 123.4,
            }
        },
    )
    handler = _DummyHandler("/camera_stats/0")
    assert dr.handle_camera_stats(handler) is True
    assert handler.status == 200
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["camera"] == "cam1"
    assert payload["monitor_enabled"] is True
    assert payload["monitor_stop_reason"] == "none"


def test_camera_monitor_triggers_restart_on_timeout(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])
    monkeypatch.setattr(dr, "_CAMERA_MONITOR_ENABLED", True)
    monkeypatch.setattr(dr, "_CAMERA_RESTART_COOLDOWN_SEC", 0.0)
    monkeypatch.setattr(dr, "_camera_monitor_state", {})

    def _fake_urlopen(req, timeout=0):
        url = req.full_url
        if url.endswith("/stats"):
            return _DummyResponse(b'{"camera":"cam1","stream_alive":false}')
        if url.endswith("/restart"):
            return _DummyResponse(b'{"success": true}')
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(dr, "urlopen", _fake_urlopen)
    dr._refresh_camera_monitor_once()
    snap = dr.get_camera_monitor_snapshot(0)
    assert snap["monitor_stop_reason"] == "timeout"
    assert snap["monitor_restart_count"] == 1


def test_handle_settings_page(monkeypatch):
    monkeypatch.setattr(dr, "render_settings_html", lambda cameras, version: "<html>settings</html>")
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])
    monkeypatch.setattr(dr, "VERSION", "0.0.0")
    handler = _DummyHandler("/settings")
    assert dr.handle_settings_page(handler) is True
    assert handler.status == 200
    assert b"settings" in handler.wfile.getvalue()


def test_handle_camera_settings_current(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])

    def _fake_urlopen(req, timeout=0):
        assert req.full_url.endswith("/stats")
        assert timeout == 5
        return _DummyResponse(b'{"settings":{"diff_threshold":20,"nuisance_overlap_threshold":0.6}}')

    monkeypatch.setattr(dr, "urlopen", _fake_urlopen)
    handler = _DummyHandler("/camera_settings/current")
    assert dr.handle_camera_settings_current(handler) is True
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["success"] is True
    assert payload["settings"]["diff_threshold"] == 20


def test_handle_camera_settings_apply_all(monkeypatch):
    monkeypatch.setattr(dr, "CAMERAS", [{"name": "cam1", "url": "http://localhost:8081"}])

    def _fake_urlopen(req, timeout=0):
        assert req.full_url.endswith("/apply_settings")
        assert req.get_method() == "POST"
        return _DummyResponse(b'{"success": true, "applied": {"diff_threshold": 20}}')

    monkeypatch.setattr(dr, "urlopen", _fake_urlopen)
    body = json.dumps({"diff_threshold": 20}).encode("utf-8")
    handler = _DummyHandler("/camera_settings/apply_all", body=body, headers={"Content-Type": "application/json"})
    assert dr.handle_camera_settings_apply_all(handler) is True
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["success"] is True
    assert payload["applied_count"] == 1
