import numpy as np
from datetime import datetime

from meteor_detector_realtime import (
    make_detection_base_name,
    make_detection_id,
    probe_rtsp_endpoint,
    resample_frames_to_cfr,
    sanitize_fps,
)


def test_sanitize_fps_returns_default_for_invalid_values():
    assert sanitize_fps(0, default=25.0) == 25.0
    assert sanitize_fps(-10, default=25.0) == 25.0
    assert sanitize_fps(1000, default=25.0) == 25.0
    assert sanitize_fps(None, default=25.0) == 25.0


def _frames(timestamps):
    """時刻列から (時刻, 識別可能な画像) のリストを作る"""
    return [
        (t, np.full((2, 2, 3), idx % 256, dtype=np.uint8))
        for idx, t in enumerate(timestamps)
    ]


def _run(timestamps, out_fps):
    frames = _frames(timestamps)
    stats = []
    out = list(resample_frames_to_cfr(frames, out_fps, stats=stats))
    return out, stats[-1]


def _ids(frames_out):
    """出力フレーム列を、元フレームの識別値の列に変換する"""
    return [int(f[0, 0, 0]) for f in frames_out]


def _run_lengths(ids):
    """同一フレームの連続回数の列を返す"""
    runs = []
    for value in ids:
        if runs and runs[-1][0] == value:
            runs[-1][1] += 1
        else:
            runs.append([value, 1])
    return [count for _, count in runs]


def test_resample_10fps_input_to_20fps_grid_duplicates_each_frame():
    """夜間の実効10fpsを20fps格子へ: 各フレームが2回ずつ、脱落なし"""
    timestamps = [i * 0.1 for i in range(11)]  # 10fps・1.0秒
    out, stats = _run(timestamps, 20.0)

    assert stats.n_out == 21  # 1.0秒 * 20fps + 1
    assert stats.n_dropped == 0
    assert stats.n_used == 11
    assert stats.max_run == 2
    assert _run_lengths(_ids(out))[:-1] == [2] * 10


def test_resample_20fps_input_to_20fps_grid_is_identity():
    timestamps = [i * 0.05 for i in range(21)]
    out, stats = _run(timestamps, 20.0)

    assert stats.n_out == 21
    assert stats.n_dropped == 0
    assert stats.max_run == 1
    assert _ids(out) == list(range(21))


def test_resample_uneven_arrival_keeps_real_duration():
    """0.05/0.05/0.2秒の偏り: 中央値推定は20fpsを返すが実効は10fps

    現行の中央値方式が2倍速を生む入力パターン。再配置後の再生時間が
    入力の実時間と一致し、入力フレームが脱落しないことを確認する。
    """
    timestamps = [0.0]
    for _ in range(10):
        timestamps += [timestamps[-1] + 0.05, timestamps[-1] + 0.10, timestamps[-1] + 0.30]

    span = timestamps[-1] - timestamps[0]
    out, stats = _run(timestamps, 20.0)

    # 再生時間が実時間と一致する（n_outは両端を含むためn_out-1格子分）
    assert abs((stats.n_out - 1) / 20.0 - span) <= 1.0 / 20.0
    # 0.05秒間隔のフレームも20fps格子に収まるため脱落しない
    assert stats.n_dropped == 0
    assert stats.n_used == len(timestamps)
    assert len(out) == stats.n_out


def test_resample_simultaneous_arrivals_are_dropped_but_duration_holds():
    """ほぼ同時到着が半数を超える入力（現行推定が200fps前後を返す）

    格子より細かい間隔のフレームは出力に現れないが、再生時間は実時間を保つ。
    脱落はn_droppedで検知できる。
    """
    timestamps = []
    for i in range(10):
        base = i * 0.1
        timestamps += [base, base + 0.001, base + 0.002]

    span = timestamps[-1] - timestamps[0]
    out, stats = _run(timestamps, 20.0)

    assert abs((stats.n_out - 1) / 20.0 - span) <= 1.0 / 20.0
    assert stats.n_dropped > 0  # 同時到着分が脱落する
    assert stats.n_used + stats.n_dropped == len(timestamps)
    assert len(out) == stats.n_out


def test_resample_fps_change_midway_is_tracked():
    """途中で10fpsから20fpsへ変化: 複製連長が2から1へ変わる"""
    timestamps = [i * 0.1 for i in range(6)]          # 10fps・0.5秒
    timestamps += [timestamps[-1] + (i + 1) * 0.05 for i in range(10)]  # 20fps・0.5秒

    span = timestamps[-1] - timestamps[0]
    out, stats = _run(timestamps, 20.0)

    assert abs((stats.n_out - 1) / 20.0 - span) <= 1.0 / 20.0
    assert stats.n_dropped == 0

    runs = _run_lengths(_ids(out))
    assert runs[0] == 2    # 10fps区間は2回ずつ
    assert runs[-2] == 1   # 20fps区間は1回ずつ


def test_resample_gap_is_filled_with_previous_frame():
    """2秒の欠落区間は直前フレームの複製で埋まる"""
    timestamps = [0.0, 0.05, 0.10, 2.10, 2.15]
    out, stats = _run(timestamps, 20.0)

    assert stats.n_out == int(2.15 * 20) + 1
    assert stats.n_dropped == 0
    assert stats.max_run == 40  # 0.10秒のフレームが2.10秒直前まで40スロット継続
    assert _ids(out)[3] == 2    # 欠落区間は直前フレーム(index 2)で埋まる


def test_resample_handles_degenerate_inputs():
    assert list(resample_frames_to_cfr([], 20.0)) == []

    single, stats = _run([1.5], 20.0)
    assert len(single) == 1
    assert stats.n_out == 1
    assert stats.n_dropped == 0

    # 時刻の逆行・停滞は除外される（例外を出さない）
    out, stats = _run([0.0, 0.05, 0.04, 0.05, 0.10], 20.0)
    assert stats.n_dropped == 2
    assert _ids(out) == [0, 1, 4]


def test_resample_uses_sanitized_out_fps():
    """不正なout_fpsはsanitize_fpsの既定値へ丸められる"""
    timestamps = [i * (1.0 / 30.0) for i in range(31)]
    out, stats = _run(timestamps, 0)  # 0 -> 既定30.0

    assert stats.n_out == 31
    assert len(out) == 31




def test_probe_rtsp_endpoint_reports_tcp_ok(monkeypatch):
    class _DummySocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("meteor_detector_realtime.socket.create_connection", lambda addr, timeout=0: _DummySocket())
    result = probe_rtsp_endpoint("rtsp://user:pass@10.0.1.11/live")
    assert "probe=tcp_ok" in result
    assert "host=10.0.1.11" in result
    assert "port=554" in result


def test_probe_rtsp_endpoint_reports_tcp_error(monkeypatch):
    def _raise(addr, timeout=0):
        raise TimeoutError("timed out")

    monkeypatch.setattr("meteor_detector_realtime.socket.create_connection", _raise)
    result = probe_rtsp_endpoint("rtsp://user:pass@10.0.1.11:8554/live")
    assert "probe=tcp_error" in result
    assert "port=8554" in result
    assert "TimeoutError" in result


def test_make_detection_id_is_stable():
    record = {
        "timestamp": "2026-02-07T22:00:00.123456",
        "start_time": 1.0,
        "end_time": 1.4,
        "start_point": [10, 20],
        "end_point": [40, 50],
    }
    detection_id = make_detection_id("camera1", record)
    assert detection_id.startswith("det_")
    assert detection_id == make_detection_id("camera1", record)


def test_make_detection_base_name_avoids_existing_collision(tmp_path):
    detection_id = "det_1234567890abcdef1234"
    first = make_detection_base_name(tmp_path, datetime(2026, 2, 7, 22, 0, 0), detection_id)
    assert first == "meteor_20260207_220000_12345678"

    (tmp_path / f"{first}.mp4").write_bytes(b"x")
    second = make_detection_base_name(tmp_path, datetime(2026, 2, 7, 22, 0, 0), detection_id)
    assert second == "meteor_20260207_220000_12345678_02"
