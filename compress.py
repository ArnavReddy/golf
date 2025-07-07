#!/usr/bin/env python3
import argparse
import subprocess
import os
from pathlib import Path

# Supported input extensions
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm"}

def process_file(input_path: Path, output_path: Path, crf: int, preset: str):
    """Run ffmpeg to convert/compress a single file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        # video: H.264 + chosen preset/quality
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        # audio: AAC 128k
        "-c:a", "aac", "-b:a", "128k",
        str(output_path)
    ]
    subprocess.run(cmd, check=True)

def main():
    p = argparse.ArgumentParser(
        description="Convert videos to MP4/H.264 and compress them in batch"
    )
    p.add_argument("--input_dir", type=Path, default="./uncompressed", help="Directory to scan for videos")
    p.add_argument(
        "--output_dir",
        type=Path,
        nargs="?",
        default="./compressed",
        help="Where to save processed files (defaults to input_dir/_compressed/)",
    )
    p.add_argument(
        "--crf",
        type=int,
        default=35,
        help="FFmpeg CRF (quality): lower = better quality, higher = more compression",
    )
    p.add_argument(
        "--preset",
        choices=[
            "ultrafast","superfast","veryfast","faster","fast",
            "medium","slow","slower","veryslow"
        ],
        default="medium",
        help="FFmpeg encoding preset (speed vs. compression tradeoff)",
    )
    args = p.parse_args()

    inp = args.input_dir.resolve()
    out = (args.output_dir or (inp / "_compressed")).resolve()
    print(f"Input dir : {inp}")
    print(f"Output dir: {out}")
    print(f"CRF        : {args.crf}")
    print(f"Preset     : {args.preset}")
    print()

    for root, _, files in os.walk(inp):
        root_path = Path(root)
        rel = root_path.relative_to(inp)
        for fname in files:
            in_path = root_path / fname
            if in_path.suffix.lower() not in VIDEO_EXTS:
                continue  # skip non-video files

            # always output .mp4
            out_rel = rel / (in_path.stem + ".mp4")
            out_path = out / out_rel
            if out_path.exists():
                continue

            print(f"→ {in_path.relative_to(inp)}  →  {out_rel}")
            try:
                process_file(in_path, out_path, args.crf, args.preset)
            except subprocess.CalledProcessError:
                print(f"  ✖ Error processing {in_path}")
    print("\nAll done!")

if __name__ == "__main__":
    main()
