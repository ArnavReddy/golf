#!/usr/bin/env python3
import cv2
import numpy as np
from scipy.signal import find_peaks
import subprocess
import sqlite3
from pathlib import Path

# ── CONFIG ─────────────────────────────────────────────────────────────
COMPRESSED_DIR    = Path("compressed")
SWINGS_DIR        = Path("swings")
SWINGS_DIR.mkdir(exist_ok=True)
SEGMENTS_DIR      = Path("data/segments")
DOWNSAMPLE_FACTOR = 4
EDGE_TRIM_PCT     = 0.0258
MIN_SEP_SEC       = 20.0
WINDOW_SEC        = 10.0

# ── UTILITIES ──────────────────────────────────────────────────────────
def get_video_duration(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    fps         = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return frame_count / fps

def compute_motion_series(video_path: Path, downsample: int):
    cap, fps = cv2.VideoCapture(str(video_path)), None
    fps = cap.get(cv2.CAP_PROP_FPS)
    prev_gray = None
    idx = 0
    times, mags = [], []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % downsample == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                flow = cv2.calcOpticalFlowFarneback(
                    prev_gray, gray, None,
                    pyr_scale=0.5, levels=3, winsize=15,
                    iterations=3, poly_n=5, poly_sigma=1.2, flags=0
                )
                mag, _ = cv2.cartToPolar(flow[...,0], flow[...,1])
                times.append(idx/fps)
                mags.append(mag.mean())
            prev_gray = gray
        idx += 1
    cap.release()
    return np.array(times), np.array(mags)

def detect_impacts(times, mags, percentile=95, min_sep=MIN_SEP_SEC):
    if len(mags) < 2:
        return np.array([])
    thr = np.percentile(mags, percentile)
    sample_interval = times[1] - times[0]
    min_dist = int(1 / sample_interval)
    peaks, _ = find_peaks(mags, height=thr, distance=min_dist)
    # enforce true time separation
    out, last_t = [], -min_sep
    for p in peaks:
        t = times[p]
        if t - last_t >= min_sep:
            out.append(t)
            last_t = t
    return np.array(out)

def load_manual_windows(video_stem: str):
    """
    From data/segments/<stem>/seg_<start>_<end>.mp4 files,
    return list of (start_s, end_s).
    """
    folder = SEGMENTS_DIR / video_stem
    if not folder.exists():
        return []
    windows = []
    for seg in folder.glob("seg_*_*.mp4"):
        name = seg.stem  # "seg_75000_100000"
        try:
            parts = name.split("_")
            start_ms, end_ms = float(parts[1]), float(parts[2])
            windows.append((start_ms/1000.0, end_ms/1000.0))
        except:
            continue
    return windows

# ── MAIN ────────────────────────────────────────────────────────────────
all_results = {}  # video_stem → { correct, added, missed }

for video in COMPRESSED_DIR.glob("*.mp4"):
    stem = video.stem
    print(f"\n▶️ Processing {video.name}")
    dur = get_video_duration(video)
    print(f"   Duration: {dur:.2f}s")

    # 1) detect if not debugging
    times, mags = compute_motion_series(video, downsample=DOWNSAMPLE_FACTOR)
    impacts = detect_impacts(times, mags)
    # 2) trim edges
    lo, hi = dur * EDGE_TRIM_PCT, dur*(1-EDGE_TRIM_PCT)
    impacts = impacts[(impacts>=lo)&(impacts<=hi)]
    print(f"   Predicted impacts: {impacts.tolist()}")

    # 4) load manual windows
    manual = load_manual_windows(stem)
    print(f"   Manual windows:    {manual}")

    # 5) classify
    correct, added = [], []
    for t in impacts:
        if any(s <= t <= e for (s,e) in manual):
            correct.append(t)
        else:
            added.append(t)
    missed = []
    for (s,e) in manual:
        if not any(s <= t <= e for t in impacts):
            missed.append((s,e))

    # store results
    all_results[stem] = {
        "correct": sorted(correct),
        "added":   sorted(added),
        "missed":  sorted(missed),
    }

    # 6) write out clips
    swing_dir = SWINGS_DIR
    for i, t in enumerate(impacts, start=1):
        start_time = max(0, t - WINDOW_SEC)
        out_name   = f"{stem}_{i:02d}_{start_time:.1f}s.mp4"
        out_path   = swing_dir / out_name
        subprocess.run([
            "ffmpeg","-y",
            "-ss", f"{start_time:.3f}",
            "-i", str(video),
            "-t",  f"{2*WINDOW_SEC:.3f}",
            "-c",  "copy",
            str(out_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"   Wrote {len(impacts)} swing clips to {swing_dir}/")

    # ── SUMMARY ─────────────────────────────────────────────────────────────
    print("\n📊 Segmentation Summary:")
    total_correct = total_added = total_missed = 0
    for stem, res in all_results.items():
        c, a, m = len(res["correct"]), len(res["added"]), len(res["missed"])
        total_correct += c
        total_added   += a
        total_missed  += m
        print(f"  • {stem}: correct={c}, added={a}, missed={m}")
    print("────────────────────────────")
    print(f"  Total correct segments:         {total_correct}")
    print(f"  Total incorrectly added:        {total_added}")
    print(f"  Total manually missed segments: {total_missed}")
print("\n✅ All done! Clips saved to ./swings/")
