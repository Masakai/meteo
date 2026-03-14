import hashlib
import json

from scripts.rescue_orphan_detection_files import make_detection_id as make_rescue_detection_id


def test_rescued_detection_id_matches_runtime_rule():
    record = {
        "timestamp": "2026-02-07T22:00:00",
        "confidence": 0.0,
        "base_name": "meteor_20260207_220000_deadbeef",
        "rescued_from_orphan": True,
    }
    source = {
        "camera": "camera1",
        "timestamp": "2026-02-07T22:00:00",
        "start_time": "",
        "end_time": "",
        "start_point": "",
        "end_point": "",
    }
    digest = hashlib.sha1(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    assert make_rescue_detection_id("camera1", record) == f"det_{digest[:20]}"
