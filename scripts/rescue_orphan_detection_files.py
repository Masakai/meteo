#!/usr/bin/env python3
"""detections.jsonl から孤立した検出ファイルを救済する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


METEOR_FILE_RE = re.compile(
    r"^(meteor_\d{8}_\d{6}(?:_[A-Za-z0-9]+(?:_\d{2})?)?)(\.mp4|\.mov|_composite\.jpg|_composite_original\.jpg)$"
)


def make_rescued_detection_id(camera_name: str, base_name: str, timestamp: str) -> str:
    source = {
        "camera": camera_name,
        "base_name": base_name,
        "timestamp": timestamp,
        "rescued": True,
    }
    digest = hashlib.sha1(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"det_{digest[:20]}"


def parse_base_timestamp(base_name: str) -> str:
    parts = base_name.split("_")
    dt = datetime.strptime(f"{parts[1]}_{parts[2]}", "%Y%m%d_%H%M%S")
    return dt.isoformat()


def load_records(jsonl_path: Path) -> list[dict]:
    records: list[dict] = []
    if not jsonl_path.exists():
        return records
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


def collect_orphan_groups(camera_dir: Path, records: list[dict]) -> dict[str, dict[str, str]]:
    referenced = set()
    for record in records:
        for key in ("clip_path", "image_path", "composite_original_path"):
            value = str(record.get(key, "")).strip()
            if value:
                referenced.add(value)

        if not any(str(record.get(key, "")).strip() for key in ("clip_path", "image_path", "composite_original_path")):
            base_name = str(record.get("base_name", "")).strip()
            if not base_name:
                timestamp = str(record.get("timestamp", "")).strip()
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        base_name = f"meteor_{dt.strftime('%Y%m%d_%H%M%S')}"
                    except Exception:
                        base_name = ""
            if base_name:
                for suffix in (".mp4", ".mov", "_composite.jpg", "_composite_original.jpg"):
                    candidate = camera_dir / f"{base_name}{suffix}"
                    if candidate.exists():
                        referenced.add(candidate.name)

    groups: dict[str, dict[str, str]] = defaultdict(dict)
    for path in sorted(camera_dir.iterdir()):
        if not path.is_file() or path.name in {"detections.jsonl", ".DS_Store"}:
            continue
        match = METEOR_FILE_RE.match(path.name)
        if not match:
            continue
        if path.name in referenced:
            continue
        base_name, suffix = match.groups()
        groups[base_name][suffix] = path.name
    return groups


def rescue_camera(camera_dir: Path, apply: bool) -> dict:
    jsonl_path = camera_dir / "detections.jsonl"
    records = load_records(jsonl_path)
    orphan_groups = collect_orphan_groups(camera_dir, records)
    by_base = {str(record.get("base_name", "")).strip(): record for record in records if str(record.get("base_name", "")).strip()}

    patched = 0
    appended = 0
    for base_name, files in sorted(orphan_groups.items()):
        existing = by_base.get(base_name)
        if existing:
            changed = False
            alternate = list(existing.get("alternate_clip_paths", []))
            if not str(existing.get("clip_path", "")).strip():
                clip_name = files.get(".mp4") or files.get(".mov")
                if clip_name:
                    existing["clip_path"] = clip_name
                    changed = True
            else:
                for clip_suffix in (".mp4", ".mov"):
                    clip_name = files.get(clip_suffix)
                    if clip_name and clip_name != existing.get("clip_path") and clip_name not in alternate:
                        alternate.append(clip_name)
                        changed = True
            if not str(existing.get("image_path", "")).strip() and files.get("_composite.jpg"):
                existing["image_path"] = files["_composite.jpg"]
                changed = True
            if not str(existing.get("composite_original_path", "")).strip() and files.get("_composite_original.jpg"):
                existing["composite_original_path"] = files["_composite_original.jpg"]
                changed = True
            if alternate:
                existing["alternate_clip_paths"] = alternate
            if changed:
                patched += 1
            continue

        timestamp = parse_base_timestamp(base_name)
        rescued = {
            "timestamp": timestamp,
            "confidence": 0.0,
            "id": make_rescued_detection_id(camera_dir.name, base_name, timestamp),
            "base_name": base_name,
            "rescued_from_orphan": True,
        }
        clip_name = files.get(".mp4") or files.get(".mov")
        if clip_name:
            rescued["clip_path"] = clip_name
        if files.get("_composite.jpg"):
            rescued["image_path"] = files["_composite.jpg"]
        if files.get("_composite_original.jpg"):
            rescued["composite_original_path"] = files["_composite_original.jpg"]
        records.append(rescued)
        by_base[base_name] = rescued
        appended += 1

    if apply and (patched or appended):
        write_records(jsonl_path, records)

    return {
        "camera": camera_dir.name,
        "patched": patched,
        "appended": appended,
        "orphan_groups": len(orphan_groups),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rescue orphaned detection files back into detections.jsonl.")
    parser.add_argument("--detections-dir", default="detections", help="Detections root directory.")
    parser.add_argument("--apply", action="store_true", help="Write rescued records to detections.jsonl.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    detections_dir = Path(args.detections_dir)
    if not detections_dir.exists():
        raise SystemExit(f"detections dir not found: {detections_dir}")

    summaries = []
    for camera_dir in sorted(p for p in detections_dir.iterdir() if p.is_dir() and p.name != "runtime_settings"):
        summary = rescue_camera(camera_dir, apply=args.apply)
        if summary["orphan_groups"] > 0:
            summaries.append(summary)

    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode} detections_dir={detections_dir}")
    for summary in summaries:
        print(
            f"{summary['camera']}: orphan_groups={summary['orphan_groups']} "
            f"patched={summary['patched']} appended={summary['appended']}"
        )


if __name__ == "__main__":
    main()
