"""detections.db の内容をダンプするツール。

Usage:
    python scripts/dump_detections_db.py [--db PATH] [--camera CAMERA]
                                         [--deleted] [--limit N]
                                         [--table {detections,sync,all}]
                                         [--format {table,json,csv}]

Examples:
    # デフォルト (detections/ 以下の DB を table 形式でダンプ)
    python scripts/dump_detections_db.py

    # JSON 形式で出力
    python scripts/dump_detections_db.py --format json

    # 特定カメラのみ・最新 20 件
    python scripts/dump_detections_db.py --camera cam1 --limit 20

    # 削除済みレコードも含める
    python scripts/dump_detections_db.py --deleted

    # jsonl_sync_state テーブルも表示
    python scripts/dump_detections_db.py --table sync
"""

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

DEFAULT_DB = _PROJECT_ROOT / "detections" / "detections.db"

# raw_json は長いので table 形式では省略するカラム
_SKIP_COLS_TABLE = {"raw_json"}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _dump_detections(conn, *, camera=None, include_deleted=False, limit=None, fmt="table"):
    conditions = []
    params: list = []

    if not include_deleted:
        conditions.append("deleted = 0")

    if camera:
        conditions.append("camera = ?")
        params.append(camera)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM detections {where} ORDER BY timestamp DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = conn.execute(sql, params).fetchall()

    if not rows:
        print("(レコードなし)")
        return

    if fmt == "json":
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["alternate_clip_paths"] = json.loads(d.get("alternate_clip_paths") or "[]")
            except Exception:
                pass
            result.append(d)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    cols = list(rows[0].keys())

    if fmt == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
        return

    # table 形式
    display_cols = [c for c in cols if c not in _SKIP_COLS_TABLE]
    col_widths = {c: max(len(c), max(len(str(row[c] or "")) for row in rows)) for c in display_cols}
    # 幅の上限を設ける
    MAX_W = 40
    col_widths = {c: min(w, MAX_W) for c, w in col_widths.items()}

    def _fmt(val, width):
        s = str(val) if val is not None else ""
        if len(s) > width:
            s = s[:width - 1] + "…"
        return s.ljust(width)

    header = "  ".join(_fmt(c, col_widths[c]) for c in display_cols)
    sep = "  ".join("-" * col_widths[c] for c in display_cols)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(_fmt(row[c], col_widths[c]) for c in display_cols))

    print(f"\n合計: {len(rows)} 件")


def _dump_sync(conn, *, fmt="table"):
    rows = conn.execute("SELECT * FROM jsonl_sync_state ORDER BY camera").fetchall()
    if not rows:
        print("(レコードなし)")
        return

    if fmt == "json":
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return

    cols = list(rows[0].keys())
    col_widths = {c: max(len(c), max(len(str(row[c] or "")) for row in rows)) for c in cols}

    def _fmt(val, width):
        return str(val if val is not None else "").ljust(width)

    header = "  ".join(_fmt(c, col_widths[c]) for c in cols)
    sep = "  ".join("-" * col_widths[c] for c in cols)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(_fmt(row[c], col_widths[c]) for c in cols))

    print(f"\n合計: {len(rows)} カメラ")


def main():
    parser = argparse.ArgumentParser(description="detections.db ダンプツール")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DB ファイルパス")
    parser.add_argument("--camera", help="カメラ名でフィルタ")
    parser.add_argument("--deleted", action="store_true", help="削除済みレコードも含める")
    parser.add_argument("--limit", type=int, help="最大取得件数")
    parser.add_argument(
        "--table",
        choices=["detections", "sync", "all"],
        default="detections",
        help="ダンプ対象テーブル (default: detections)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="出力形式 (default: table)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"エラー: DB が見つかりません: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = _connect(db_path)

    if args.table in ("detections", "all"):
        if args.table == "all":
            print("=== detections ===")
        _dump_detections(
            conn,
            camera=args.camera,
            include_deleted=args.deleted,
            limit=args.limit,
            fmt=args.format,
        )

    if args.table in ("sync", "all"):
        if args.table == "all":
            print("\n=== jsonl_sync_state ===")
        _dump_sync(conn, fmt=args.format)

    conn.close()


if __name__ == "__main__":
    main()
