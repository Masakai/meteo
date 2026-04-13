#!/usr/bin/env python3
"""別システムの detections/ ディレクトリから検出データを取り込む。

別のサーバーやマシンで動作していた meteo システムの検出結果（JSONL・動画・画像）を
本システムの detections/ ディレクトリへ移行する。

使い方:
    # ドライラン（デフォルト）：何が起こるかを確認
    python scripts/import_from_other_system.py --source /mnt/other_system/detections

    # カメラ名マッピングあり（別名で運用していた場合）
    python scripts/import_from_other_system.py \\
        --source /mnt/other_system/detections \\
        --camera-map old_camera_name:new_camera_name \\
        --camera-map cam_south:camera2_10_0_1_3

    # 実際に取り込む
    python scripts/import_from_other_system.py \\
        --source /mnt/other_system/detections \\
        --apply

注意:
    - --apply を指定しない限り、ファイルは一切変更されません（ドライラン）
    - 既存ファイルは上書きされません（スキップ）
    - JSONL 重複行は INSERT OR IGNORE で無視されます
    - SQLite への同期は --apply 時のみ実行されます
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import detection_store  # noqa: E402


# カメラディレクトリとして扱わないディレクトリ名
_SKIP_DIRS = {"masks", "runtime_settings", "manual_recordings"}
# コピー対象外のファイル名
_SKIP_FILES = {".DS_Store", "detections.db", "detection_labels.json"}
# JSONL ファイルは個別処理するためコピー対象外
_SKIP_EXTENSIONS = {".jsonl", ".db"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="別システムの detections/ ディレクトリから検出データを取り込む。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source", "-s",
        required=True,
        help="取り込み元の detections/ ディレクトリのパス（sshfs マウント先や rsync コピー先など）",
    )
    parser.add_argument(
        "--target", "-t",
        default="detections",
        help="取り込み先の detections/ ディレクトリのパス（デフォルト: detections）",
    )
    parser.add_argument(
        "--camera-map", "-m",
        action="append",
        default=[],
        metavar="OLD:NEW",
        help="カメラ名マッピング。例: old_camera_name:new_camera_name。複数指定可。",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="実際にファイルをコピーし JSONL・SQLite を更新する（指定しないとドライラン）",
    )
    parser.add_argument(
        "--cameras",
        nargs="+",
        metavar="CAMERA_NAME",
        help="取り込むカメラ名を絞り込む（ソース側のカメラ名で指定）。省略時は全カメラ。",
    )
    return parser.parse_args()


def parse_camera_map(camera_map_args: list[str]) -> dict[str, str]:
    """'OLD:NEW' 形式の引数をパースして辞書に変換する。"""
    mapping: dict[str, str] = {}
    for entry in camera_map_args:
        parts = entry.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise SystemExit(f"--camera-map の形式が不正です（'OLD:NEW' の形式で指定してください）: {entry!r}")
        mapping[parts[0]] = parts[1]
    return mapping


def load_jsonl_records(jsonl_path: Path) -> list[tuple[str, dict]]:
    """JSONL ファイルを読み込んで (raw_line, parsed_dict) のリストを返す。"""
    if not jsonl_path.exists():
        return []
    results = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            results.append((stripped, json.loads(stripped)))
        except json.JSONDecodeError as exc:
            print(f"  WARNING: JSONL パースエラー（スキップ）: {exc} — {stripped[:120]!r}", file=sys.stderr)
    return results


def rewrite_asset_paths(record: dict, old_camera: str, new_camera: str) -> dict:
    """JSONL レコード内のアセットパスのカメラ名プレフィックスを置き換える。

    例: "old_camera/meteor_xxx.jpg" → "new_camera/meteor_xxx.jpg"
    """
    updated = dict(record)
    prefix_old = old_camera + "/"
    prefix_new = new_camera + "/"

    for field in ("clip_path", "image_path", "composite_original_path"):
        value = updated.get(field)
        if isinstance(value, str) and value.startswith(prefix_old):
            updated[field] = prefix_new + value[len(prefix_old):]

    alt_paths = updated.get("alternate_clip_paths")
    if isinstance(alt_paths, list):
        updated["alternate_clip_paths"] = [
            prefix_new + p[len(prefix_old):] if isinstance(p, str) and p.startswith(prefix_old) else p
            for p in alt_paths
        ]

    return updated


def collect_media_files(source_cam_dir: Path) -> list[Path]:
    """コピー対象のメディアファイル一覧を返す（JSONL・DB・スキップ対象は除外）。"""
    files = []
    for path in source_cam_dir.iterdir():
        if path.is_dir():
            continue
        if path.name in _SKIP_FILES:
            continue
        if path.suffix.lower() in _SKIP_EXTENSIONS:
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.name)


def sync_to_sqlite(target_dir: Path, camera_name: str, apply: bool) -> None:
    """JSONL → SQLite への増分同期を実行する。"""
    db_path = str(target_dir / "detections.db")
    detection_store.init_db(db_path)

    # sync_state をリセットして全行を再処理させる
    detection_store.reset_sync_state(db_path, camera_name)

    # normalize_fn を dashboard_routes からインポート
    from dashboard_routes import _normalize_detection_record  # noqa: PLC0415

    cam_dir = target_dir / camera_name
    inserted = detection_store.sync_camera_from_jsonl(
        camera_name,
        cam_dir,
        db_path,
        _normalize_detection_record,
    )
    return inserted


def process_camera(
    source_cam_dir: Path,
    target_dir: Path,
    source_camera: str,
    target_camera: str,
    apply: bool,
) -> dict:
    """1 カメラ分の取り込み処理を行う。"""
    target_cam_dir = target_dir / target_camera
    source_jsonl = source_cam_dir / "detections.jsonl"
    target_jsonl = target_cam_dir / "detections.jsonl"
    camera_renamed = source_camera != target_camera

    # --- JSONL 読み込み ---
    source_records = load_jsonl_records(source_jsonl)
    target_records_set: set[str] = set()
    if target_jsonl.exists():
        for raw_line, _ in load_jsonl_records(target_jsonl):
            target_records_set.add(raw_line)

    # --- メディアファイル収集 ---
    media_files = collect_media_files(source_cam_dir)

    # --- 新規 JSONL レコードの特定 ---
    new_jsonl_lines: list[str] = []
    skipped_jsonl = 0
    for raw_line, record in source_records:
        if camera_renamed:
            record = rewrite_asset_paths(record, source_camera, target_camera)
            raw_line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if raw_line in target_records_set:
            skipped_jsonl += 1
        else:
            new_jsonl_lines.append(raw_line)

    # --- コピー対象ファイルの特定 ---
    files_to_copy: list[tuple[Path, Path]] = []
    files_skipped: list[Path] = []
    for src_file in media_files:
        dest_file = target_cam_dir / src_file.name
        if dest_file.exists():
            files_skipped.append(src_file)
        else:
            files_to_copy.append((src_file, dest_file))

    result = {
        "source_camera": source_camera,
        "target_camera": target_camera,
        "records_total": len(source_records),
        "records_new": len(new_jsonl_lines),
        "records_skipped": skipped_jsonl,
        "files_to_copy": len(files_to_copy),
        "files_skipped": len(files_skipped),
        "sqlite_inserted": 0,
    }

    if not apply:
        # ドライラン: ファイル一覧だけ表示
        for src_file, dest_file in files_to_copy:
            print(f"    [copy] {src_file.name}")
        for src_file in files_skipped:
            print(f"    [skip] {src_file.name} (既存)")
        for line in new_jsonl_lines:
            preview = line[:80] + ("..." if len(line) > 80 else "")
            print(f"    [jsonl] {preview}")
        return result

    # --- 実行フェーズ ---
    target_cam_dir.mkdir(parents=True, exist_ok=True)

    # ファイルコピー
    for src_file, dest_file in files_to_copy:
        shutil.copy2(str(src_file), str(dest_file))
        print(f"    copied: {src_file.name}")

    # JSONL 追記
    if new_jsonl_lines:
        with open(target_jsonl, "a", encoding="utf-8") as f:
            for line in new_jsonl_lines:
                f.write(line + "\n")
        print(f"    JSONL に {len(new_jsonl_lines)} 行追記しました")

    # SQLite 同期
    try:
        inserted = sync_to_sqlite(target_dir, target_camera, apply=True)
        result["sqlite_inserted"] = inserted
        print(f"    SQLite に {inserted} 件挿入しました")
    except Exception as exc:
        print(f"    WARNING: SQLite 同期エラー: {exc}", file=sys.stderr)

    return result


def main() -> None:
    args = parse_args()
    source_dir = Path(args.source).resolve()
    target_dir = Path(args.target).resolve()
    camera_map = parse_camera_map(args.camera_map)
    apply = args.apply
    filter_cameras = set(args.cameras) if args.cameras else None

    # --- バリデーション ---
    if not source_dir.exists():
        raise SystemExit(f"ERROR: --source が見つかりません: {source_dir}")
    if not source_dir.is_dir():
        raise SystemExit(f"ERROR: --source はディレクトリでなければなりません: {source_dir}")
    if apply and not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"取り込み先ディレクトリを作成しました: {target_dir}")
    elif not apply and not target_dir.exists():
        print(f"NOTE: 取り込み先ディレクトリは未作成です（--apply 時に作成）: {target_dir}")

    mode = "apply" if apply else "dry-run"
    print(f"モード: {mode}")
    print(f"取り込み元: {source_dir}")
    print(f"取り込み先: {target_dir}")
    if camera_map:
        print("カメラ名マッピング:")
        for old, new in camera_map.items():
            print(f"  {old} → {new}")
    print()

    # --- カメラディレクトリの探索 ---
    camera_dirs: list[tuple[Path, str, str]] = []  # (source_cam_dir, source_name, target_name)
    for entry in sorted(source_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in _SKIP_DIRS:
            continue
        if entry.name.startswith("."):
            continue
        # detections.jsonl がなければカメラディレクトリではないとみなす
        if not (entry / "detections.jsonl").exists():
            print(f"SKIP: {entry.name}/ (detections.jsonl なし)")
            continue
        source_camera = entry.name
        if filter_cameras is not None and source_camera not in filter_cameras:
            continue
        target_camera = camera_map.get(source_camera, source_camera)
        camera_dirs.append((entry, source_camera, target_camera))

    if not camera_dirs:
        print("取り込み対象のカメラディレクトリが見つかりませんでした。")
        return

    # --- 各カメラの処理 ---
    total_records_new = 0
    total_files_copied = 0
    total_sqlite_inserted = 0

    for source_cam_dir, source_camera, target_camera in camera_dirs:
        display = source_camera if source_camera == target_camera else f"{source_camera} → {target_camera}"
        print(f"カメラ: {display}")

        result = process_camera(
            source_cam_dir=source_cam_dir,
            target_dir=target_dir,
            source_camera=source_camera,
            target_camera=target_camera,
            apply=apply,
        )

        print(
            f"  レコード: 合計={result['records_total']}"
            f"  新規={result['records_new']}"
            f"  スキップ(重複)={result['records_skipped']}"
        )
        print(
            f"  ファイル: コピー={result['files_to_copy']}"
            f"  スキップ(既存)={result['files_skipped']}"
        )
        if apply:
            print(f"  SQLite 挿入: {result['sqlite_inserted']} 件")

        total_records_new += result["records_new"]
        total_files_copied += result["files_to_copy"]
        total_sqlite_inserted += result["sqlite_inserted"]
        print()

    # --- サマリー ---
    print("=" * 50)
    print(f"完了: モード={mode}  カメラ数={len(camera_dirs)}")
    print(f"  新規 JSONL レコード: {total_records_new} 件")
    print(f"  コピーファイル:       {total_files_copied} 個")
    if apply:
        print(f"  SQLite 挿入:        {total_sqlite_inserted} 件")
    else:
        print()
        print("  ※ドライランです。実際に取り込むには --apply を追加してください。")


if __name__ == "__main__":
    main()
