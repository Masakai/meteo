import subprocess
import dashboard_camera_handlers as dch


def _reset_caches():
    dch._qsv_available_cache = None
    dch._vaapi_available_cache = None


def test_check_qsv_available_true(monkeypatch):
    _reset_caches()

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dch._check_qsv_available() is True


def test_check_qsv_available_false(monkeypatch):
    _reset_caches()

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dch._check_qsv_available() is False


def test_check_qsv_available_exception(monkeypatch):
    _reset_caches()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("ffmpeg")))
    assert dch._check_qsv_available() is False


def test_check_qsv_available_cached(monkeypatch):
    _reset_caches()
    dch._qsv_available_cache = True
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(1))
    assert dch._check_qsv_available() is True
    assert called == []  # subprocess.run が呼ばれていないこと


def test_check_vaapi_available_true(monkeypatch):
    _reset_caches()

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dch._check_vaapi_available() is True


def test_check_vaapi_available_false(monkeypatch):
    _reset_caches()

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dch._check_vaapi_available() is False


def test_check_vaapi_available_exception(monkeypatch):
    _reset_caches()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("ffmpeg")))
    assert dch._check_vaapi_available() is False


def test_check_vaapi_available_cached(monkeypatch):
    _reset_caches()
    dch._vaapi_available_cache = False
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(1))
    assert dch._check_vaapi_available() is False
    assert called == []  # subprocess.run が呼ばれていないこと


def test_youtube_start_uses_qsv_when_available(monkeypatch):
    """QSV利用可能時は h264_qsv が選択される"""
    _reset_caches()
    monkeypatch.setattr(dch, "_check_qsv_available", lambda: True)
    monkeypatch.setattr(dch, "_check_vaapi_available", lambda: True)
    monkeypatch.setattr(dch, "_stop_youtube_process", lambda i: None)

    started = []

    def fake_thread(target, args, daemon, name):
        class T:
            def start(self):
                started.append(args[1])  # cmd
        return T()

    import threading
    monkeypatch.setattr(threading, "Thread", fake_thread)
    monkeypatch.setattr(dch, "_youtube_active", {})
    monkeypatch.setattr(dch, "_youtube_threads", {})

    import io, json

    class Handler:
        path = "/youtube_start/0"
        wfile = io.BytesIO()
        def send_response(self, c): pass
        def send_header(self, k, v): pass
        def end_headers(self): pass

    cameras = [{"youtube_key": "test-key"}]
    dch.handle_youtube_start(Handler(), cameras, "", lambda p: 0, None, None)

    cmd = started[0]
    assert "h264_qsv" in cmd
    assert "h264_vaapi" not in cmd
    assert "libx264" not in cmd


def test_youtube_start_uses_vaapi_when_qsv_unavailable(monkeypatch):
    """QSV不可・VAAPI利用可能時は h264_vaapi が選択される"""
    _reset_caches()
    monkeypatch.setattr(dch, "_check_qsv_available", lambda: False)
    monkeypatch.setattr(dch, "_check_vaapi_available", lambda: True)
    monkeypatch.setattr(dch, "_stop_youtube_process", lambda i: None)

    started = []

    def fake_thread(target, args, daemon, name):
        class T:
            def start(self):
                started.append(args[1])
        return T()

    import threading
    monkeypatch.setattr(threading, "Thread", fake_thread)
    monkeypatch.setattr(dch, "_youtube_active", {})
    monkeypatch.setattr(dch, "_youtube_threads", {})

    import io

    class Handler:
        path = "/youtube_start/0"
        wfile = io.BytesIO()
        def send_response(self, c): pass
        def send_header(self, k, v): pass
        def end_headers(self): pass

    cameras = [{"youtube_key": "test-key"}]
    dch.handle_youtube_start(Handler(), cameras, "", lambda p: 0, None, None)

    cmd = started[0]
    assert "h264_vaapi" in cmd
    assert "h264_qsv" not in cmd
    assert "libx264" not in cmd


def test_youtube_start_uses_libx264_when_no_hw(monkeypatch):
    """QSV・VAAPI両方不可の場合は libx264 が選択される"""
    _reset_caches()
    monkeypatch.setattr(dch, "_check_qsv_available", lambda: False)
    monkeypatch.setattr(dch, "_check_vaapi_available", lambda: False)
    monkeypatch.setattr(dch, "_stop_youtube_process", lambda i: None)

    started = []

    def fake_thread(target, args, daemon, name):
        class T:
            def start(self):
                started.append(args[1])
        return T()

    import threading
    monkeypatch.setattr(threading, "Thread", fake_thread)
    monkeypatch.setattr(dch, "_youtube_active", {})
    monkeypatch.setattr(dch, "_youtube_threads", {})

    import io

    class Handler:
        path = "/youtube_start/0"
        wfile = io.BytesIO()
        def send_response(self, c): pass
        def send_header(self, k, v): pass
        def end_headers(self): pass

    cameras = [{"youtube_key": "test-key"}]
    dch.handle_youtube_start(Handler(), cameras, "", lambda p: 0, None, None)

    cmd = started[0]
    assert "libx264" in cmd
    assert "h264_qsv" not in cmd
    assert "h264_vaapi" not in cmd
