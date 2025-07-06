import streamlit as st
import os
import subprocess
import sqlite3
from pathlib import Path
import base64
import re
from datetime import datetime

# --- Configuration ---
DATA_DIR = Path("data")
RECORDINGS_DIR = DATA_DIR / "recordings"
SEGMENTS_DIR = DATA_DIR / "segments"
THUMB_DIR = DATA_DIR / "thumbnails"
DB_PATH = DATA_DIR / "metadata.db"


def init_db():
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
    return sorted(RECORDINGS_DIR.glob("*.mp4"))


def get_video_info(path: Path):
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'format=duration',
        '-of', 'csv=p=0', str(path)
    ]
    duration = float(subprocess.run(cmd, capture_output=True, text=True).stdout.strip())
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=r_frame_rate',
        '-of', 'csv=p=0', str(path)
    ]
    rate = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    nums = re.split(r"[/\\]", rate)
    fps = float(nums[0]) / float(nums[1]) if len(nums) == 2 else float(nums[0])
    return duration, fps


def encode_file(path: Path):
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode()


def make_thumbnail(video_path: Path, seg_id: int, time_offset: float = 0.1):
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    thumb_path = THUMB_DIR / f"thumb_{seg_id}.png"
    if not thumb_path.exists():
        cmd = [
            'ffmpeg', '-y', '-i', str(video_path),
            '-ss', str(time_offset), '-vframes', '1', '-q:v', '2',
            str(thumb_path)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return encode_file(thumb_path)


def main():
    st.set_page_config(page_title="Slomo Golf Clip Manager", layout="wide")
    DATA_DIR.mkdir(exist_ok=True)
    RECORDINGS_DIR.mkdir(exist_ok=True)
    SEGMENTS_DIR.mkdir(exist_ok=True)
    init_db()

    # Global CSS for video containers and buttons
    st.markdown(
        """
        <style>
        .video-container { max-width: 100%; margin-bottom: 8px; }
        .control-button { margin: 2px; padding: 4px 8px; border-radius: 4px; }
        </style>
        """, unsafe_allow_html=True
    )

    st.sidebar.title("📂 Recordings")
    page = st.sidebar.radio("Navigate", ["Segment", "Browse"])
    if page == "Segment":
        segment_page()
    else:
        browse_page()


def segment_page():
    st.header("✂️ Segment & Categorize a Recording")
    uploaded = st.file_uploader("Upload a .mp4 recording", type=["mp4"])
    if uploaded:
        save_path = RECORDINGS_DIR / uploaded.name
        if not save_path.exists():
            with open(save_path, 'wb') as f:
                f.write(uploaded.getbuffer())
            st.success(f"Saved recording: {uploaded.name}")

    recs = list_recordings()
    if not recs:
        st.info("No recordings found. Please upload a .mp4 file.")
        return
    selected = st.selectbox("Select a recording", recs, format_func=lambda p: p.name)

    duration, fps = get_video_info(selected)
    step = 1 / fps
    b64 = encode_file(selected)

    # Player with custom controls
    html = (
        f"<div class='video-container'>"
        f"<video id='video' width='100%' controls preload='metadata'>"
        f"<source src='data:video/mp4;base64,{b64}' type='video/mp4'>"
        "</video><br>"
        f"<button class='control-button' onclick=\"document.getElementById('video').playbackRate=0.5\">0.5×</button>"
        f"<button class='control-button' onclick=\"document.getElementById('video').playbackRate=1\">1×</button>"
        f"<button class='control-button' onclick=\"var v=document.getElementById('video');v.currentTime=Math.max(0,v.currentTime-{step});\">◀︎ Frame</button>"
        f"<button class='control-button' onclick=\"var v=document.getElementById('video');v.currentTime=Math.min(v.duration,v.currentTime+{step});\">▶︎ Frame</button>"
        "</div>"
    )
    st.components.v1.html(html, height=360)

    start = st.slider("Start time (s)", 0.0, duration, 0.0, 0.01)
    end = st.slider("End time (s)", 0.0, duration, duration, 0.01)
    bucket = st.selectbox("Assign bucket (0=worst, 5=best)", list(range(6)))
    notes = st.text_input("Notes (optional)")

    if start >= end:
        st.error("Start must be less than end.")
    elif st.button("Save Segment"):
        segment_dir = SEGMENTS_DIR / selected.stem
        segment_dir.mkdir(parents=True, exist_ok=True)
        out_name = f"seg_{int(start*1000)}_{int(end*1000)}.mp4"
        out_path = segment_dir / out_name
        subprocess.run([
            'ffmpeg', '-y', '-i', str(selected),
            '-ss', str(start), '-to', str(end),
            '-avoid_negative_ts', 'make_zero', '-c', 'copy',
            '-movflags', '+faststart', str(out_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO recordings(filename) VALUES(?)", (selected.name,))
        c.execute("SELECT id FROM recordings WHERE filename=?", (selected.name,))
        rec_id = c.fetchone()[0]
        rel_path = str(out_path.relative_to(DATA_DIR))
        c.execute(
            "INSERT INTO segments(recording_id,filename,start_sec,end_sec,bucket,notes) VALUES(?,?,?,?,?,?)",
            (rec_id, rel_path, start, end, bucket, notes)
        )
        conn.commit()
        conn.close()
        st.success(f"Saved segment {out_name} with bucket {bucket}.")


def browse_page():
    st.header("🔍 Browse & Edit Segments")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, filename, imported_at FROM recordings ORDER BY imported_at DESC")
    recs = c.fetchall()
    dates = sorted({datetime.fromisoformat(r[2]).date() for r in recs})
    selected_date = st.sidebar.selectbox("Filter by date", ["All"] + [d.isoformat() for d in dates])
    buckets = st.sidebar.multiselect("Filter by bucket", list(range(6)), default=list(range(6)))

    query = (
        "SELECT s.id, r.filename, s.filename, s.bucket, s.notes "
        "FROM segments s JOIN recordings r ON s.recording_id=r.id"
    )
    params, conds = [], []
    if selected_date != "All":
        conds.append("date(r.imported_at)=?")
        params.append(selected_date)
    conds.append(f"s.bucket IN ({','.join(map(str,buckets))})")
    query += " WHERE " + " AND ".join(conds)
    c.execute(query, params)
    segments = c.fetchall()
    conn.close()

    if not segments:
        st.info("No segments found for selected filters.")
        return

    # Use two columns for larger videos
    cols = st.columns(2)
    for idx, (seg_id, rec_file, seg_file, bucket, notes) in enumerate(segments):
        col = cols[idx % 2]
        seg_path = DATA_DIR / seg_file
        thumb_b64 = make_thumbnail(seg_path, seg_id)
        duration, fps = get_video_info(seg_path)
        step = 1 / fps
        seg_b64 = encode_file(seg_path)

        with col:
            html = (
                f"<div class='video-container'>"
                f"<video id='video{seg_id}' width='100%' controls preload='metadata' poster='data:image/png;base64,{thumb_b64}'>"
                f"<source src='data:video/mp4;base64,{seg_b64}' type='video/mp4'>"
                "</video><br>"
                f"<button class='control-button' onclick=\"document.getElementById('video{seg_id}').playbackRate=0.5\">0.5×</button>"
                f"<button class='control-button' onclick=\"document.getElementById('video{seg_id}').playbackRate=1\">1×</button>"
                f"<button class='control-button' onclick=\"var v=document.getElementById('video{seg_id}');v.currentTime=Math.max(0,v.currentTime-{step});\">◀︎</button>"
                f"<button class='control-button' onclick=\"var v=document.getElementById('video{seg_id}');v.currentTime=Math.min(v.duration,v.currentTime+{step});\">▶︎</button>"
                "</div>"
            )
            st.components.v1.html(html, height=380)
            st.markdown(f"**Bucket:** {bucket}")
            with st.expander("Details"):
                new_bucket = st.selectbox("Bucket", options=list(range(6)), index=bucket, key=f"bucket{seg_id}")
                new_notes = st.text_input("Notes", value=notes or "", key=f"notes{seg_id}")
                if st.button("Update", key=f"update{seg_id}"):
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute("UPDATE segments SET bucket=?, notes=? WHERE id=?", (new_bucket, new_notes, seg_id))
                    conn.commit()
                    conn.close()
                    st.success("Updated segment.")

if __name__ == "__main__":
    main()
