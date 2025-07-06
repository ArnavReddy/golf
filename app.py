import streamlit as st
import os
import subprocess
import sqlite3
from pathlib import Path
import base64
import re

# --- Configuration ---
DATA_DIR = Path("data")
RECORDINGS_DIR = DATA_DIR / "recordings"
SEGMENTS_DIR = DATA_DIR / "segments"
DB_PATH = DATA_DIR / "metadata.db"


def init_db():
    """
    Initialize the SQLite database and tables.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS recordings (
            id INTEGER PRIMARY KEY,
            filename TEXT UNIQUE,
            imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY,
            recording_id INTEGER REFERENCES recordings(id),
            filename TEXT UNIQUE,
            start_sec REAL,
            end_sec REAL,
            bucket INTEGER,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def list_recordings():
    """Return a sorted list of available recordings."""
    return sorted(RECORDINGS_DIR.glob("*.mp4"))


def get_video_info(path: Path):
    """Use ffprobe to get video duration (s) and frame rate."""
    # Duration
    cmd_dur = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'format=duration',
        '-of', 'csv=p=0',
        str(path)
    ]
    result = subprocess.run(cmd_dur, capture_output=True, text=True)
    duration = float(result.stdout.strip())
    # Frame rate
    cmd_fps = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=r_frame_rate',
        '-of', 'csv=p=0',
        str(path)
    ]
    result = subprocess.run(cmd_fps, capture_output=True, text=True)
    rate = result.stdout.strip()  # e.g. "30000/1001"
    nums = re.split(r"[/\\\\]", rate)
    fps = float(nums[0]) / float(nums[1]) if len(nums) == 2 else float(nums[0])
    return duration, fps


def main():
    # --- Setup ---
    st.set_page_config(page_title="Slomo Golf Clip Manager", layout="wide", initial_sidebar_state="expanded")
    DATA_DIR.mkdir(exist_ok=True)
    RECORDINGS_DIR.mkdir(exist_ok=True)
    SEGMENTS_DIR.mkdir(exist_ok=True)
    init_db()

    # --- Sidebar ---
    st.sidebar.title("📂 Recordings")
    page = st.sidebar.radio("Navigate", ["Segment", "Browse"])
    
    if page == "Segment":
        segment_page()
    else:
        browse_page()


def segment_page():
    """UI for uploading/selecting a recording and creating segments."""
    st.header("✂️ Segment a Recording")

    # Upload new recording
    uploaded = st.file_uploader("Upload a .mp4 recording", type=["mp4"])
    if uploaded is not None:
        save_path = RECORDINGS_DIR / uploaded.name
        if not save_path.exists():
            with open(save_path, 'wb') as f:
                f.write(uploaded.getbuffer())
            st.success(f"Saved recording: {uploaded.name}")

    # Select existing recording
    recordings = list_recordings()
    if not recordings:
        st.info("No recordings found. Please upload a .mp4 file.")
        return
    selected = st.selectbox("Select a recording to segment", recordings, format_func=lambda p: p.name)

    # Get video info
    duration, fps = get_video_info(selected)
    step = 1 / fps

    # Read video bytes and encode
    with open(selected, 'rb') as f:
        video_bytes = f.read()
    b64 = base64.b64encode(video_bytes).decode()

    # Video player with controls
    html = f"""
    <video id="video" width="640" controls>
      <source src="data:video/mp4;base64,{b64}" type="video/mp4">
      Your browser does not support the video tag.
    </video>
    <br/>
    <button onclick="document.getElementById('video').playbackRate=0.5">0.5×</button>
    <button onclick="document.getElementById('video').playbackRate=1">1×</button>
    <button onclick="var v=document.getElementById('video'); v.currentTime = Math.max(0, v.currentTime - {step});">◀︎ Frame</button>
    <button onclick="var v=document.getElementById('video'); v.currentTime = Math.min(v.duration, v.currentTime + {step});">Frame ▶︎</button>
    """
    st.components.v1.html(html, height=360)

    # Sliders for trimming
    start = st.slider("Start time (s)", min_value=0.0, max_value=duration, value=0.0, step=0.01)
    end = st.slider("End time (s)", min_value=0.0, max_value=duration, value=duration, step=0.01)
    if start >= end:
        st.error("Start time must be less than end time.")
    else:
        if st.button("Save Segment"):
            # Prepare output path
            segment_dir = SEGMENTS_DIR / selected.stem
            segment_dir.mkdir(parents=True, exist_ok=True)
            out_name = f"seg_{int(start*1000)}_{int(end*1000)}.mp4"
            out_path = segment_dir / out_name
            # Trim with ffmpeg
            cmd = [
                'ffmpeg', '-y', '-i', str(selected),
                '-ss', str(start), '-to', str(end),
                '-c', 'copy', str(out_path)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

            # Save metadata
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO recordings(filename) VALUES(?)", (selected.name,))
            c.execute("SELECT id FROM recordings WHERE filename=?", (selected.name,))
            rec_id = c.fetchone()[0]
            rel_path = str(out_path.relative_to(DATA_DIR))
            c.execute(
                "INSERT OR IGNORE INTO segments(recording_id,filename,start_sec,end_sec,bucket,notes) VALUES(?,?,?,?,?,?)",
                (rec_id, rel_path, start, end, None, None)
            )
            conn.commit()
            conn.close()
            st.success(f"Segment saved: {out_name}")


def browse_page():
    """UI for browsing and reviewing saved segments."""
    st.header("🔍 Browse Segments")
    st.info("Browse your saved segments by date or bucket (coming soon).")
    # TODO: implement filtering and review


if __name__ == "__main__":
    main()
