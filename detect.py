import cv2
import numpy as np
from scipy.signal import find_peaks

import subprocess
from pathlib import Path

def compute_motion_series(video_path, downsample=2):
    """
    Reads the video, optionally downsamples by 'downsample' factor for speed,
    and returns (times, mags) where mags[i] is the mean flow magnitude at time times[i].
    """
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    prev_gray = None
    frame_idx = 0
    times, mags = [], []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        # skip frames to speed up
        if frame_idx % downsample != 0:
            frame_idx += 1
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
            times.append(frame_idx / fps)
        prev_gray = gray
        frame_idx += 1

    cap.release()
    return np.array(times), np.array(mags)

# compute
# times, mags = compute_motion_series("data/recordings/IMG_7432.mp4", downsample=4)

# # pick a threshold at, say, the 95th percentile of all motion
# thr = np.percentile(mags, 95)

# # require peaks to be at least 1s apart (fps thresholds)
# min_dist_sec = 1.0
# min_dist = int(min_dist_sec / (times[1] - times[0]))

# peaks, _ = find_peaks(mags, height=thr, distance=min_dist)

# impact_times = times[peaks]
impact_times = np.array([
    0.53333333, 1.6, 2.53333333, 4.53333333, 5.6,
    8.0, 88.53333333, 190.13333333, 290.53333333,
    303.73333333, 304.8, 307.6, 308.53333333, 310.0
])
print("Detected impacts at:", impact_times)

PREVIEW_DIR = Path("swings")
PREVIEW_DIR.mkdir(exist_ok=True)

for i, t in enumerate(impact_times):
    start = max(0, t - 10.0)
    dur   = 20.0
    out = PREVIEW_DIR / f"swing_{i+1:02d}_{start:.1f}s.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", "data/recordings/IMG_7432.mp4",
        "-t", f"{dur:.3f}",
        "-c", "copy",  # if you want frame‐exact, switch to re-encode as before
        str(out)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Wrote", out)

