import numpy as np
from datetime import datetime

import cv2

from meteor_detector_realtime import (
    DetectionParams,
    EventMerger,
    MeteorEvent,
    RealtimeMeteorDetector,
    estimate_fps_from_frames,
    make_detection_base_name,
    make_detection_id,
    probe_rtsp_endpoint,
    sanitize_fps,
)


def _event(start_time, end_time, start_point, end_point, confidence=0.7):
    return MeteorEvent(
        timestamp=datetime(2026, 8, 15, 1, 55, 0),
        start_time=start_time,
        end_time=end_time,
        start_point=start_point,
        end_point=end_point,
        peak_brightness=220.0,
        confidence=confidence,
        frames=[],
    )


def test_sanitize_fps_returns_default_for_invalid_values():
    assert sanitize_fps(0, default=25.0) == 25.0
    assert sanitize_fps(-10, default=25.0) == 25.0
    assert sanitize_fps(1000, default=25.0) == 25.0
    assert sanitize_fps(None, default=25.0) == 25.0


def test_estimate_fps_from_frames_20fps():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    # 0.05s間隔 -> 20fps
    frames = [(0.00, frame), (0.05, frame), (0.10, frame), (0.15, frame), (0.20, frame)]
    fps = estimate_fps_from_frames(frames, fallback_fps=30.0)
    assert abs(fps - 20.0) < 0.5


def test_estimate_fps_from_frames_15fps():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    # 0.0667s間隔 -> 約15fps
    frames = [(0.00, frame), (0.0667, frame), (0.1334, frame), (0.2001, frame)]
    fps = estimate_fps_from_frames(frames, fallback_fps=30.0)
    assert abs(fps - 15.0) < 0.5


def test_estimate_fps_from_frames_rejects_fps_far_above_negotiated():
    # 2026-08-16に本番greeng4で観測された事象の再現。接続時fps=20.0のカメラで
    # camera1/meteor_20260816_032802_79d9e49b.mp4 が108fpsで書き出されていた。
    # 約9.3ms間隔はsanitize_fps()の有効帯(1.0〜120.0)の内側のため既存の上限では
    # 弾けず、fallback_fps(20.0)との比率でのみ検出できる。
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frames = [(i / 108.0, frame) for i in range(20)]
    fps = estimate_fps_from_frames(frames, fallback_fps=20.0)
    assert fps == 20.0


def test_estimate_fps_from_frames_rejects_fps_within_sanitize_range():
    # 同上、camera2/meteor_20260816_030601_7f6b0f81.mp4 の117fpsケース。
    # 120.0未満のためsanitize_fps()を素通りする値であることが本テストの要点。
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frames = [(i / 117.0, frame) for i in range(20)]
    fps = estimate_fps_from_frames(frames, fallback_fps=20.0)
    assert fps == 20.0


def test_estimate_fps_from_frames_allows_normal_variation_within_ratio():
    # Tapo C120は夜間IRモードで実効fpsが接続時ネゴシエーション値(20.0)より
    # 下がることがある。10fps程度への低下は異常値ではないため推定値をそのまま使う。
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frames = [(0.00, frame), (0.10, frame), (0.20, frame), (0.30, frame)]
    fps = estimate_fps_from_frames(frames, fallback_fps=20.0)
    assert abs(fps - 10.0) < 0.5


def test_estimate_fps_from_frames_allows_fps_just_below_ratio_limit():
    # 許容倍率1.5の境界。fallback_fps=20.0に対し29.0fpsは閾値30.0未満のため
    # 推定値をそのまま採用する（境界判定は > のため30.0ちょうどはクランプされる）。
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frames = [(i / 29.0, frame) for i in range(20)]
    fps = estimate_fps_from_frames(frames, fallback_fps=20.0)
    assert abs(fps - 29.0) < 0.5


def _run_merger(merger, events, advance_to=None):
    """本番と同じ経路（add_event → 内部で flush_expired）でイベントを流す。

    pending へ直接 extend して flush_all() を1回呼ぶ書き方では、バースト判定を
    行う _note_arrival() を通らないうえ、確定が1バッチにまとまるため
    「flushが分割されても抑制できるか」を検証できない。必ずこの経路を使う。
    """
    finalized = []
    for ev in events:
        finalized.extend(merger.add_event(ev))
    if advance_to is not None:
        finalized.extend(merger.flush_expired(advance_to))
    finalized.extend(merger.flush_all())
    return finalized


def test_event_merger_rejects_simultaneous_burst():
    # 2026-08-15 01:55:00 にcamera2で発生した158件バーストの再現。
    # start_timeが0.192秒の幅に集中し、各イベントは画面上の別座標に散在するため
    # _is_mergeable の距離条件では結合されない。全件が破棄されることを確認する。
    params = DetectionParams()
    merger = EventMerger(params)
    events = []
    for i in range(158):
        start = 5328.271 + (i % 3) * 0.096
        # 座標はmerge_max_distance(80px)を超えて散在させる
        events.append(_event(start, start + 0.40, (100 + i * 13, 200), (160 + i * 13, 260)))

    assert _run_merger(merger, events, advance_to=5340.0) == []


def test_event_merger_rejects_burst_with_scattered_end_times():
    # end_time がばらつくと flush_expired() の排出が複数回に分割される。
    # 確定バッチ単位で判定する実装ではこの場合に抑制が効かなかった
    # （実データでも270バースト中38件で end_time が大きくばらついていた）。
    params = DetectionParams()
    merger = EventMerger(params)
    events = []
    for i in range(158):
        start = 5328.271 + (i % 3) * 0.096
        # 20fpsで1フレームぶんずつ end_time をずらす
        end = start + 0.40 + i * 0.05
        events.append(_event(start, end, (100 + i * 13, 200), (160 + i * 13, 260)))

    assert _run_merger(merger, events, advance_to=5400.0) == []


def test_event_merger_keeps_normal_meteor_events():
    # 通常の流星は時間的に離れて発生するためバースト判定に掛からない。
    params = DetectionParams()
    merger = EventMerger(params)
    events = [
        _event(100.0, 100.5, (10, 10), (60, 60)),
        _event(200.0, 200.5, (20, 20), (70, 70)),
        _event(300.0, 300.5, (30, 30), (80, 80)),
    ]

    assert len(_run_merger(merger, events, advance_to=400.0)) == 3


def test_event_merger_keeps_burst_at_threshold():
    # burst_max_events(5件)ちょうどは破棄しない（閾値は「超えた場合」）。
    params = DetectionParams()
    merger = EventMerger(params)
    events = [
        _event(50.0 + i * 0.05, 50.4 + i * 0.05, (100 + i * 200, 200), (160 + i * 200, 260))
        for i in range(params.burst_max_events)
    ]

    finalized = _run_merger(merger, events, advance_to=60.0)
    assert len(finalized) == params.burst_max_events


def test_event_merger_rejects_only_burst_window():
    # バースト窓の外にある正常なイベントは残す。
    params = DetectionParams()
    merger = EventMerger(params)
    burst = [
        _event(50.0 + i * 0.05, 50.4 + i * 0.05, (100 + i * 200, 200), (160 + i * 200, 260))
        for i in range(20)
    ]
    isolated = _event(500.0, 500.5, (10, 10), (60, 60))

    finalized = _run_merger(merger, burst + [isolated], advance_to=600.0)
    assert finalized == [isolated]


def test_event_merger_does_not_burst_reject_merged_fragments():
    # トラッキングの瞬断で1つの流星が複数の断片に分かれ、_is_mergeable の
    # 条件（時間・距離・速度差）で結合されるのは正常系。断片の数だけ到着として
    # 数えると burst_max_events を超えて誤って全破棄されることがあった
    # （実測で6断片の単一流星がburst_max_events=5を超えて全破棄される事例を確認）。
    params = DetectionParams()
    merger = EventMerger(params)
    fragments = []
    t = 100.0
    x, y = 500, 500
    for i in range(6):
        end = t + 0.1
        fragments.append(_event(t, end, (x, y), (x + 10, y + 10)))
        t = end + 0.05  # merge_max_gap_time(1.5秒)より十分短い間隔
        x += 5
        y += 5

    finalized = _run_merger(merger, fragments, advance_to=t + 100)
    # 実測: 5番目の断片(index 4)で speed_ratio が merge_max_speed_ratio(0.5)を
    # 超えて分裂するため、6断片は2件のイベントにマージされる
    # （前半4断片が1件、後半2断片が1件）。破棄されずに残ることが要点。
    assert len(finalized) == 2


def test_event_merger_burst_window_connects_trailing_isolated_event():
    # ギャップクラスタリングの定義上の挙動: バースト終息直後、
    # burst_window_time秒以内に到着した次のイベントは単連結クラスタの
    # 続きとして連結され、クラスタごと破棄される。これは無関係なイベントを
    # 誤検知しているのではなく方式の定義通り。
    params = DetectionParams()
    merger = EventMerger(params)
    burst = [
        _event(1000.0 + i * 0.02, 1000.4 + i * 0.02, (100 + i * 200, 200), (160 + i * 200, 260))
        for i in range(10)
    ]
    burst_end = burst[-1].start_time
    trailing = _event(burst_end + 0.5, burst_end + 0.9, (999999, 999999), (999999, 999999))

    finalized = _run_merger(merger, burst + [trailing], advance_to=burst_end + 100)
    assert finalized == []


def test_event_merger_burst_window_releases_event_beyond_window():
    # burst_window_timeを超えて離れたイベントはクラスタに連結されず残る。
    params = DetectionParams()
    merger = EventMerger(params)
    burst = [
        _event(1000.0 + i * 0.02, 1000.4 + i * 0.02, (100 + i * 200, 200), (160 + i * 200, 260))
        for i in range(10)
    ]
    burst_end = burst[-1].start_time
    far = _event(burst_end + 2.0, burst_end + 2.4, (999999, 999999), (999999, 999999))

    finalized = _run_merger(merger, burst + [far], advance_to=burst_end + 100)
    assert finalized == [far]


def test_event_merger_handles_non_monotonic_arrival_order():
    # EventMergerはトラッキング側の複数トラックが並行して確定する場合など、
    # start_timeが到着順(FIFO)と一致しない状況を受け取りうる。到着ログの
    # 窓管理が到着順の先頭を「最古」と仮定していると、非単調な到着で
    # 不正な状態になる（begin > end の区間が生成される等）。座標を大きく
    # 離してマージが起きないようにし、内部状態が破綻しないことを確認する。
    params = DetectionParams()
    merger = EventMerger(params)
    arrivals = [100.00, 100.05, 100.10, 99.90, 100.15, 100.20, 100.02]
    events = [
        _event(st, st + 0.4, (i * 10000, i * 10000), (i * 10000 + 50, i * 10000 + 50))
        for i, st in enumerate(arrivals)
    ]
    # 例外を送出せず、_arrival_timesが単調増加を仮定した実装で壊れないことを確認する。
    # 実測: 7件は到着間隔1.0秒以内の単一クラスタとなりburst_max_events(5)を超えるため
    # 全件がバーストとして破棄される。
    finalized = _run_merger(merger, events, advance_to=200.0)
    assert finalized == []
    assert merger._burst_dropped == 7


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


def test_detection_params_default_values_are_not_clamped():
    # 既定値はレンジ内であり、クランプが発動しないことを確認する。
    params = DetectionParams()
    assert params.exclude_bottom_ratio == 1 / 16
    assert params.exclude_edge_ratio == 0.0
    assert params.burst_window_time == 1.0
    assert params.burst_max_events == 5


def test_detection_params_clamps_out_of_range_values(capsys):
    params = DetectionParams(
        exclude_bottom_ratio=1.5,
        exclude_edge_ratio=0.9,
        burst_window_time=-1.0,
        burst_max_events=0,
    )
    assert params.exclude_bottom_ratio == 1.0
    assert params.exclude_edge_ratio == 0.5
    assert params.burst_window_time == 0.0
    assert params.burst_max_events == 1

    captured = capsys.readouterr()
    assert "[WARN]" in captured.out
    assert "exclude_bottom_ratio" in captured.out
    assert "exclude_edge_ratio" in captured.out
    assert "burst_window_time" in captured.out
    assert "burst_max_events" in captured.out


def test_detection_params_warns_when_burst_span_exceeds_prune_retention(capsys):
    # burst_max_events × burst_window_time が _prune_arrival_times() の
    # 保持幅（10 × max(burst_window_time, merge_max_gap_time)）を超える場合、
    # クランプはしないが警告を出す。
    DetectionParams(burst_window_time=5.0, burst_max_events=100, merge_max_gap_time=1.5)
    captured = capsys.readouterr()
    assert "[WARN] バースト抑制の設定が保持幅を超えています" in captured.out


def test_detect_bright_objects_roi_matches_full_frame_calculation():
    # detect_bright_objects の brightness / nuisance_overlap_ratio 計算を
    # 輪郭のROI(外接矩形)に限定した実装に変更したが、結果はフレーム全面で
    # マスクを確保する旧方式と完全一致するはず（uint8の合計・カウントなので
    # 誤差は生じない）。複数の候補輪郭・ノイズ帯マスクとの重なりを含めて検証する。
    height, width = 120, 160
    frame = np.full((height, width), 50, dtype=np.uint8)
    prev_frame = np.full((height, width), 50, dtype=np.uint8)

    # 3つの明るい矩形（面積・輝度が異なる）を候補として配置。
    # 3つ目は非対称な外接矩形（rx != ry, rw != rh）とし、ノイズ帯が候補矩形を
    # 部分的にのみ覆うようにする。これにより boundingRect の offset(-rx, -ry)
    # の1pxずれや、ROIスライス座標の入れ替え（[rx:rx+rw, ry:ry+rh]）といった
    # 実装ミスが混入した場合に overlap_ratio の値が変化し、テストが検出できる
    # （対称形状・完全内包/完全非重複のみだとこれらの変異が数学的に無害化される）。
    cv2.rectangle(frame, (10, 10), (25, 25), 220, -1)   # 通常の明るい物体（ノイズ帯対象外）
    cv2.rectangle(frame, (60, 60), (68, 68), 210, -1)   # small_area閾値以下、ノイズ帯と完全重なり→除外される
    cv2.rectangle(frame, (30, 70), (46, 76), 205, -1)   # small_area閾値以下、ノイズ帯と部分的に重なる（非対称）

    nuisance_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.rectangle(nuisance_mask, (55, 55), (75, 75), 255, -1)  # 2つ目の矩形を完全に内包
    cv2.rectangle(nuisance_mask, (30, 70), (38, 76), 255, -1)  # 3つ目の矩形を部分的に重なる

    params = DetectionParams(
        diff_threshold=30,
        min_area=5,
        max_area=10000,
        min_brightness=100,
        small_area_threshold=100,
        nuisance_overlap_threshold=0.60,
        exclude_bottom_ratio=0.0,
        exclude_edge_ratio=0.0,
    )
    detector = RealtimeMeteorDetector(params, fps=20, nuisance_mask=nuisance_mask)

    objects = detector.detect_bright_objects(frame, prev_frame)

    # ノイズ帯と完全重なりの矩形(overlap_ratio=1.0 >= 0.60)は候補段階で除外される。
    # 部分重なりの矩形(overlap_ratio≈0.53 < 0.60)は残る。
    assert len(objects) == 2
    by_brightness = {round(o["brightness"]): o for o in objects}
    assert sorted(by_brightness) == [205, 220]
    assert by_brightness[220]["nuisance_overlap_ratio"] == 0.0
    assert round(by_brightness[205]["nuisance_overlap_ratio"], 4) == 0.5304

    # 除外閾値を1.0超にして overlap_ratio 自体の計算値（ROIスライスでの正確さ）を検証する。
    params_no_reject = DetectionParams(
        diff_threshold=30,
        min_area=5,
        max_area=10000,
        min_brightness=100,
        small_area_threshold=100,
        nuisance_overlap_threshold=1.5,
        exclude_bottom_ratio=0.0,
        exclude_edge_ratio=0.0,
    )
    detector_no_reject = RealtimeMeteorDetector(params_no_reject, fps=20, nuisance_mask=nuisance_mask)
    objects_all = detector_no_reject.detect_bright_objects(frame, prev_frame)

    assert len(objects_all) == 3
    by_brightness = {round(o["brightness"]): o for o in objects_all}
    assert by_brightness[220]["nuisance_overlap_ratio"] == 0.0
    # 内包される矩形は輪郭全域がノイズ帯内なのでoverlap_ratioは1.0
    assert by_brightness[210]["nuisance_overlap_ratio"] == 1.0
    # 部分的に重なる非対称矩形は、offsetの1pxずれやROIスライス座標の
    # 入れ替えといった実装ミスがあれば異なる値を返す（1pxずれなら0.5、
    # 座標入れ替えなら形状不一致でValueError）。
    assert round(by_brightness[205]["nuisance_overlap_ratio"], 4) == 0.5304
