#!/usr/bin/env python3
"""再同期で失われた削除フラグを復旧する。

## 背景

v3.14.0 以前の `detection_store._insert_detection` は JSONL 同期時に
`deleted` を 0 固定で INSERT していた。検出コアが追記する `detections.jsonl`
は削除時に行を消さないため、カメラ名変更などで全行再同期が走ると
UI で削除したはずのレコードが `deleted=0` で復活していた。

復活したレコードは実ファイルが既に削除済みなので、`_resolve_asset_path`
のファイル存在チェックにより `image_path` が空になる。結果として
ダッシュボードに「サムネイルが付かない記録」として並ぶ。

## 判定条件

JSONL（検出時の一次記録）に画像パスが記録されているのに実ファイルが
存在しないレコードを、削除済みとみなして `deleted=1` に戻し、
`deleted_detections` に履歴を登録する。

検出時に画像生成へ失敗した場合は JSONL 側にもパスが入らないため、
この条件で「削除された」ものだけを選別できる。

## 使い方

    python3 scripts/repair_lost_deletions.py --detections-dir ~/meteo/detections
    python3 scripts/repair_lost_deletions.py --detections-dir ~/meteo/detections --apply

`--apply` を付けるまでは変更しない（ドライラン）。
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ASSET_KEYS = ("image_path", "composite_original_path", "clip_path")


def iter_jsonl_records(cam_dir):
    """カメラディレクトリの detections.jsonl を1行ずつ読む。"""
    jsonl = cam_dir / "detections.jsonl"
    if not jsonl.exists():
        return
    with open(jsonl, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def asset_missing_on_disk(cam_dir, record):
    """JSONL にパスがあるのに実ファイルが無いなら True。

    パスは移行の経緯によりファイル名のみ・カメラ名付きの両形式がある。
    どちらの解釈でも見つからない場合に「無い」と判定する。
    """
    recorded_any = False
    for key in ASSET_KEYS:
        rel = str(record.get(key, "")).strip()
        if not rel:
            continue
        recorded_any = True
        name = Path(rel).name
        if (cam_dir / name).exists():
            return False
    return recorded_any


def collect_candidates(detections_dir, cameras):
    """削除済みとみなすべきレコードを集める。"""
    candidates = []
    for camera in cameras:
        cam_dir = detections_dir / camera
        if not cam_dir.is_dir():
            continue
        for record in iter_jsonl_records(cam_dir):
            detection_id = str(record.get("id", "")).strip()
            if not detection_id:
                continue
            if asset_missing_on_disk(cam_dir, record):
                candidates.append({
                    "id": detection_id,
                    "camera": camera,
                    "timestamp": record.get("timestamp", ""),
                })
    return candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--detections-dir", required=True,
                        help="detections ディレクトリ（detections.db を含む）")
    parser.add_argument("--apply", action="store_true",
                        help="実際に DB を更新する（既定はドライラン）")
    parser.add_argument("--include-migrated", action="store_true",
                        help="移行前の旧カメラディレクトリ（*.migrated_*）も対象にする")
    args = parser.parse_args()

    detections_dir = Path(args.detections_dir).expanduser().resolve()
    db_path = detections_dir / "detections.db"
    if not db_path.exists():
        print(f"エラー: DB が見つかりません: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    cameras = sorted(
        p.name for p in detections_dir.iterdir()
        if p.is_dir() and (p / "detections.jsonl").exists()
        and (args.include_migrated or ".migrated_" not in p.name)
    )
    print(f"対象カメラ: {', '.join(cameras) or '(なし)'}")

    candidates = collect_candidates(detections_dir, cameras)
    if not candidates:
        print("復旧対象はありません。")
        return 0

    ids = [c["id"] for c in candidates]
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, deleted FROM detections WHERE id IN ({placeholders})", ids
    ).fetchall()
    current = {r["id"]: r["deleted"] for r in rows}

    to_fix = [c for c in candidates if current.get(c["id"]) == 0]
    already = len(candidates) - len(to_fix)

    print(f"JSONL に記録があり実ファイルが無い: {len(candidates)}件")
    print(f"  うち既に deleted=1: {already}件")
    print(f"  復旧対象 (deleted=0 → 1): {len(to_fix)}件")

    if to_fix:
        by_month = {}
        for c in to_fix:
            key = str(c["timestamp"])[:7]
            by_month[key] = by_month.get(key, 0) + 1
        print("  月別内訳:")
        for month in sorted(by_month):
            print(f"    {month}: {by_month[month]}件")

    if not args.apply:
        print("\nドライランです。実行するには --apply を付けてください。")
        return 0

    if not to_fix:
        print("更新対象がないため終了します。")
        return 0

    now = datetime.now().isoformat(timespec="seconds")
    with conn:
        conn.executemany(
            "UPDATE detections SET deleted = 1 WHERE id = ?",
            [(c["id"],) for c in to_fix],
        )
        conn.executemany(
            """
            INSERT INTO deleted_detections (id, camera, deleted_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            [(c["id"], c["camera"], now) for c in to_fix],
        )
    print(f"\n{len(to_fix)}件を deleted=1 に更新し、削除履歴に登録しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
