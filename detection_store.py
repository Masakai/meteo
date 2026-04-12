"""SQLite-backed detection store.

Provides thread-safe CRUD operations and incremental JSONL→SQLite sync.
The detection engine continues writing to JSONL files; this module reads
new lines and inserts them into SQLite, making the DB the authoritative
read store for the dashboard.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_local = threading.local()

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS detections (
    id                      TEXT PRIMARY KEY,
    camera                  TEXT NOT NULL,
    timestamp               TEXT NOT NULL,
    confidence              REAL,
    base_name               TEXT,
    clip_path               TEXT DEFAULT '',
    image_path              TEXT DEFAULT '',
    composite_original_path TEXT DEFAULT '',
    alternate_clip_paths    TEXT DEFAULT '',
    label                   TEXT DEFAULT '',
    deleted                 INTEGER DEFAULT 0,
    raw_json                TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_camera    ON detections(camera);
CREATE INDEX IF NOT EXISTS idx_timestamp ON detections(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_active    ON detections(deleted) WHERE deleted = 0;
CREATE TABLE IF NOT EXISTS jsonl_sync_state (
    camera  TEXT PRIMARY KEY,
    offset  INTEGER NOT NULL DEFAULT 0,
    mtime   REAL    NOT NULL DEFAULT 0.0
);
"""


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Return a thread-local SQLite connection for db_path."""
    conn = getattr(_local, "conn", None)
    stored_path = getattr(_local, "db_path", None)
    if conn is None or stored_path != db_path:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
        _local.db_path = db_path
    return conn


def init_db(db_path: str) -> None:
    """Create tables and indexes if they do not exist."""
    conn = _get_conn(db_path)
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def _insert_detection(conn: sqlite3.Connection, camera: str, normalized: dict, raw_json: str) -> None:
    alternate = normalized.get("alternate_clip_paths", [])
    alternate_str = json.dumps(alternate, ensure_ascii=False) if isinstance(alternate, list) else str(alternate)
    conn.execute(
        """
        INSERT OR IGNORE INTO detections
            (id, camera, timestamp, confidence, base_name,
             clip_path, image_path, composite_original_path,
             alternate_clip_paths, label, deleted, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,0,?)
        """,
        (
            normalized["id"],
            camera,
            normalized.get("timestamp", ""),
            normalized.get("confidence"),
            normalized.get("base_name", ""),
            normalized.get("clip_path", ""),
            normalized.get("image_path", ""),
            normalized.get("composite_original_path", ""),
            alternate_str,
            normalized.get("label", ""),
            raw_json,
        ),
    )


def sync_camera_from_jsonl(
    camera_name: str,
    cam_dir: Path,
    db_path: str,
    normalize_fn,
) -> int:
    """Read new lines from camera's detections.jsonl and insert into SQLite.

    Uses jsonl_sync_state to track the byte offset of the last processed
    position, so only newly appended lines are processed each call.

    Returns the number of new rows inserted.
    """
    jsonl_file = cam_dir / "detections.jsonl"
    if not jsonl_file.exists():
        return 0

    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT offset, mtime FROM jsonl_sync_state WHERE camera = ?", (camera_name,)
    ).fetchone()
    prev_offset = row["offset"] if row else 0
    prev_mtime = row["mtime"] if row else 0.0

    try:
        stat = jsonl_file.stat()
        current_mtime = stat.st_mtime
        current_size = stat.st_size
    except OSError:
        return 0

    if current_mtime == prev_mtime and current_size <= prev_offset:
        return 0

    # File was truncated/rewritten; restart from the beginning
    if current_size < prev_offset:
        prev_offset = 0

    inserted = 0
    new_offset = prev_offset

    try:
        with open(jsonl_file, "r", encoding="utf-8") as f:
            f.seek(prev_offset)
            while True:
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    new_offset = f.tell()
                    continue
                try:
                    raw = json.loads(stripped)
                    normalized = normalize_fn(camera_name, cam_dir, raw)
                    _insert_detection(conn, camera_name, normalized, stripped)
                    inserted += 1
                except Exception:
                    logger.exception(
                        "sync_camera_from_jsonl: parse error camera=%s line=%r",
                        camera_name,
                        stripped[:200],
                    )
                new_offset = f.tell()
    except OSError:
        logger.exception("sync_camera_from_jsonl: read error camera=%s", camera_name)
        return 0

    conn.execute(
        """
        INSERT INTO jsonl_sync_state (camera, offset, mtime)
        VALUES (?, ?, ?)
        ON CONFLICT(camera) DO UPDATE SET offset=excluded.offset, mtime=excluded.mtime
        """,
        (camera_name, new_offset, current_mtime),
    )
    conn.commit()
    return inserted


def query_detections(
    db_path: str,
    *,
    camera: str = None,
    deleted: bool = False,
    limit: int = None,
) -> list:
    """Return detections as a list of dicts.

    By default returns only non-deleted records.
    """
    conn = _get_conn(db_path)
    conditions = ["deleted = ?"]
    params: list = [1 if deleted else 0]
    if camera is not None:
        conditions.append("camera = ?")
        params.append(camera)
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM detections WHERE {where} ORDER BY timestamp DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["alternate_clip_paths"] = json.loads(d.get("alternate_clip_paths") or "[]")
        except Exception:
            d["alternate_clip_paths"] = []
        result.append(d)
    return result


def soft_delete(db_path: str, detection_id: str) -> None:
    """Mark a detection as deleted (does not modify JSONL)."""
    conn = _get_conn(db_path)
    conn.execute("UPDATE detections SET deleted = 1 WHERE id = ?", (detection_id,))
    conn.commit()


def set_label(db_path: str, detection_id: str, label: str) -> None:
    """Update the label column for a detection."""
    conn = _get_conn(db_path)
    conn.execute("UPDATE detections SET label = ? WHERE id = ?", (label, detection_id))
    conn.commit()


def count_asset_references(
    db_path: str,
    asset_path: str,
    *,
    exclude_id: str = "",
) -> int:
    """Count non-deleted detections that reference asset_path.

    Checks clip_path, image_path, composite_original_path, and alternate_clip_paths.
    Used to decide whether it is safe to delete a file on disk.
    """
    if not asset_path:
        return 0
    conn = _get_conn(db_path)
    params: list = [asset_path, asset_path, asset_path]
    exclude_clause = ""
    if exclude_id:
        exclude_clause = "AND id != ?"
        params.append(exclude_id)

    # Check the three scalar path columns
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM detections
        WHERE deleted = 0
          AND (clip_path = ? OR image_path = ? OR composite_original_path = ?)
          {exclude_clause}
        """,
        params,
    ).fetchone()
    count = row[0]

    # Check alternate_clip_paths (stored as JSON text)
    escaped = asset_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like_pattern = f'%"{escaped}"%'
    alt_params: list = [like_pattern]
    if exclude_id:
        alt_params.append(exclude_id)
    alt_row = conn.execute(
        f"""
        SELECT COUNT(*) FROM detections
        WHERE deleted = 0
          AND alternate_clip_paths LIKE ? ESCAPE '\\'
          {exclude_clause}
        """,
        alt_params,
    ).fetchone()
    count += alt_row[0]
    return count


def reset_sync_state(db_path: str, camera_name: str) -> None:
    """Reset the jsonl_sync_state offset and mtime for camera_name to zero.

    Call this after rewriting (truncating) a camera's detections.jsonl so the
    next sync_camera_from_jsonl call re-reads the file from the beginning.
    """
    conn = _get_conn(db_path)
    conn.execute(
        """
        INSERT INTO jsonl_sync_state (camera, offset, mtime)
        VALUES (?, 0, 0.0)
        ON CONFLICT(camera) DO UPDATE SET offset=0, mtime=0.0
        """,
        (camera_name,),
    )
    conn.commit()


def get_detection_by_id(db_path: str, detection_id: str) -> dict | None:
    """Return a single detection dict by id, or None if not found."""
    conn = _get_conn(db_path)
    row = conn.execute("SELECT * FROM detections WHERE id = ?", (detection_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["alternate_clip_paths"] = json.loads(d.get("alternate_clip_paths") or "[]")
    except Exception:
        d["alternate_clip_paths"] = []
    return d
