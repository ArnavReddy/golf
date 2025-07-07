#!/usr/bin/env python3
import cv2
import numpy as np
from scipy.signal import find_peaks
import subprocess
from pathlib import Path

# ── CONFIG ─────────────────────────────────────────────────────────────
COMPRESSED_DIR    = Path("compressed")
SWINGS_DIR        = Path("swings")
SWINGS_DIR.mkdir(exist_ok=True)
DOWNSAMPLE_FACTOR = 4         # skip every 4th frame to speed up
EDGE_TRIM_PCT     = 0.0258    # cut first/last 2.58%
MIN_SEP_SEC       = 20.0      # minimum seconds between impacts
WINDOW_SEC        = 10.0      # seconds before & after impact

# ── UTILITIES ──────────────────────────────────────────────────────────
def get_video_duration(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    fps         = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return frame_count / fps

def compute_motion_series(video_path: Path, downsample: int):
    """Return (times, mags) for average optical-flow magnitude per sampled frame."""
    cap      = cv2.VideoCapture(str(video_path))
    fps      = cap.get(cv2.CAP_PROP_FPS)
    prev_gray = None
    idx      = 0
    times, mags = [], []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % downsample != 0:
            idx += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0
            )
            mag, _ = cv2.cartToPolar(flow[...,0], flow[...,1])
            mags.append(mag.mean())
            times.append(idx / fps)

        prev_gray = gray
        idx += 1

    cap.release()
    return np.array(times), np.array(mags)

def detect_impacts(times, mags, percentile=95, min_sep=MIN_SEP_SEC):
    """Pick peaks in mags above the given percentile, then enforce min separation."""
    if len(mags) < 2:
        return np.array([])
    thr = np.percentile(mags, percentile)
    # distance in samples
    sample_interval = times[1] - times[0]
    min_dist_samples = int(1 / sample_interval)
    peaks, _ = find_peaks(mags, height=thr, distance=min_dist_samples)

    print(f"Before separation = {times[peaks]}")

    # now enforce true time separation
    out = []
    last_t = -min_sep
    for p in peaks:
        t = times[p]
        if t - last_t >= min_sep:
            out.append(t)
            last_t = t
    return np.array(out)

# ── MAIN LOOP ──────────────────────────────────────────────────────────
def main():
    for video in COMPRESSED_DIR.glob("*.mp4"):
        print(f"\n▶️ Processing {video.name}")
        dur = get_video_duration(video)
        print(f"   Duration: {dur:.2f}s")

        # 1) compute motion series
        times, mags = compute_motion_series(video, downsample=DOWNSAMPLE_FACTOR)

        # 2) detect impacts
        impacts = detect_impacts(times, mags)
        print(f"   Raw impacts: {impacts}")

        # 3) trim out those within first/last EDGE_TRIM_PCT
        edge_start = dur * EDGE_TRIM_PCT
        edge_end   = dur * (1 - EDGE_TRIM_PCT)
        impacts = impacts[(impacts >= edge_start) & (impacts <= edge_end)]
        print(f"   After edge trim: {impacts}")
        print(f"   Final impacts: {impacts}")

        # 5) slice out windows
        for i, t in enumerate(impacts, start=1):
            start_time = max(0.0, t - WINDOW_SEC)
            out_name   = f"{video.stem}_{i:02d}_{start_time:.1f}s.mp4"
            out_path   = SWINGS_DIR / out_name
            print(f"    • Writing {out_name} (impact@{t:.2f}s)")

            subprocess.run([
                "ffmpeg", "-y",
                "-ss", f"{start_time:.3f}",
                "-i", str(video),
                "-t",  f"{2*WINDOW_SEC:.3f}",
                "-c",  "copy",
                str(out_path)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        break

    print("\n✅ All done! Clips saved to ./swings/")

if __name__ == "__main__":
    main()
