#!/usr/bin/env python3
import os
import sys
import cv2
import numpy as np
from scipy.signal import find_peaks
import subprocess
import sqlite3
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── CONFIG ─────────────────────────────────────────────────────────────
COMPRESSED_DIR    = Path("compressed")
SWINGS_DIR        = Path("swings")
SWINGS_DIR.mkdir(exist_ok=True)
SEGMENTS_DIR      = Path("data/segments")
DOWNSAMPLE_FACTOR = 4
EDGE_TRIM_PCT     = 0.0258
MIN_SEP_SEC       = 20.0
WINDOW_SEC        = 10.0

SEGMENTS_DIR      = Path("data/segments")
DATA_DIR          = Path("data")
DB_PATH           = DATA_DIR / "metadata.db"

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

# def load_manual_windows(video_stem: str):
#     """
#     From data/segments/<stem>/seg_<start>_<end>.mp4 files,
#     return list of (start_s, end_s).
#     """
#     folder = SEGMENTS_DIR / video_stem
#     if not folder.exists():
#         return []
#     windows = []
#     for seg in folder.glob("seg_*_*.mp4"):
#         name = seg.stem  # "seg_75000_100000"
#         try:
#             parts = name.split("_")
#             start_ms, end_ms = float(parts[1]), float(parts[2])
#             windows.append((start_ms/1000.0, end_ms/1000.0))
#         except:
#             continue
#     return windows

# ── MAIN ────────────────────────────────────────────────────────────────

def process_one_video(video: Path, all_results):
    stem = video.stem
    already = list(SWINGS_DIR.glob(f"{stem}_*.mp4"))
    if already:
        print(f"↷ Skipping {video.name}: {len(already)} clip(s) already exist.")
        return
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
    # # 4) load manual windows
    # manual = load_manual_windows(stem)
    # print(f"   Manual windows:    {manual}")
    # # 5) classify
    # correct, added = [], []
    # for t in impacts:
    #     if any(s <= t <= e for (s,e) in manual):
    #         correct.append(t)
    #     else:
    #         added.append(t)
    # missed = []
    # for (s,e) in manual:
    #     if not any(s <= t <= e for t in impacts):
    #         missed.append((s,e))
    # # store results
    # all_results[stem] = {
    #     "correct": sorted(correct),
    #     "added":   sorted(added),
    #     "missed":  sorted(missed),
    # }
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
    # print("\n📊 Segmentation Summary:")
    # total_correct = total_added = total_missed = 0
    # for stem, res in all_results.items():
    #     c, a, m = len(res["correct"]), len(res["added"]), len(res["missed"])
    #     total_correct += c
    #     total_added   += a
    #     total_missed  += m
    #     print(f"  • {stem}: correct={c}, added={a}, missed={m}")
    # print("────────────────────────────")
    # print(f"  Total correct segments:         {total_correct}")
    # print(f"  Total incorrectly added:        {total_added}")
    # print(f"  Total manually missed segments: {total_missed}")
def auto_segment_all():
    all_results = {}  # video_stem → { correct, added, missed }

    videos = list(COMPRESSED_DIR.glob("*.mp4"))
    if not videos:
        print("No videos found in", COMPRESSED_DIR)
        return

    print(f"Starting segmentation using up to {os.cpu_count()} threads...")
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as exe:
        futures = { exe.submit(process_one_video, v, all_results): v for v in videos }
        for fut in as_completed(futures):
            vid = futures[fut]
            try:
                fut.result()
            except Exception as e:
                print(f"⚠️  Error processing {vid.name}: {e}")
        
    print("\n✅ All done! Clips saved to ./swings/")
# ── REVIEW GUI (PyQt5) ───────────────────────────────────────────────────
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QComboBox, QMessageBox
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, QTimer

def init_db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS recordings (
            id          INTEGER PRIMARY KEY,
            filename    TEXT UNIQUE,
            imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS segments (
            id            INTEGER PRIMARY KEY,
            recording_id  INTEGER REFERENCES recordings(id),
            filename      TEXT UNIQUE,
            start_sec     REAL,
            end_sec       REAL,
            bucket        TEXT,
            notes         TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS buckets (
            id   INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        )""")
    for b in ("driver","hybrid","iron","wedge"):
        c.execute("INSERT OR IGNORE INTO buckets(name) VALUES(?)", (b,))
    conn.commit(); conn.close()

def list_buckets():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM buckets ORDER BY name")
    names = [r[0] for r in c.fetchall()]
    conn.close()
    return names
class PreviewWindow(QMainWindow):
    def __init__(self, video_path: Path, start_time: float, duration: float = 30.0):
        super().__init__()
        self.setWindowTitle("▶ Next 30s Preview")
        # central widget
        w = QWidget()
        self.setCentralWidget(w)
        v = QVBoxLayout(w)

        # video player
        self.player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        vw = QVideoWidget()
        self.player.setVideoOutput(vw)
        v.addWidget(vw)

        # load and seek
        url = QUrl.fromLocalFile(str(video_path.absolute()))
        print(url)
        self.player.setPlaybackRate(10.0)
        self.player.setMedia(QMediaContent(url))
        
        self.player.setPosition(int(start_time * 1000))
        self.player.play()
    def closeEvent(self, event):
        # stop playback and clear media so audio really stops
        self.player.stop()
        self.player.setMedia(QMediaContent())  # optional, releases the file
        super().closeEvent(event)
class ReviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎾 Swing Review")
        self.files = sorted(SWINGS_DIR.glob("*.mp4"))
        self.idx = 0

        # central widget
        w = QWidget()
        self.setCentralWidget(w)
        v = QVBoxLayout()
        w.setLayout(v)

        # video widget
        self.player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        vw = QVideoWidget()
        self.player.setVideoOutput(vw)
        v.addWidget(vw)

        # status label
        self.label = QLabel("")
        v.addWidget(self.label)

        # controls row
        row = QHBoxLayout()
        v.addLayout(row)

        self.bucket_cb = QComboBox()
        self.bucket_cb.addItems(list_buckets())
        row.addWidget(QLabel("Bucket:"))
        row.addWidget(self.bucket_cb)

        self.play_btn = QPushButton("Play/Pause")
        self.play_btn.clicked.connect(self.toggle_play)
        row.addWidget(self.play_btn)

        self.accept_btn = QPushButton("✅ Accept")
        self.accept_btn.clicked.connect(self.accept_clip)
        row.addWidget(self.accept_btn)

        self.reject_btn = QPushButton("❌ Reject")
        self.reject_btn.clicked.connect(self.reject_clip)
        row.addWidget(self.reject_btn)

        self.skip_btn = QPushButton("⏭ Skip")
        self.skip_btn.clicked.connect(self.skip_clip)
        row.addWidget(self.skip_btn)

        self.next30_btn = QPushButton("▶ Next 30s")
        self.next30_btn.clicked.connect(self.preview_next)
        row.addWidget(self.next30_btn)

        self.load_current()

    def load_current(self):
        if self.idx >= len(self.files):
            QMessageBox.information(self, "Done", "All clips reviewed!")
            self.close()
            return
        clip = self.files[self.idx]
        self.current = clip
        # parse times
        stem, _, start_s = clip.stem.rsplit("_", 2)
        start = float(start_s.rstrip("s"))
        end   = start + 2*WINDOW_SEC

        url = QUrl.fromLocalFile(str(clip.absolute()))
        self.player.setMedia(QMediaContent(url))
        self.player.play()

        self.label.setText(f"{clip.name}  —  window {start:.1f}s → {end:.1f}s")
        self.bucket_cb.setCurrentIndex(0)

    def toggle_play(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def accept_clip(self):
        # move file and record DB
        clip = self.current
        stem, _, start_s = clip.stem.rsplit("_", 2)
        start = float(start_s.rstrip("s"))
        end   = start + 2*WINDOW_SEC
        bucket = self.bucket_cb.currentText()

        dest_dir = SEGMENTS_DIR / stem
        dest_dir.mkdir(parents=True, exist_ok=True)
        start_ms = int(start*1000)
        end_ms   = int(end*1000)
        new_name = f"seg_{start_ms}_{end_ms}.mp4"
        dest = dest_dir / new_name
        shutil.move(str(clip), str(dest))

        # DB insert
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        rec_fn = f"{stem}.mp4"
        c.execute("INSERT OR IGNORE INTO recordings(filename) VALUES(?)", (rec_fn,))
        c.execute("SELECT id FROM recordings WHERE filename=?", (rec_fn,))
        rec_id = c.fetchone()[0]
        rel = str(dest.relative_to(DATA_DIR))
        c.execute(
            "INSERT OR IGNORE INTO segments(recording_id,filename,start_sec,end_sec,bucket,notes) VALUES(?,?,?,?,?,?)",
            (rec_id, rel, start, end, bucket, "")
        )
        conn.commit(); conn.close()

        self.idx += 1
        self.load_current()

    def reject_clip(self):
        # simply delete the file
        try:
            self.current.unlink()
        except:
            pass
        self.idx += 1
        self.load_current()

    def skip_clip(self):
        """Just move on to the next clip without deleting or saving."""
        self.idx += 1
        self.load_current()
    def preview_next(self):
        """
        Open a tiny popup that plays 30s immediately after this segment,
        so you can see your finger-signals without altering the clip itself.
        """
        self.toggle_play()
        clip = self.current
        stem, _, start_s = clip.stem.rsplit("_", 2)
        start = float(start_s.rstrip("s"))
        # segment length was 2*WINDOW_SEC, so end_of_segment = start + window
        end_of_segment = start + 2 * WINDOW_SEC

        # original source lives in COMPRESSED_DIR
        orig = COMPRESSED_DIR / f"{stem}.mp4"
        if not orig.exists():
            QMessageBox.warning(self, "Missing original",
                                f"Couldn't find {orig}")
            return

        preview = PreviewWindow(orig, end_of_segment, duration=30.0)
        preview.resize(640, 360)
        preview.show()
        # keep a ref so it doesn't get garbage-collected
        self._preview_win = preview

if __name__ == "__main__":
    auto_segment_all()
    init_db()
    app = QApplication(sys.argv)
    win = ReviewWindow()
    win.resize(800, 600)
    win.show()
    sys.exit(app.exec_())