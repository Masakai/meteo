#!/usr/bin/env python3
"""detections 配下の 2 つの検出ディレクトリを統合する。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


SKIP_DIRS = {"masks", "runtime_settings"}
SKIP_FILES = {"detections.jsonl", ".DS_Store"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge one detections/<source> directory into detections/<target>."
    )
    parser.add_argument("--detections-dir", default="detections", help="Detections root directory.")
    parser.add_argument(
        "--source",
        "--from",
        dest="source",
        default="南側",
        help="Source directory name under detections.",
    )
    parser.add_argument(
        "--target",
        "--to",
        dest="target",
        default="camera2_10_0_1_3",
        help="Target directory name under detections.",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes to disk.")
    parser.add_argument(
        "--cleanup-source",
        action="store_true",
        help="Remove empty source files/directories that are left after a successful merge.",
    )
    return parser.parse_args()


def load_records(jsonl_path: Path) -> list[dict]:
    if not jsonl_path.exists():
        return []

    records: list[dict] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def write_records(jsonl_path: Path, records: list[dict]) -> None:
    def sort_key(record: dict) -> tuple[str, str]:
        return (str(record.get("timestamp", "")), str(record.get("id", "")))

    payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in sorted(records, key=sort_key))
    tmp_path = jsonl_path.with_suffix(".jsonl.tmp")
    tmp_path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")
    tmp_path.replace(jsonl_path)


def collect_asset_names(records: list[dict]) -> set[str]:
    names: set[str] = set()
    for record in records:
        for key in ("clip_path", "image_path", "composite_original_path"):
            value = str(record.get(key, "")).strip()
            if value:
                names.add(value)
        for key in ("alternate_clip_paths",):
            for value in record.get(key, []) or []:
                name = str(value).strip()
                if name:
                    names.add(name)
    return names


def collect_move_candidates(source_dir: Path, records: list[dict]) -> list[Path]:
    candidates: set[Path] = set()
    asset_names = collect_asset_names(records)
    for name in asset_names:
        path = source_dir / name
        if path.exists() and path.is_file():
            candidates.add(path)

    for path in source_dir.iterdir():
        if path.is_dir() or path.name in SKIP_FILES or path.name in asset_names:
            continue
        candidates.add(path)

    return sorted(candidates, key=lambda path: path.name)


def ensure_no_record_conflicts(target_records: list[dict], source_records: list[dict]) -> None:
    target_ids = {str(record.get("id", "")).strip() for record in target_records if str(record.get("id", "")).strip()}
    target_bases = {
        str(record.get("base_name", "")).strip() for record in target_records if str(record.get("base_name", "")).strip()
    }

    duplicate_ids = sorted(
        {
            str(record.get("id", "")).strip()
            for record in source_records
            if str(record.get("id", "")).strip() and str(record.get("id", "")).strip() in target_ids
        }
    )
    duplicate_bases = sorted(
        {
            str(record.get("base_name", "")).strip()
            for record in source_records
            if str(record.get("base_name", "")).strip() and str(record.get("base_name", "")).strip() in target_bases
        }
    )

    if duplicate_ids or duplicate_bases:
        problems = []
        if duplicate_ids:
            problems.append(f"duplicate ids: {', '.join(duplicate_ids)}")
        if duplicate_bases:
            problems.append(f"duplicate base_name: {', '.join(duplicate_bases)}")
        raise SystemExit("merge aborted due to conflicts: " + "; ".join(problems))


def ensure_no_file_conflicts(target_dir: Path, source_files: list[Path]) -> None:
    conflicts = [path.name for path in source_files if (target_dir / path.name).exists()]
    if conflicts:
        raise SystemExit("merge aborted due to existing target files: " + ", ".join(sorted(conflicts)))


def remove_empty_source_paths(source_dir: Path) -> list[Path]:
    removed: list[Path] = []

    for path in sorted(source_dir.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            removed.append(path)

    if source_dir.exists() and not any(source_dir.iterdir()):
        source_dir.rmdir()
        removed.append(source_dir)

    return removed


def main() -> None:
    args = parse_args()
    detections_dir = Path(args.detections_dir)
    source_dir = detections_dir / args.source
    target_dir = detections_dir / args.target

    if not source_dir.exists():
        print(f"source dir not found, skipping: {source_dir}")
        return
    if not target_dir.exists():
        raise SystemExit(f"target dir not found: {target_dir}")
    if source_dir.resolve() == target_dir.resolve():
        raise SystemExit("source and target must be different directories")

    source_jsonl = source_dir / "detections.jsonl"
    target_jsonl = target_dir / "detections.jsonl"
    source_records = load_records(source_jsonl)
    target_records = load_records(target_jsonl)

    ensure_no_record_conflicts(target_records, source_records)
    move_candidates = collect_move_candidates(source_dir, source_records)
    ensure_no_file_conflicts(target_dir, move_candidates)

    merged_records = target_records + source_records

    if args.apply:
        for path in move_candidates:
            shutil.move(str(path), str(target_dir / path.name))
        write_records(target_jsonl, merged_records)
        if source_jsonl.exists():
            source_jsonl.unlink()
        if args.cleanup_source:
            removed = remove_empty_source_paths(source_dir)
        else:
            removed = []
    else:
        removed = []

    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode} detections_dir={detections_dir}")
    print(f"source={source_dir.name} target={target_dir.name}")
    print(f"records_to_merge={len(source_records)} target_records_after_merge={len(merged_records)}")
    print(f"files_to_move={len(move_candidates)}")
    for path in move_candidates:
        print(f"move {path.relative_to(detections_dir)} -> {(target_dir / path.name).relative_to(detections_dir)}")
    print(f"remove {source_jsonl.relative_to(detections_dir.parent)}")
    if args.apply and args.cleanup_source:
        print(f"removed_paths={len(removed)}")
        for path in removed:
            print(f"removed {path.relative_to(detections_dir.parent)}")


if __name__ == "__main__":
    main()
