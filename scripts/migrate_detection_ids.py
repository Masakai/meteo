#!/usr/bin/env python3
"""Add stable detection ids to existing detections.jsonl and audit integrity."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


def make_detection_id(camera_name: str, record: dict) -> str:
    source = {
        "camera": camera_name,
        "timestamp": record.get("timestamp", ""),
        "start_time": record.get("start_time", ""),
        "end_time": record.get("end_time", ""),
        "start_point": record.get("start_point", ""),
        "end_point": record.get("end_point", ""),
    }
    digest = hashlib.sha1(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"det_{digest[:20]}"


def display_time(record: dict) -> str:
    timestamp = str(record.get("timestamp", "")).strip()
    if not timestamp:
        return ""
    return timestamp.replace("T", " ")[:19]


def legacy_base_name(record: dict) -> str:
    timestamp = str(record.get("timestamp", "")).strip()
    if not timestamp:
        return ""
    dt = datetime.fromisoformat(timestamp)
    return f"meteor_{dt.strftime('%Y%m%d_%H%M%S')}"


def update_record(camera_name: str, record: dict, camera_dir: Path) -> tuple[dict, dict]:
    updated = dict(record)
    changes = {"id_added": False, "paths_added": 0}
    detection_id = str(updated.get("id", "")).strip()
    if not detection_id:
        detection_id = make_detection_id(camera_name, updated)
        updated["id"] = detection_id
        changes["id_added"] = True

    base_name = str(updated.get("base_name", "")).strip()
    if not base_name:
        base_name = legacy_base_name(updated)
        if base_name:
            updated["base_name"] = base_name

    fields = [
        ("clip_path", ".mp4"),
        ("image_path", "_composite.jpg"),
        ("composite_original_path", "_composite_original.jpg"),
    ]
    for field_name, suffix in fields:
        value = str(updated.get(field_name, "")).strip()
        if value:
            continue
        if not base_name:
            continue
        candidate = camera_dir / f"{base_name}{suffix}"
        if candidate.exists():
            updated[field_name] = candidate.name
            changes["paths_added"] += 1

    return updated, changes


def normalize_label(value: str) -> str:
    return "post_detected" if str(value).strip() == "post_detected" else "detected"


def migrate_camera_jsonl(camera_dir: Path, apply: bool) -> dict:
    jsonl_path = camera_dir / "detections.jsonl"
    stats = {
        "camera": camera_dir.name,
        "records": 0,
        "ids_added": 0,
        "paths_added": 0,
        "duplicate_ids": 0,
        "shared_assets": 0,
        "missing_assets": 0,
        "records_data": [],
    }
    if not jsonl_path.exists():
        return stats

    updated_lines = []
    seen_ids = Counter()
    asset_refs = Counter()
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        updated, changes = update_record(camera_dir.name, record, camera_dir)
        stats["records"] += 1
        stats["ids_added"] += int(changes["id_added"])
        stats["paths_added"] += int(changes["paths_added"])
        seen_ids[updated["id"]] += 1
        for field in ("clip_path", "image_path", "composite_original_path"):
            rel = str(updated.get(field, "")).strip()
            if rel:
                asset_refs[rel] += 1
            elif field != "clip_path":
                stats["missing_assets"] += 1
        stats["records_data"].append(updated)
        updated_lines.append(json.dumps(updated, ensure_ascii=False))

    stats["duplicate_ids"] = sum(1 for count in seen_ids.values() if count > 1)
    stats["shared_assets"] = sum(1 for count in asset_refs.values() if count > 1)

    if apply:
        jsonl_path.write_text("\n".join(updated_lines) + ("\n" if updated_lines else ""), encoding="utf-8")
    return stats


def migrate_labels(detections_dir: Path, records_by_camera: dict[str, list[dict]], apply: bool) -> dict:
    labels_path = detections_dir / "detection_labels.json"
    stats = {"converted": 0, "dropped": 0, "total": 0}
    if not labels_path.exists():
        return stats

    raw = json.loads(labels_path.read_text(encoding="utf-8"))
    converted = {}
    lookup = {}
    for camera_name, records in records_by_camera.items():
        for record in records:
            lookup[f"{camera_name}|{display_time(record)}"] = record["id"]

    for key, value in raw.items():
        stats["total"] += 1
        if key.startswith("det_"):
            converted[key] = normalize_label(value)
            continue
        detection_id = lookup.get(key)
        if detection_id:
            converted[detection_id] = normalize_label(value)
            stats["converted"] += 1
        else:
            stats["dropped"] += 1

    if apply:
        labels_path.write_text(json.dumps(converted, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return stats


def parse_args():
    parser = argparse.ArgumentParser(description="Migrate detections.jsonl records to id-based format.")
    parser.add_argument("--detections-dir", default="detections", help="Detections root directory.")
    parser.add_argument("--apply", action="store_true", help="Write changes to disk.")
    return parser.parse_args()


def main():
    args = parse_args()
    detections_dir = Path(args.detections_dir)
    if not detections_dir.exists():
        raise SystemExit(f"detections dir not found: {detections_dir}")

    records_by_camera: dict[str, list[dict]] = {}
    summaries = []
    for camera_dir in sorted(p for p in detections_dir.iterdir() if p.is_dir()):
        summary = migrate_camera_jsonl(camera_dir, apply=args.apply)
        records_by_camera[camera_dir.name] = summary.pop("records_data")
        if summary["records"] > 0:
            summaries.append(summary)

    label_stats = migrate_labels(detections_dir, records_by_camera, apply=args.apply)

    print(f"mode={'apply' if args.apply else 'dry-run'} detections_dir={detections_dir}")
    for summary in summaries:
        print(
            f"{summary['camera']}: records={summary['records']} ids_added={summary['ids_added']} "
            f"paths_added={summary['paths_added']} duplicate_ids={summary['duplicate_ids']} "
            f"shared_assets={summary['shared_assets']} missing_assets={summary['missing_assets']}"
        )
    print(
        f"labels: total={label_stats['total']} converted={label_stats['converted']} dropped={label_stats['dropped']}"
    )


if __name__ == "__main__":
    main()
