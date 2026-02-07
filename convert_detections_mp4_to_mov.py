#!/usr/bin/env python3
"""Convert detection videos to Facebook-friendly MP4/MOV using ffmpeg."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def find_videos(root: Path) -> list[Path]:
    videos: list[Path] = []
    for ext in ("*.mp4", "*.mov"):
        videos.extend([p for p in root.rglob(ext) if p.is_file()])
    # 同名なら .mov を優先して先に処理
    return sorted(videos, key=lambda p: (str(p.with_suffix("")), 0 if p.suffix.lower() == ".mov" else 1))


def convert_one(
    src: Path,
    dst: Path,
    *,
    overwrite: bool,
    dry_run: bool,
    reencode: bool,
    crf: int,
    preset: str,
    delete_source: bool,
) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not overwrite:
        return "skipped"

    # mp4 -> mp4 を同一パスで上書きする場合、ffmpeg は入出力同一を許可しないため一時ファイルへ出力
    in_place = src.resolve() == dst.resolve()
    ffmpeg_dst = dst.with_name(f"{dst.stem}.tmp{dst.suffix}") if in_place else dst

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
    cmd += ["-movflags", "+faststart", str(ffmpeg_dst)]

    if dry_run:
        print("DRY RUN:", " ".join(cmd))
        return "converted"

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return "failed"

    if in_place:
        ffmpeg_dst.replace(dst)

    if delete_source and src.resolve() != dst.resolve():
        src.unlink(missing_ok=True)

    return "converted"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert all .mp4/.mov files under detections/ to Facebook-friendly video using ffmpeg."
    )
    parser.add_argument(
        "--input",
        default="detections",
        help="Input directory to scan (default: detections)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory. If omitted, writes converted file next to source.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing destination files.",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Container-only conversion without re-encoding (Facebook互換を崩す可能性あり).",
    )
    parser.add_argument(
        "--mov",
        action="store_true",
        help="Output .mov instead of .mp4.",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="変換成功後に元ファイルを削除する（拡張子変更時のみ）。",
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

    videos = find_videos(in_root)
    if not videos:
        print("No .mp4/.mov files found.")
        return 0

    converted = 0
    skipped = 0
    failed = 0

    planned_dsts: set[Path] = set()
    for src in videos:
        if out_root:
            rel = src.relative_to(in_root)
            dst = out_root / rel
            dst = dst.with_suffix(f".{output_ext}")
        else:
            dst = src.with_suffix(f".{output_ext}")

        dst_key = dst.resolve()
        if dst_key in planned_dsts:
            skipped += 1
            continue
        planned_dsts.add(dst_key)

        status = convert_one(
            src,
            dst,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            reencode=not args.copy,
            crf=args.crf,
            preset=args.preset,
            delete_source=args.delete_source,
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
