import dashboard_routes as dr


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
