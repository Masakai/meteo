"""Unit tests for detection_store.py."""

import json
import sqlite3
from pathlib import Path

import pytest

import detection_store


@pytest.fixture()
def db(tmp_path):
    """Return a path string for a fresh, initialized SQLite DB."""
    db_path = str(tmp_path / "detections.db")
    detection_store.init_db(db_path)
    return db_path


@pytest.fixture(autouse=True)
def reset_thread_local():
    """Clear the thread-local connection cache between tests."""
    yield
    if hasattr(detection_store._local, "conn"):
        detection_store._local.conn.close()
        del detection_store._local.conn
    if hasattr(detection_store._local, "db_path"):
        del detection_store._local.db_path


def _make_normalize_fn():
    """Return a trivial normalize function that uses the raw record as-is."""
    def normalize(camera_name, cam_dir, raw):
        return {
            "id": raw["id"],
            "timestamp": raw.get("timestamp", "2024-01-01T00:00:00"),
            "confidence": raw.get("confidence"),
            "base_name": raw.get("base_name", ""),
            "clip_path": raw.get("clip_path", ""),
            "image_path": raw.get("image_path", ""),
            "composite_original_path": raw.get("composite_original_path", ""),
            "alternate_clip_paths": raw.get("alternate_clip_paths", []),
            "label": raw.get("label", ""),
        }
    return normalize


class TestInitDb:
    def test_creates_detections_table(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        detection_store.init_db(db_path)
        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "detections" in tables

    def test_creates_jsonl_sync_state_table(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        detection_store.init_db(db_path)
        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "jsonl_sync_state" in tables

    def test_creates_required_columns(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        detection_store.init_db(db_path)
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(detections)").fetchall()}
        conn.close()
        expected = {"id", "camera", "timestamp", "confidence", "base_name",
                    "clip_path", "image_path", "composite_original_path",
                    "alternate_clip_paths", "label", "deleted", "raw_json"}
        assert expected.issubset(cols)

    def test_idempotent(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        detection_store.init_db(db_path)
        detection_store.init_db(db_path)  # should not raise


class TestSyncCameraFromJsonl:
    def _write_jsonl(self, path: Path, records: list) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")

    def _append_jsonl(self, path: Path, records: list) -> None:
        with open(path, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")

    def test_initial_sync_inserts_records(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        self._write_jsonl(cam_dir / "detections.jsonl", [
            {"id": "a1", "timestamp": "2024-01-01T00:00:00"},
            {"id": "a2", "timestamp": "2024-01-01T00:01:00"},
        ])
        n = detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())
        assert n == 2
        rows = detection_store.query_detections(db, camera="cam1")
        assert len(rows) == 2

    def test_offset_advances_on_append(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        jsonl = cam_dir / "detections.jsonl"
        self._write_jsonl(jsonl, [{"id": "a1", "timestamp": "2024-01-01T00:00:00"}])
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        # Append new record
        self._append_jsonl(jsonl, [{"id": "a2", "timestamp": "2024-01-01T00:01:00"}])
        n = detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())
        assert n == 1
        rows = detection_store.query_detections(db, camera="cam1")
        assert len(rows) == 2

    def test_no_duplicate_on_repeated_sync(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        self._write_jsonl(cam_dir / "detections.jsonl", [
            {"id": "a1", "timestamp": "2024-01-01T00:00:00"},
        ])
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())
        n = detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())
        assert n == 0

    def test_file_shrink_triggers_full_reread(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        jsonl = cam_dir / "detections.jsonl"
        self._write_jsonl(jsonl, [
            {"id": "a1", "timestamp": "2024-01-01T00:00:00"},
            {"id": "a2", "timestamp": "2024-01-01T00:01:00"},
        ])
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        # Rewrite with only one (different) record — file is smaller
        self._write_jsonl(jsonl, [{"id": "a3", "timestamp": "2024-01-02T00:00:00"}])
        n = detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())
        assert n == 1
        ids = {r["id"] for r in detection_store.query_detections(db, camera="cam1")}
        assert "a3" in ids

    def test_skips_empty_lines(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        jsonl = cam_dir / "detections.jsonl"
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write("\n")
            f.write(json.dumps({"id": "a1", "timestamp": "2024-01-01T00:00:00"}) + "\n")
            f.write("\n")
        n = detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())
        assert n == 1

    def test_skips_parse_error_lines(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        jsonl = cam_dir / "detections.jsonl"
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write("not valid json\n")
            f.write(json.dumps({"id": "a1", "timestamp": "2024-01-01T00:00:00"}) + "\n")
        n = detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())
        assert n == 1

    def test_offset_advances_past_bad_lines(self, db, tmp_path):
        """After syncing bad lines, re-sync should not re-process them."""
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        jsonl = cam_dir / "detections.jsonl"
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write("bad json\n")
            f.write(json.dumps({"id": "a1", "timestamp": "2024-01-01T00:00:00"}) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        # Append another record and verify only it is returned as new
        with open(jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "a2", "timestamp": "2024-01-01T00:01:00"}) + "\n")
        n = detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())
        assert n == 1


class TestSoftDelete:
    def test_soft_deleted_record_not_returned(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        jsonl = cam_dir / "detections.jsonl"
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "a1", "timestamp": "2024-01-01T00:00:00"}) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        detection_store.soft_delete(db, "a1")
        rows = detection_store.query_detections(db)
        assert all(r["id"] != "a1" for r in rows)

    def test_soft_deleted_record_returned_when_deleted_flag_true(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        jsonl = cam_dir / "detections.jsonl"
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "a1", "timestamp": "2024-01-01T00:00:00"}) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        detection_store.soft_delete(db, "a1")
        rows = detection_store.query_detections(db, deleted=True)
        assert any(r["id"] == "a1" for r in rows)


class TestCountAssetReferences:
    def _insert(self, db, detection_id, clip_path="", image_path="", composite_original_path="", alternate=None):
        conn = sqlite3.connect(db)
        alt_str = json.dumps(alternate or [])
        conn.execute(
            """
            INSERT INTO detections
                (id, camera, timestamp, clip_path, image_path, composite_original_path,
                 alternate_clip_paths, label, deleted, raw_json)
            VALUES (?,?,?,?,?,?,?,?,0,?)
            """,
            (detection_id, "cam1", "2024-01-01T00:00:00",
             clip_path, image_path, composite_original_path, alt_str, "", "{}"),
        )
        conn.commit()
        conn.close()

    def test_counts_clip_path_reference(self, db):
        self._insert(db, "a1", clip_path="cam1/clip.mp4")
        assert detection_store.count_asset_references(db, "cam1/clip.mp4") == 1

    def test_counts_image_path_reference(self, db):
        self._insert(db, "a1", image_path="cam1/img.jpg")
        assert detection_store.count_asset_references(db, "cam1/img.jpg") == 1

    def test_counts_composite_original_path_reference(self, db):
        self._insert(db, "a1", composite_original_path="cam1/comp.jpg")
        assert detection_store.count_asset_references(db, "cam1/comp.jpg") == 1

    def test_counts_alternate_clip_paths_reference(self, db):
        self._insert(db, "a1", alternate=["cam1/alt.mp4"])
        assert detection_store.count_asset_references(db, "cam1/alt.mp4") == 1

    def test_excludes_specified_id(self, db):
        self._insert(db, "a1", clip_path="cam1/clip.mp4")
        self._insert(db, "a2", clip_path="cam1/clip.mp4")
        assert detection_store.count_asset_references(db, "cam1/clip.mp4", exclude_id="a1") == 1

    def test_empty_path_returns_zero(self, db):
        assert detection_store.count_asset_references(db, "") == 0

    def test_no_reference_returns_zero(self, db):
        self._insert(db, "a1", clip_path="cam1/other.mp4")
        assert detection_store.count_asset_references(db, "cam1/clip.mp4") == 0

    def test_deleted_record_not_counted(self, db):
        self._insert(db, "a1", clip_path="cam1/clip.mp4")
        conn = sqlite3.connect(db)
        conn.execute("UPDATE detections SET deleted=1 WHERE id='a1'")
        conn.commit()
        conn.close()
        assert detection_store.count_asset_references(db, "cam1/clip.mp4") == 0

    def test_percent_in_path_does_not_wildcard_match(self, db):
        self._insert(db, "a1", alternate=["cam1/100%_clip.mp4"])
        # A path with a literal '%' should not match a different path
        assert detection_store.count_asset_references(db, "cam1/100%_clip.mp4") == 1
        assert detection_store.count_asset_references(db, "cam1/100x_clip.mp4") == 0

    def test_underscore_in_path_does_not_wildcard_match(self, db):
        self._insert(db, "a1", alternate=["cam1/clip_a.mp4"])
        # A literal '_' in the path should not match any single character
        assert detection_store.count_asset_references(db, "cam1/clip_a.mp4") == 1
        assert detection_store.count_asset_references(db, "cam1/clipXa.mp4") == 0


class TestResetSyncState:
    def test_resets_offset_and_mtime_to_zero(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        jsonl = cam_dir / "detections.jsonl"
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "a1", "timestamp": "2024-01-01T00:00:00"}) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        # Verify sync state was recorded (non-zero)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT offset, mtime FROM jsonl_sync_state WHERE camera='cam1'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] > 0

        detection_store.reset_sync_state(db, "cam1")

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT offset, mtime FROM jsonl_sync_state WHERE camera='cam1'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 0
        assert row[1] == 0.0

    def test_reset_for_nonexistent_camera_inserts_zero_row(self, db):
        detection_store.reset_sync_state(db, "cam_new")
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT offset, mtime FROM jsonl_sync_state WHERE camera='cam_new'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 0
        assert row[1] == 0.0


class TestSetLabel:
    def test_label_update_reflected_in_query(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        with open(cam_dir / "detections.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "a1", "timestamp": "2024-01-01T00:00:00"}) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        detection_store.set_label(db, "a1", "meteor")
        rows = detection_store.query_detections(db, camera="cam1")
        assert len(rows) == 1
        assert rows[0]["label"] == "meteor"

    def test_label_update_to_empty_string(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        with open(cam_dir / "detections.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "a1", "timestamp": "2024-01-01T00:00:00"}) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        detection_store.set_label(db, "a1", "meteor")
        detection_store.set_label(db, "a1", "")
        rows = detection_store.query_detections(db, camera="cam1")
        assert rows[0]["label"] == ""


class TestGetDetectionById:
    def _insert_via_jsonl(self, db, tmp_path, records):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir(exist_ok=True)
        with open(cam_dir / "detections.jsonl", "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

    def test_returns_existing_detection(self, db, tmp_path):
        self._insert_via_jsonl(db, tmp_path, [{"id": "a1", "timestamp": "2024-01-01T00:00:00"}])
        result = detection_store.get_detection_by_id(db, "a1")
        assert result is not None
        assert result["id"] == "a1"

    def test_returns_none_for_nonexistent_id(self, db, tmp_path):
        self._insert_via_jsonl(db, tmp_path, [{"id": "a1", "timestamp": "2024-01-01T00:00:00"}])
        result = detection_store.get_detection_by_id(db, "nonexistent")
        assert result is None

    def test_returns_deleted_record(self, db, tmp_path):
        self._insert_via_jsonl(db, tmp_path, [{"id": "a1", "timestamp": "2024-01-01T00:00:00"}])
        detection_store.soft_delete(db, "a1")
        result = detection_store.get_detection_by_id(db, "a1")
        assert result is not None
        assert result["deleted"] == 1


class TestQueryDetectionsForStats:
    def _insert_direct(self, db, records):
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(db)
        for rec in records:
            conn.execute(
                "INSERT INTO detections (id, camera, timestamp, deleted, raw_json) VALUES (?,?,?,0,?)",
                (rec["id"], rec["camera"], rec["timestamp"], "{}"),
            )
        conn.commit()
        conn.close()

    def test_returns_only_id_camera_timestamp(self, db):
        self._insert_direct(db, [
            {"id": "a1", "camera": "cam1", "timestamp": "2024-01-01T01:00:00"},
        ])
        rows = detection_store.query_detections_for_stats(db, "2024-01-01T00:00:00", "2024-01-01T06:00:00")
        assert len(rows) == 1
        assert set(rows[0].keys()) == {"id", "camera", "timestamp"}

    def test_filters_by_timestamp_range(self, db):
        self._insert_direct(db, [
            {"id": "a1", "camera": "cam1", "timestamp": "2024-01-01T02:00:00"},
            {"id": "a2", "camera": "cam1", "timestamp": "2024-01-01T08:00:00"},
        ])
        rows = detection_store.query_detections_for_stats(db, "2024-01-01T00:00:00", "2024-01-01T06:00:00")
        assert len(rows) == 1
        assert rows[0]["id"] == "a1"

    def test_excludes_deleted(self, db):
        self._insert_direct(db, [
            {"id": "a1", "camera": "cam1", "timestamp": "2024-01-01T02:00:00"},
        ])
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(db)
        conn.execute("UPDATE detections SET deleted=1 WHERE id='a1'")
        conn.commit()
        conn.close()
        rows = detection_store.query_detections_for_stats(db, "2024-01-01T00:00:00", "2024-01-01T06:00:00")
        assert len(rows) == 0

    def test_returns_ascending_order(self, db):
        self._insert_direct(db, [
            {"id": "a2", "camera": "cam1", "timestamp": "2024-01-01T03:00:00"},
            {"id": "a1", "camera": "cam1", "timestamp": "2024-01-01T01:00:00"},
        ])
        rows = detection_store.query_detections_for_stats(db, "2024-01-01T00:00:00", "2024-01-01T06:00:00")
        assert [r["id"] for r in rows] == ["a1", "a2"]


class TestQueryDetectionsLimit:
    def test_limit_restricts_result_count(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        records = [
            {"id": f"a{i}", "timestamp": f"2024-01-01T00:{i:02d}:00"}
            for i in range(5)
        ]
        with open(cam_dir / "detections.jsonl", "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        rows = detection_store.query_detections(db, limit=3)
        assert len(rows) == 3

    def test_limit_none_returns_all(self, db, tmp_path):
        cam_dir = tmp_path / "cam1"
        cam_dir.mkdir()
        records = [
            {"id": f"a{i}", "timestamp": f"2024-01-01T00:{i:02d}:00"}
            for i in range(5)
        ]
        with open(cam_dir / "detections.jsonl", "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
        detection_store.sync_camera_from_jsonl("cam1", cam_dir, db, _make_normalize_fn())

        rows = detection_store.query_detections(db, limit=None)
        assert len(rows) == 5
