#!/usr/bin/env python3
# Usage: python migrate_camera_dirs.py [--detections-dir DIR] [--dry-run] [--yes]
"""
IPアドレスベースのカメラディレクトリをインデックスベースに移行するスクリプト

使い方:
    python migrate_camera_dirs.py --dry-run
    python migrate_camera_dirs.py
    python migrate_camera_dirs.py --yes
    python migrate_camera_dirs.py --detections-dir /path/to/detections

Copyright (c) 2026 Masanori Sakai
Licensed under the MIT License
"""

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def find_migration_targets(detections_dir: Path) -> list[tuple[str, str]]:
    """camera{i}_ で始まるディレクトリを検索し、(src_name, target_name) のリストを返す。

    複数の古いディレクトリが同じインデックスに対応する場合はすべて含める。
    戻り値はディレクトリ名の昇順でソートされる。
    """
    pattern = re.compile(r"^camera(\d+)_")
    targets = []
    for d in sorted(detections_dir.iterdir()):
        if not d.is_dir():
            continue
        m = pattern.match(d.name)
        if m:
            index = m.group(1)
            targets.append((d.name, f"camera{index}"))
    return targets


def _unique_path(dest: Path) -> Path:
    """destが既に存在する場合、_1, _2 ... のサフィックスを付けた未使用パスを返す。"""
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _backup_db(db_path: Path, timestamp: str) -> Path:
    """DBのバックアップを作成し、バックアップパスを返す。"""
    bak_path = db_path.with_name(f"{db_path.name}.bak_{timestamp}")
    shutil.copy2(db_path, bak_path)
    return bak_path


def _move_media_files(src_dir: Path, dest_dir: Path) -> list[str]:
    """メディアファイル(.mp4, .jpg, .png)をsrc_dirからdest_dirに移動する。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for ext in ("*.mp4", "*.jpg", "*.png"):
        for f in src_dir.glob(ext):
            dest = _unique_path(dest_dir / f.name)
            f.rename(dest)
            moved.append(str(dest))
    return moved


def _merge_jsonl(src_jsonl: Path, dest_jsonl: Path):
    """src_jsonlの内容をdest_jsonlに追記する。"""
    content = src_jsonl.read_bytes()
    if dest_jsonl.exists():
        existing = dest_jsonl.read_bytes()
        with dest_jsonl.open("ab") as f:
            if existing and not existing.endswith(b"\n"):
                f.write(b"\n")
            f.write(content)
    else:
        dest_jsonl.write_bytes(content)


def _update_db(db_path: Path, old_name: str, new_name: str):
    """SQLiteのdetectionsテーブルとjsonl_sync_stateテーブルを更新する。"""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE detections
               SET camera = ?,
                   clip_path = replace(clip_path, ?, ?),
                   image_path = replace(image_path, ?, ?),
                   composite_original_path = replace(composite_original_path, ?, ?)
               WHERE camera = ?""",
            (
                new_name,
                f"{old_name}/", f"{new_name}/",
                f"{old_name}/", f"{new_name}/",
                f"{old_name}/", f"{new_name}/",
                old_name,
            ),
        )
        # この時点で camera カラムはすでに new_name に書き換え済み
        cur.execute(
            """UPDATE detections
               SET alternate_clip_paths = replace(alternate_clip_paths, ?, ?)
               WHERE camera = ? AND alternate_clip_paths != ''""",
            (f"{old_name}/", f"{new_name}/", new_name),
        )
        cur.execute(
            "DELETE FROM jsonl_sync_state WHERE camera = ?",
            (old_name,),
        )
        conn.commit()
    finally:
        conn.close()


def migrate(detections_dir: Path, dry_run: bool, yes: bool):
    targets = find_migration_targets(detections_dir)
    if not targets:
        print("移行対象のディレクトリが見つかりません。")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_path = detections_dir / "detections.db"

    print("以下の操作を実行します:")
    print()
    for old_name, new_name in targets:
        src_dir = detections_dir / old_name
        dest_dir = detections_dir / new_name
        print(f"  [{old_name}] -> [{new_name}]")
        print(f"    メディアファイルを {src_dir}/ から {dest_dir}/ に移動")
        if (src_dir / "detections.jsonl").exists():
            print(f"    detections.jsonl を {dest_dir}/detections.jsonl に追記")
        if db_path.exists():
            print(f"    detections.db の camera='{old_name}' を '{new_name}' に更新")
        print(f"    {old_name}/ を {old_name}.migrated_{timestamp}/ にリネーム")
        print()

    if db_path.exists():
        print(f"  detections.db バックアップ: detections.db.bak_{timestamp}")
        print()

    if dry_run:
        print("--dry-run モードのため、実際の操作は行いません。")
        return

    if not yes:
        answer = input("実行しますか? [y/N]: ").strip().lower()
        if answer != "y":
            print("中止しました。")
            return

    bak_path = None
    if db_path.exists():
        bak_path = _backup_db(db_path, timestamp)
        print(f"DBバックアップ: {bak_path}")

        for old_name, new_name in targets:
            try:
                _update_db(db_path, old_name, new_name)
            except Exception as e:
                print(f"エラー: DB更新失敗 ({old_name} -> {new_name}): {e}", file=sys.stderr)
                sys.exit(1)
            print(f"DB更新完了: {old_name} -> {new_name}")

    for old_name, new_name in targets:
        src_dir = detections_dir / old_name
        dest_dir = detections_dir / new_name

        try:
            moved = _move_media_files(src_dir, dest_dir)
        except Exception as e:
            print(f"エラー: メディアファイル移動失敗 ({old_name} -> {new_name}): {e}", file=sys.stderr)
            if bak_path:
                print(f"DBは更新済み。バックアップから復元するには: cp {bak_path} {db_path}", file=sys.stderr)
            sys.exit(1)
        print(f"メディアファイル移動: {len(moved)} 件 ({old_name} -> {new_name})")

        src_jsonl = src_dir / "detections.jsonl"
        dest_jsonl = dest_dir / "detections.jsonl"
        if src_jsonl.exists():
            try:
                _merge_jsonl(src_jsonl, dest_jsonl)
            except Exception as e:
                print(f"エラー: JSONL追記失敗 ({old_name}): {e}", file=sys.stderr)
                if bak_path:
                    print(f"DBは更新済み。バックアップから復元するには: cp {bak_path} {db_path}", file=sys.stderr)
                sys.exit(1)
            print(f"JSONL追記完了: {dest_jsonl}")

        try:
            migrated_dir = detections_dir / f"{old_name}.migrated_{timestamp}"
            src_dir.rename(migrated_dir)
        except Exception as e:
            print(f"エラー: ディレクトリリネーム失敗 ({old_name}): {e}", file=sys.stderr)
            if bak_path:
                print(f"DBは更新済み。バックアップから復元するには: cp {bak_path} {db_path}", file=sys.stderr)
            sys.exit(1)
        print(f"リネーム完了: {old_name}/ -> {migrated_dir.name}/")
        print()

    print("移行完了。")


def main():
    parser = argparse.ArgumentParser(
        description="IPアドレスベースのカメラディレクトリをインデックスベースに移行する"
    )
    parser.add_argument(
        "--detections-dir",
        default="detections",
        help="対象ディレクトリ (デフォルト: detections)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="操作内容を表示するだけで実行しない",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="確認プロンプトをスキップして実行",
    )
    args = parser.parse_args()

    detections_dir = Path(args.detections_dir)
    if not detections_dir.is_dir():
        print(f"エラー: ディレクトリが存在しません: {detections_dir}", file=sys.stderr)
        sys.exit(1)

    migrate(detections_dir, dry_run=args.dry_run, yes=args.yes)


if __name__ == "__main__":
    main()
