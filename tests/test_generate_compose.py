import hashlib
import pytest
import generate_compose as gc
from generate_compose import (
    _compute_file_hash,
    load_generated_hashes,
    should_generate_mask,
    generate_compose,
    generate_go2rtc_config,
    generate_logrotate_conf,
    _is_usable_candidate_ip,
    generate_service,
    generate_station_reporter,
)


def test_generate_compose_includes_webrtc_dashboard_and_go2rtc(tmp_path):
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live||東側\n", encoding="utf-8")

    compose = generate_compose(
        str(streamers),
        {
            "sensitivity": "medium",
            "scale": "0.5",
            "buffer": "15",
            "exclude_bottom": "0.0625",
            "extract_clips": "true",
            "latitude": "35.0",
            "longitude": "139.0",
            "enable_time_window": "true",
            "mask_output_dir": "masks",
            "mask_dilate": "20",
            "mask_save": "",
            "streaming_mode": "webrtc",
            "go2rtc_api_port": 1984,
            "go2rtc_webrtc_port": 8555,
            "go2rtc_config_path": "./go2rtc.yaml",
            "go2rtc_candidate_host": "10.0.1.59",
        },
        base_port=8080,
    )

    assert "meteor-go2rtc" in compose
    assert "CAMERA1_STREAM_KIND=webrtc" in compose
    assert "CAMERA1_STREAM_URL=http://localhost:1984/stream.html?src=camera1&mode=webrtc&mode=mse&mode=hls&mode=mjpeg&background=false" in compose
    assert "./go2rtc.yaml:/config/go2rtc.yaml" in compose


def test_generate_go2rtc_config_uses_camera_sources():
    config = generate_go2rtc_config(
        [
            {"url": "rtsp://user:pass@192.168.0.11/live"},
            {"url": "rtsp://user:pass@192.168.0.12/live"},
        ],
        {"go2rtc_candidate_host": "10.0.1.59", "go2rtc_webrtc_port": 8555},
    )
    assert 'origin: "*"' in config
    assert "webrtc:" in config
    assert "    - 10.0.1.59:8555" in config
    assert "camera1:" in config
    assert "camera2:" in config
    assert "rtsp://user:pass@192.168.0.11/live" in config
    assert "rtsp://user:pass@192.168.0.12/live" in config


def test_generate_compose_defaults_streaming_mode_to_webrtc(tmp_path):
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live\n", encoding="utf-8")

    compose = generate_compose(
        str(streamers),
        {
            "sensitivity": "medium",
            "scale": "0.5",
            "buffer": "15",
            "exclude_bottom": "0.0625",
            "extract_clips": "true",
            "latitude": "35.0",
            "longitude": "139.0",
            "enable_time_window": "true",
            "mask_output_dir": "masks",
            "mask_dilate": "20",
            "mask_save": "",
            "go2rtc_api_port": 1984,
            "go2rtc_webrtc_port": 8555,
            "go2rtc_config_path": "./go2rtc.yaml",
            "go2rtc_candidate_host": "10.0.1.59",
        },
        base_port=8080,
    )

    assert "meteor-go2rtc" in compose
    assert "CAMERA1_STREAM_KIND=webrtc" in compose


_BASE_SETTINGS = {
    "sensitivity": "medium",
    "scale": "0.5",
    "buffer": "15",
    "exclude_bottom": "0.0625",
    "extract_clips": "true",
    "latitude": "35.0",
    "longitude": "139.0",
    "enable_time_window": "true",
    "mask_output_dir": "masks",
    "mask_dilate": "20",
    "mask_save": "",
    "streaming_mode": "webrtc",
    "go2rtc_api_port": 1984,
    "go2rtc_webrtc_port": 8555,
    "go2rtc_config_path": "./go2rtc.yaml",
    "go2rtc_candidate_host": "10.0.1.59",
}


def test_generate_compose_exits_when_mask_set_and_cv2_unavailable(tmp_path, monkeypatch):
    """マスク指定 + cv2 なしの場合は sys.exit(1) で中止する"""
    mask_file = tmp_path / "mask.jpg"
    mask_file.write_bytes(b"")

    streamers = tmp_path / "streamers"
    streamers.write_text(f"rtsp://user:pass@192.168.0.11/live|{mask_file}|East\n", encoding="utf-8")

    monkeypatch.setattr(gc, "cv2", None)

    with pytest.raises(SystemExit) as exc_info:
        generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)

    assert exc_info.value.code == 1


def test_generate_compose_no_exit_when_no_mask_and_cv2_unavailable(tmp_path, monkeypatch):
    """マスク未指定なら cv2 がなくても中止しない"""
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live||East\n", encoding="utf-8")

    monkeypatch.setattr(gc, "cv2", None)

    compose = generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)
    assert "meteor-camera1" in compose


def test_is_usable_candidate_ip_rejects_invalid_string():
    assert _is_usable_candidate_ip("not-an-ip") is False


def test_is_usable_candidate_ip_rejects_loopback():
    assert _is_usable_candidate_ip("127.0.0.1") is False


def test_is_usable_candidate_ip_accepts_private_ip():
    assert _is_usable_candidate_ip("192.168.0.1") is True


def test_generate_service_debug_tools_arg(tmp_path):
    """debug_tools=True のとき DEBUG_TOOLS が出力されること"""
    settings = {
        **_BASE_SETTINGS,
        "debug_tools": True,
        "mask_dilate": "5",
        "mask_save": "",
    }
    rtsp_info = {"host": "192.168.0.11", "url": "rtsp://user:pass@192.168.0.11/live", "display_name": "East"}
    result = generate_service(1, rtsp_info, settings, 8081, "")
    assert 'DEBUG_TOOLS: "true"' in result


def test_generate_compose_mjpeg_mode(tmp_path):
    """mjpeg モードでは CAMERA*_STREAM_KIND=mjpeg になること"""
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live\n", encoding="utf-8")

    settings = {**_BASE_SETTINGS, "streaming_mode": "mjpeg"}
    compose = generate_compose(str(streamers), settings, base_port=8080)

    assert "CAMERA1_STREAM_KIND=mjpeg" in compose
    assert "meteor-go2rtc" not in compose


def test_generate_compose_youtube_key(tmp_path):
    """youtube_key が指定されたとき CAMERA*_YOUTUBE_KEY が出力されること"""
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live|||youtube:mykey-xxxx\n", encoding="utf-8")

    compose = generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)

    assert "CAMERA1_YOUTUBE_KEY=mykey-xxxx" in compose
    assert "CAMERA1_RTSP_URL=" in compose


def test_generate_station_reporter_contains_config_path():
    result = generate_station_reporter("station.json")
    assert "station.json" in result
    assert "meteor-station-reporter" in result


def test_generate_compose_invalid_url_no_password(tmp_path, capsys):
    """無効URLでパスワードなしの場合、netloc がそのまま警告に出力されること"""
    streamers = tmp_path / "streamers"
    # パスワードなしの無効URL（http:// スキームは parse_rtsp_url が None を返す）
    streamers.write_text("http://host/path\n", encoding="utf-8")

    with pytest.raises(ValueError):
        generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)

    captured = capsys.readouterr()
    assert "host" in captured.out
    assert "***" not in captured.out


def test_generate_compose_with_station_config(tmp_path):
    """station_config が存在する場合、station-reporter サービスが含まれること"""
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live\n", encoding="utf-8")

    station_json = tmp_path / "station.json"
    station_json.write_text('{"id": "test"}', encoding="utf-8")

    settings = {**_BASE_SETTINGS, "station_config": str(station_json)}
    compose = generate_compose(str(streamers), settings, base_port=8080)

    assert "meteor-station-reporter" in compose


def test_generate_compose_mask_path_success(tmp_path, monkeypatch):
    """マスク画像が正常に生成される場合、compose にマスクパスが含まれること"""
    mask_file = tmp_path / "mask.jpg"
    mask_file.write_bytes(b"dummy")

    streamers = tmp_path / "streamers"
    streamers.write_text(f"rtsp://user:pass@192.168.0.11/live|{mask_file}|East\n", encoding="utf-8")

    import generate_compose as gc_module
    monkeypatch.setattr(gc_module, "cv2", object())  # cv2 が None でないようにする
    monkeypatch.setattr(gc_module, "generate_mask_file", lambda *a, **kw: str(tmp_path / "masks/camera1_mask.png"))

    compose = generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)
    assert "mask_image.png" in compose


def test_generate_compose_mask_path_failure(tmp_path, monkeypatch, capsys):
    """マスク生成が RuntimeError を送出した場合は sys.exit(1) すること"""
    mask_file = tmp_path / "mask.jpg"
    mask_file.write_bytes(b"dummy")

    streamers = tmp_path / "streamers"
    streamers.write_text(f"rtsp://user:pass@192.168.0.11/live|{mask_file}|East\n", encoding="utf-8")

    import generate_compose as gc_module
    monkeypatch.setattr(gc_module, "cv2", object())
    monkeypatch.setattr(gc_module, "generate_mask_file", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("failed")))

    with pytest.raises(SystemExit) as exc_info:
        generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)

    assert exc_info.value.code == 1
    assert "マスク生成に失敗" in capsys.readouterr().out


def test_generate_compose_includes_twilight_env_vars(tmp_path):
    """生成された compose に TWILIGHT_* 環境変数が含まれること"""
    streamers = tmp_path / "streamers"
    streamers.write_text("rtsp://user:pass@192.168.0.11/live||東側\n", encoding="utf-8")

    compose = generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)

    assert "TWILIGHT_DETECTION_MODE=reduce" in compose
    assert "TWILIGHT_TYPE=nautical" in compose
    assert "TWILIGHT_SENSITIVITY=low" in compose
    assert "TWILIGHT_MIN_SPEED=200" in compose


def test_generate_compose_invalid_url_masks_password(tmp_path, capsys):
    """無効URLの警告出力でパスワードが *** に置換されること"""
    streamers = tmp_path / "streamers"
    # http:// スキームは parse_rtsp_url が無効と判定するため警告ブランチに入る
    streamers.write_text("http://user:secretpass@host/path\n", encoding="utf-8")

    with pytest.raises(ValueError):
        generate_compose(str(streamers), _BASE_SETTINGS, base_port=8080)

    captured = capsys.readouterr()
    assert "secretpass" not in captured.out
    assert "***" in captured.out


# --- ハッシュ管理関数のテスト ---

def test_compute_file_hash_existing(tmp_path):
    """既知バイト列のハッシュが正しいことを確認"""
    data = b"hello world"
    f = tmp_path / "test.bin"
    f.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert _compute_file_hash(f) == expected


def test_compute_file_hash_missing(tmp_path):
    """存在しないファイル → 空文字列"""
    assert _compute_file_hash(tmp_path / "nonexistent.bin") == ""


def test_load_generated_hashes_missing(tmp_path):
    """ファイルなし → 空dict"""
    assert load_generated_hashes(tmp_path / "hashes.json") == {}


def test_load_generated_hashes_corrupt(tmp_path):
    """JSON破損 → 空dict"""
    f = tmp_path / "hashes.json"
    f.write_text("not valid json", encoding="utf-8")
    assert load_generated_hashes(f) == {}


def test_should_generate_mask_new_file(tmp_path):
    """ファイルなし → (True, 'new')"""
    result = should_generate_mask(tmp_path / "camera1_mask.png", "", force=False)
    assert result == (True, "new")


def test_should_generate_mask_no_record(tmp_path):
    """ファイルは存在するが stored_hash が空文字 → (True, 'no_record')"""
    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(b"some mask data")
    result = should_generate_mask(mask_file, "", force=False)
    assert result == (True, "no_record")


def test_should_generate_mask_hash_match(tmp_path):
    """ハッシュ一致 → (True, 'unchanged')"""
    data = b"mask data"
    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(data)
    stored = hashlib.sha256(data).hexdigest()
    result = should_generate_mask(mask_file, stored, force=False)
    assert result == (True, "unchanged")


def test_should_generate_mask_hash_mismatch(tmp_path):
    """ハッシュ不一致 → (False, 'manually_modified')"""
    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(b"current content")
    stored = hashlib.sha256(b"original content").hexdigest()
    result = should_generate_mask(mask_file, stored, force=False)
    assert result == (False, "manually_modified")


def test_should_generate_mask_force(tmp_path):
    """force=True かつ不一致でも → (True, 'force')"""
    mask_file = tmp_path / "camera1_mask.png"
    mask_file.write_bytes(b"current content")
    stored = hashlib.sha256(b"original content").hexdigest()
    result = should_generate_mask(mask_file, stored, force=True)
    assert result == (True, "force")


# --- generate_logrotate_conf のテスト ---

def test_generate_logrotate_conf_contains_daily():
    result = generate_logrotate_conf("/home/user/meteo", ["logs/camera*.log"])
    assert "daily" in result


def test_generate_logrotate_conf_contains_dateext():
    result = generate_logrotate_conf("/home/user/meteo", ["logs/camera*.log"])
    assert "dateext" in result


def test_generate_logrotate_conf_contains_copytruncate():
    result = generate_logrotate_conf("/home/user/meteo", ["logs/camera*.log"])
    assert "copytruncate" in result


def test_generate_logrotate_conf_contains_rotate_90():
    result = generate_logrotate_conf("/home/user/meteo", ["logs/camera*.log"])
    assert "rotate 90" in result


def test_generate_logrotate_conf_contains_dateformat():
    result = generate_logrotate_conf("/home/user/meteo", ["logs/camera*.log"])
    assert "dateformat -%Y%m%d" in result


def test_generate_logrotate_conf_contains_all_patterns():
    patterns = ["logs/camera*.log", "logs/dashboard.log", "logs/ffmpeg_youtube*.log"]
    result = generate_logrotate_conf("/srv/meteo", patterns)
    assert "/srv/meteo/logs/camera*.log" in result
    assert "/srv/meteo/logs/dashboard.log" in result
    assert "/srv/meteo/logs/ffmpeg_youtube*.log" in result


def test_generate_logrotate_conf_path_uses_cwd():
    result = generate_logrotate_conf("/custom/path", ["logs/camera*.log"])
    assert "/custom/path/logs/camera*.log" in result
