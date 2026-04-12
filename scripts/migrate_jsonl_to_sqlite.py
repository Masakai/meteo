"""Migrate existing JSONL detection files and detection_labels.json to SQLite.

Usage:
    source .venv/bin/activate
    python scripts/migrate_jsonl_to_sqlite.py

The script is idempotent: it uses INSERT OR IGNORE so running it multiple
times is safe. Existing JSONL files are NOT deleted (kept as rollback source).
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

# Ensure the project root is on sys.path when run from any working directory
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import detection_store  # noqa: E402  (after sys.path modification)
from dashboard_routes import _normalize_detection_label  # noqa: E402


def _load_labels(detections_dir: Path) -> dict:
    labels_path = detections_dir / "detection_labels.json"
    if not labels_path.exists():
        return {}
    try:
        with open(labels_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"  WARNING: could not read detection_labels.json: {exc}", file=sys.stderr)
        return {}


def _normalize_fn(camera_name, cam_dir, record):
    """Minimal normalization for migration: reuse dashboard_routes helpers."""
    # Import lazily to avoid circular dependency issues
    from dashboard_routes import _normalize_detection_record
    return _normalize_detection_record(camera_name, cam_dir, record)


def migrate(detections_dir: Path) -> None:
    db_path = str(detections_dir / "detections.db")
    print(f"Initialising DB: {db_path}")
    detection_store.init_db(db_path)

    labels = _load_labels(detections_dir)
    print(f"Loaded {len(labels)} labels from detection_labels.json")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    total_inserted = 0
    total_cameras = 0

    try:
        for cam_dir in sorted(detections_dir.iterdir()):
            if not cam_dir.is_dir():
                continue
            jsonl_file = cam_dir / "detections.jsonl"
            if not jsonl_file.exists():
                continue

            camera_name = cam_dir.name
            total_cameras += 1
            inserted = 0
            skipped = 0

            print(f"  Migrating camera: {camera_name} ...", end="", flush=True)
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        raw = json.loads(stripped)
                        normalized = _normalize_fn(camera_name, cam_dir, raw)
                        detection_id = normalized["id"]

                        # Resolve label: prefer id-keyed, fall back to legacy key
                        legacy_key = normalized.get("legacy_label_key", "")
                        label_value = labels.get(detection_id, labels.get(legacy_key, ""))

                        normalized["label"] = _normalize_detection_label(label_value)

                        alternate = normalized.get("alternate_clip_paths", [])
                        alternate_str = (
                            json.dumps(alternate, ensure_ascii=False)
                            if isinstance(alternate, list)
                            else str(alternate)
                        )

                        cur = conn.execute(
                            """
                            INSERT OR IGNORE INTO detections
                                (id, camera, timestamp, confidence, base_name,
                                 clip_path, image_path, composite_original_path,
                                 alternate_clip_paths, label, deleted, raw_json)
                            VALUES (?,?,?,?,?,?,?,?,?,?,0,?)
                            """,
                            (
                                normalized["id"],
                                camera_name,
                                normalized.get("timestamp", ""),
                                normalized.get("confidence"),
                                normalized.get("base_name", ""),
                                normalized.get("clip_path", ""),
                                normalized.get("image_path", ""),
                                normalized.get("composite_original_path", ""),
                                alternate_str,
                                normalized.get("label", ""),
                                stripped,
                            ),
                        )
                        if cur.rowcount:
                            inserted += 1
                        else:
                            skipped += 1
                    except Exception as exc:
                        print(f"\n  WARNING: skipped line in {camera_name}: {exc}", file=sys.stderr)

            conn.commit()

            # Record the current file size as the sync offset so the normal
            # incremental sync loop won't re-process lines we just imported.
            try:
                file_size = jsonl_file.stat().st_size
                file_mtime = jsonl_file.stat().st_mtime
                conn.execute(
                    """
                    INSERT INTO jsonl_sync_state (camera, offset, mtime)
                    VALUES (?, ?, ?)
                    ON CONFLICT(camera) DO UPDATE SET offset=excluded.offset, mtime=excluded.mtime
                    """,
                    (camera_name, file_size, file_mtime),
                )
                conn.commit()
            except Exception as exc:
                print(f"\n  WARNING: could not update sync state for {camera_name}: {exc}", file=sys.stderr)

            total_inserted += inserted
            print(f" inserted={inserted} skipped(already exists)={skipped}")
    finally:
        conn.close()

    print(f"\nDone. cameras={total_cameras} total_inserted={total_inserted}")
    print("Existing JSONL files have NOT been deleted.")


def main():
    detections_dir_env = os.environ.get("DETECTIONS_DIR", "detections")
    detections_dir = Path(detections_dir_env).resolve()

    if not detections_dir.exists():
        print(f"ERROR: DETECTIONS_DIR does not exist: {detections_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"DETECTIONS_DIR: {detections_dir}")
    migrate(detections_dir)


if __name__ == "__main__":
    main()
