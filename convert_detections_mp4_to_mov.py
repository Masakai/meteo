#!/usr/bin/env python3
"""Convert all .mp4 files under detections/ to Facebook-friendly .mp4 using ffmpeg."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def find_mp4s(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.mp4") if p.is_file()]


def convert_one(
    src: Path,
    dst: Path,
    *,
    overwrite: bool,
    dry_run: bool,
    reencode: bool,
    crf: int,
    preset: str,
    output_ext: str,
) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not overwrite:
        return "skipped"

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-i",
        str(src),
    ]
    if reencode:
        cmd += [
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            preset,
            "-profile:v",
            "baseline",
            "-level",
            "3.1",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-g",
            "60",
            "-keyint_min",
            "60",
            "-sc_threshold",
            "0",
            "-tag:v",
            "avc1",
            "-an",
        ]
    else:
        cmd += ["-c", "copy"]
    cmd += ["-movflags", "+faststart", str(dst)]

    if dry_run:
        print("DRY RUN:", " ".join(cmd))
        return "converted"

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return "failed"

    return "converted"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert all .mp4 files under detections/ to Facebook-friendly .mp4 using ffmpeg."
    )
    parser.add_argument(
        "--input",
        default="detections",
        help="Input directory to scan (default: detections)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory. If omitted, writes .mp4 next to each .mp4.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .mov files.",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Container-only conversion without re-encoding.",
    )
    parser.add_argument(
        "--mov",
        action="store_true",
        help="Output .mov instead of .mp4.",
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=20,
        help="CRF for H.264 encoding (lower is higher quality). Default: 20.",
    )
    parser.add_argument(
        "--preset",
        default="medium",
        help="x264 preset (ultrafast..veryslow). Default: medium.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ffmpeg commands without executing.",
    )

    args = parser.parse_args()
    in_root = Path(args.input)
    if not in_root.exists():
        sys.stderr.write(f"Input directory not found: {in_root}\n")
        return 2

    out_root = Path(args.output) if args.output else None
    output_ext = "mov" if args.mov else "mp4"

    mp4s = find_mp4s(in_root)
    if not mp4s:
        print("No .mp4 files found.")
        return 0

    converted = 0
    skipped = 0
    failed = 0

    for src in mp4s:
        if out_root:
            rel = src.relative_to(in_root)
            dst = out_root / rel
            dst = dst.with_suffix(f".{output_ext}")
        else:
            dst = src.with_suffix(f".{output_ext}")

        status = convert_one(
            src,
            dst,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            reencode=not args.copy,
            crf=args.crf,
            preset=args.preset,
            output_ext=output_ext,
        )
        if status == "converted":
            converted += 1
        elif status == "skipped":
            skipped += 1
        else:
            failed += 1

    print(f"converted={converted} skipped={skipped} failed={failed}")
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
