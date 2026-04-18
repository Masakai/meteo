"""migrate_camera_dirs.py のユニットテスト"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from migrate_camera_dirs import (
    _backup_db,
    _merge_jsonl,
    _move_media_files,
    _unique_path,
    _update_db,
    find_migration_targets,
    migrate,
)


class TestFindMigrationTargets:
    def test_detects_ip_based_directory(self, tmp_path):
        (tmp_path / "camera1_10_0_1_15").mkdir()
        targets = find_migration_targets(tmp_path)
        assert targets == [("camera1_10_0_1_15", "camera1")]

    def test_skips_index_based_directory(self, tmp_path):
        (tmp_path / "camera1").mkdir()
        targets = find_migration_targets(tmp_path)
        assert targets == []

    def test_multiple_cameras(self, tmp_path):
        (tmp_path / "camera1_10_0_1_15").mkdir()
        (tmp_path / "camera2_10_0_1_3").mkdir()
        (tmp_path / "camera3_10_0_1_11").mkdir()
        targets = find_migration_targets(tmp_path)
        assert targets == [
            ("camera1_10_0_1_15", "camera1"),
            ("camera2_10_0_1_3", "camera2"),
            ("camera3_10_0_1_11", "camera3"),
        ]

    def test_skips_files(self, tmp_path):
        (tmp_path / "camera1_10_0_1_15").touch()
        targets = find_migration_targets(tmp_path)
        assert targets == []

    def test_mixed_directories(self, tmp_path):
        (tmp_path / "camera1_10_0_1_15").mkdir()
        (tmp_path / "camera1").mkdir()
        (tmp_path / "other_dir").mkdir()
        targets = find_migration_targets(tmp_path)
        assert targets == [("camera1_10_0_1_15", "camera1")]


class TestUniquePath:
    def test_returns_dest_when_not_exists(self, tmp_path):
        dest = tmp_path / "file.mp4"
        assert _unique_path(dest) == dest

    def test_adds_suffix_when_exists(self, tmp_path):
        dest = tmp_path / "file.mp4"
        dest.touch()
        result = _unique_path(dest)
        assert result == tmp_path / "file_1.mp4"

    def test_increments_suffix(self, tmp_path):
        dest = tmp_path / "file.mp4"
        dest.touch()
        (tmp_path / "file_1.mp4").touch()
        result = _unique_path(dest)
        assert result == tmp_path / "file_2.mp4"

    def test_no_extension(self, tmp_path):
        dest = tmp_path / "file"
        dest.touch()
        result = _unique_path(dest)
        assert result == tmp_path / "file_1"


class TestMergeJsonl:
    def test_creates_new_file_when_dest_not_exists(self, tmp_path):
        src = tmp_path / "src.jsonl"
        dest = tmp_path / "dest.jsonl"
        src.write_bytes(b'{"a": 1}\n')
        _merge_jsonl(src, dest)
        assert dest.read_bytes() == b'{"a": 1}\n'

    def test_appends_to_existing_file(self, tmp_path):
        src = tmp_path / "src.jsonl"
        dest = tmp_path / "dest.jsonl"
        dest.write_bytes(b'{"existing": 1}\n')
        src.write_bytes(b'{"new": 2}\n')
        _merge_jsonl(src, dest)
        assert dest.read_bytes() == b'{"existing": 1}\n{"new": 2}\n'

    def test_adds_newline_when_existing_lacks_it(self, tmp_path):
        src = tmp_path / "src.jsonl"
        dest = tmp_path / "dest.jsonl"
        dest.write_bytes(b'{"existing": 1}')
        src.write_bytes(b'{"new": 2}\n')
        _merge_jsonl(src, dest)
        assert dest.read_bytes() == b'{"existing": 1}\n{"new": 2}\n'


class TestUpdateDb:
    def _make_db(self, db_path: Path, camera: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE detections (
                id TEXT PRIMARY KEY,
                camera TEXT,
                clip_path TEXT,
                image_path TEXT,
                composite_original_path TEXT,
                alternate_clip_paths TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE jsonl_sync_state (
                camera TEXT PRIMARY KEY,
                last_synced_at TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?)",
            (
                "det_001",
                camera,
                f"{camera}/meteor.mp4",
                f"{camera}/meteor.jpg",
                f"{camera}/meteor_orig.jpg",
                f"{camera}/alt.mp4",
            ),
        )
        conn.execute(
            "INSERT INTO jsonl_sync_state VALUES (?, ?)",
            (camera, "2026-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

    def test_updates_camera_name(self, tmp_path):
        db_path = tmp_path / "detections.db"
        self._make_db(db_path, "camera1_10_0_1_15")
        _update_db(db_path, "camera1_10_0_1_15", "camera1")
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT camera FROM detections WHERE id = 'det_001'").fetchone()
        conn.close()
        assert row[0] == "camera1"

    def test_updates_clip_path(self, tmp_path):
        db_path = tmp_path / "detections.db"
        self._make_db(db_path, "camera1_10_0_1_15")
        _update_db(db_path, "camera1_10_0_1_15", "camera1")
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT clip_path FROM detections WHERE id = 'det_001'").fetchone()
        conn.close()
        assert row[0] == "camera1/meteor.mp4"

    def test_updates_alternate_clip_paths(self, tmp_path):
        db_path = tmp_path / "detections.db"
        self._make_db(db_path, "camera1_10_0_1_15")
        _update_db(db_path, "camera1_10_0_1_15", "camera1")
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT alternate_clip_paths FROM detections WHERE id = 'det_001'"
        ).fetchone()
        conn.close()
        assert row[0] == "camera1/alt.mp4"

    def test_deletes_jsonl_sync_state(self, tmp_path):
        db_path = tmp_path / "detections.db"
        self._make_db(db_path, "camera1_10_0_1_15")
        _update_db(db_path, "camera1_10_0_1_15", "camera1")
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM jsonl_sync_state WHERE camera = 'camera1_10_0_1_15'"
        ).fetchone()
        conn.close()
        assert row is None


class TestMoveMediaFiles:
    def test_moves_mp4(self, tmp_path):
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        src.mkdir()
        (src / "meteor.mp4").write_bytes(b"video")
        _move_media_files(src, dest)
        assert (dest / "meteor.mp4").exists()
        assert not (src / "meteor.mp4").exists()

    def test_moves_jpg(self, tmp_path):
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        src.mkdir()
        (src / "meteor.jpg").write_bytes(b"image")
        _move_media_files(src, dest)
        assert (dest / "meteor.jpg").exists()

    def test_moves_png(self, tmp_path):
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        src.mkdir()
        (src / "mask.png").write_bytes(b"mask")
        _move_media_files(src, dest)
        assert (dest / "mask.png").exists()

    def test_creates_dest_dir(self, tmp_path):
        src = tmp_path / "src"
        dest = tmp_path / "dest" / "subdir"
        src.mkdir()
        (src / "meteor.mp4").write_bytes(b"video")
        _move_media_files(src, dest)
        assert dest.is_dir()

    def test_returns_moved_list(self, tmp_path):
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        src.mkdir()
        (src / "meteor.mp4").write_bytes(b"video")
        (src / "meteor.jpg").write_bytes(b"image")
        moved = _move_media_files(src, dest)
        assert len(moved) == 2

    def test_does_not_move_jsonl(self, tmp_path):
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        src.mkdir()
        (src / "detections.jsonl").write_bytes(b"{}\n")
        moved = _move_media_files(src, dest)
        assert moved == []
        assert not (dest / "detections.jsonl").exists()


class TestBackupDb:
    def test_creates_backup_file(self, tmp_path):
        db_path = tmp_path / "detections.db"
        db_path.write_bytes(b"SQLITE")
        bak = _backup_db(db_path, "20260101_000000")
        assert bak.exists()
        assert bak.name == "detections.db.bak_20260101_000000"

    def test_backup_content_matches_original(self, tmp_path):
        db_path = tmp_path / "detections.db"
        db_path.write_bytes(b"SQLITE_DATA")
        bak = _backup_db(db_path, "20260101_000000")
        assert bak.read_bytes() == b"SQLITE_DATA"

    def test_original_not_removed(self, tmp_path):
        db_path = tmp_path / "detections.db"
        db_path.write_bytes(b"SQLITE")
        _backup_db(db_path, "20260101_000000")
        assert db_path.exists()


class TestMigrate:
    def _make_detection_dir(self, base: Path, camera_old: str) -> Path:
        """移行前のカメラディレクトリを作成する"""
        src = base / camera_old
        src.mkdir()
        (src / "meteor.mp4").write_bytes(b"video")
        (src / "meteor.jpg").write_bytes(b"image")
        (src / "detections.jsonl").write_bytes(b'{"id": "1"}\n')
        return src

    def _make_db(self, db_path: Path, camera: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE detections (
                id TEXT PRIMARY KEY,
                camera TEXT,
                clip_path TEXT,
                image_path TEXT,
                composite_original_path TEXT,
                alternate_clip_paths TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE jsonl_sync_state (
                camera TEXT PRIMARY KEY,
                last_synced_at TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?)",
            ("det_001", camera, f"{camera}/meteor.mp4", f"{camera}/meteor.jpg", "", ""),
        )
        conn.execute(
            "INSERT INTO jsonl_sync_state VALUES (?, ?)",
            (camera, "2026-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

    def test_migrate_no_targets_prints_message(self, tmp_path, capsys):
        """移行対象がない場合はメッセージを出力して終了すること"""
        (tmp_path / "camera1").mkdir()  # index-based なので対象外
        migrate(tmp_path, dry_run=False, yes=True)
        captured = capsys.readouterr()
        assert "移行対象のディレクトリが見つかりません" in captured.out

    def test_migrate_dry_run_does_not_move_files(self, tmp_path, capsys):
        """dry_run=True の場合はファイルを実際に移動しないこと"""
        self._make_detection_dir(tmp_path, "camera1_10_0_1_15")
        migrate(tmp_path, dry_run=True, yes=False)
        # ファイルが移動していないこと
        assert (tmp_path / "camera1_10_0_1_15" / "meteor.mp4").exists()
        captured = capsys.readouterr()
        assert "--dry-run" in captured.out

    def test_migrate_yes_moves_files(self, tmp_path, capsys):
        """yes=True で実際にファイルが移動されること"""
        self._make_detection_dir(tmp_path, "camera1_10_0_1_15")
        migrate(tmp_path, dry_run=False, yes=True)
        assert (tmp_path / "camera1" / "meteor.mp4").exists()
        assert (tmp_path / "camera1" / "meteor.jpg").exists()

    def test_migrate_yes_merges_jsonl(self, tmp_path, capsys):
        """yes=True でJSONLが移行先にマージされること"""
        self._make_detection_dir(tmp_path, "camera1_10_0_1_15")
        migrate(tmp_path, dry_run=False, yes=True)
        dest_jsonl = tmp_path / "camera1" / "detections.jsonl"
        assert dest_jsonl.exists()
        assert b'{"id": "1"}' in dest_jsonl.read_bytes()

    def test_migrate_yes_renames_source_dir(self, tmp_path, capsys):
        """yes=True で元ディレクトリが .migrated_ サフィックス付きにリネームされること"""
        self._make_detection_dir(tmp_path, "camera1_10_0_1_15")
        migrate(tmp_path, dry_run=False, yes=True)
        renamed_dirs = [d for d in tmp_path.iterdir() if "camera1_10_0_1_15.migrated_" in d.name]
        assert len(renamed_dirs) == 1

    def test_migrate_with_db_updates_records(self, tmp_path, capsys):
        """DBが存在する場合にカメラ名が更新されること"""
        self._make_detection_dir(tmp_path, "camera1_10_0_1_15")
        db_path = tmp_path / "detections.db"
        self._make_db(db_path, "camera1_10_0_1_15")
        migrate(tmp_path, dry_run=False, yes=True)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT camera FROM detections WHERE id = 'det_001'").fetchone()
        conn.close()
        assert row[0] == "camera1"

    def test_migrate_with_db_creates_backup(self, tmp_path, capsys):
        """DBが存在する場合にバックアップが作成されること"""
        self._make_detection_dir(tmp_path, "camera1_10_0_1_15")
        db_path = tmp_path / "detections.db"
        self._make_db(db_path, "camera1_10_0_1_15")
        migrate(tmp_path, dry_run=False, yes=True)
        bak_files = [f for f in tmp_path.iterdir() if f.name.startswith("detections.db.bak_")]
        assert len(bak_files) == 1

    def test_migrate_dry_run_with_jsonl_prints_info(self, tmp_path, capsys):
        """dry_run=True でJSONLが存在する場合にその旨が出力されること"""
        self._make_detection_dir(tmp_path, "camera1_10_0_1_15")
        migrate(tmp_path, dry_run=True, yes=False)
        captured = capsys.readouterr()
        assert "detections.jsonl" in captured.out

    def test_migrate_dry_run_with_db_prints_db_info(self, tmp_path, capsys):
        """dry_run=True でDBが存在する場合にその旨が出力されること"""
        self._make_detection_dir(tmp_path, "camera1_10_0_1_15")
        db_path = tmp_path / "detections.db"
        self._make_db(db_path, "camera1_10_0_1_15")
        migrate(tmp_path, dry_run=True, yes=False)
        captured = capsys.readouterr()
        assert "detections.db" in captured.out
