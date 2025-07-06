import streamlit as st
import os
import subprocess
import sqlite3
from pathlib import Path
import base64
import re
from datetime import datetime
import threading
import http.server
import socketserver
from urllib.parse import quote
import time

# --- Configuration ---
DATA_DIR = Path("data")
RECORDINGS_DIR = DATA_DIR / "recordings"
SEGMENTS_DIR = DATA_DIR / "segments"
THUMB_DIR = DATA_DIR / "thumbnails"
DB_PATH = DATA_DIR / "metadata.db"

# HTTP Server for serving video files
VIDEO_SERVER_PORT = 8502  # Different from Streamlit's default port
VIDEO_SERVER_STARTED = False

class VideoHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DATA_DIR), **kwargs)
    
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        super().end_headers()

def start_video_server():
    global VIDEO_SERVER_STARTED, VIDEO_SERVER_PORT  # Move global declaration to the top
    if not VIDEO_SERVER_STARTED:
        try:
            handler = VideoHTTPRequestHandler
            httpd = socketserver.TCPServer(("", VIDEO_SERVER_PORT), handler)
            server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            server_thread.start()
            VIDEO_SERVER_STARTED = True
            time.sleep(0.5)  # Give server time to start
        except OSError:
            # Port might be in use, try next port
            VIDEO_SERVER_PORT += 1
            start_video_server()

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
    # Retrieve duration and frame rate via ffprobe
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
        subprocess.run([
            'ffmpeg', '-y', '-i', str(video_path),
            '-ss', str(time_offset), '-vframes', '1', '-q:v', '2',
            str(thumb_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return encode_file(thumb_path)

def main():
    st.set_page_config(page_title="Slomo Golf Clip Manager", layout="wide")
    DATA_DIR.mkdir(exist_ok=True)
    RECORDINGS_DIR.mkdir(exist_ok=True)
    SEGMENTS_DIR.mkdir(exist_ok=True)
    init_db()
    
    # Start the video server
    start_video_server()

    # Enhanced CSS for video containers and buttons
    st.markdown(
        """
        <style>
        .video-container { 
            max-width: 100%; 
            margin-bottom: 4px; 
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 8px;
            background: #f8f9fa;
        }
        .control-button { 
            margin: 2px; 
            padding: 6px 12px; 
            border-radius: 4px;
            background: #007bff;
            color: white;
            border: none;
            cursor: pointer;
            font-size: 12px;
        }
        .control-button:hover {
            background: #0056b3;
        }
        video {
            background-color: #000;
            border-radius: 4px;
            width: 100%;
            height: auto;
        }
        .video-controls {
            margin-top: 8px;
            text-align: center;
        }
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
    
    # Create URL for the video file
    video_url = f"http://localhost:{VIDEO_SERVER_PORT}/recordings/{quote(selected.name)}"

    # Enhanced player with better controls
    html = f"""
    <div class='video-container'>
        <video id='mainVideo' width='100%' controls preload='metadata' 
               onloadedmetadata='this.currentTime=0.01'>
            <source src='{video_url}' type='video/mp4'>
            Your browser does not support the video tag.
        </video>
        <div class='video-controls'>
            <button class='control-button' onclick="setPlaybackRate(0.25)">0.25×</button>
            <button class='control-button' onclick="setPlaybackRate(0.5)">0.5×</button>
            <button class='control-button' onclick="setPlaybackRate(1)">1×</button>
            <button class='control-button' onclick="frameStep(-1)">◀︎ Frame</button>
            <button class='control-button' onclick="frameStep(1)">▶︎ Frame</button>
            <button class='control-button' onclick="skipTime(-1)">-1s</button>
            <button class='control-button' onclick="skipTime(1)">+1s</button>
        </div>
    </div>
    <script>
        function setPlaybackRate(rate) {{
            document.getElementById('mainVideo').playbackRate = rate;
        }}
        
        function frameStep(direction) {{
            const video = document.getElementById('mainVideo');
            const frameTime = {step};
            video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + (direction * frameTime)));
        }}
        
        function skipTime(seconds) {{
            const video = document.getElementById('mainVideo');
            video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + seconds));
        }}
    </script>
    """
    st.components.v1.html(html, height=500)

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
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

    # Display in two columns for larger videos
    cols = st.columns(2)
    for idx, (seg_id, rec_file, seg_file, bucket, notes) in enumerate(segments):
        col = cols[idx % 2]
        seg_path = DATA_DIR / seg_file
        duration, fps = get_video_info(seg_path)
        step = 1 / fps
        
        # Create URL for the segment file
        video_url = f"http://localhost:{VIDEO_SERVER_PORT}/{quote(seg_file)}"

        with col:
            html = f"""
            <div class='video-container'>
                <video id='video{seg_id}' width='100%' controls preload='metadata' 
                       onloadedmetadata='this.currentTime=0.01'>
                    <source src='{video_url}' type='video/mp4'>
                    Your browser does not support the video tag.
                </video>
                <div class='video-controls'>
                    <button class='control-button' onclick="setPlaybackRate{seg_id}(0.25)">0.25×</button>
                    <button class='control-button' onclick="setPlaybackRate{seg_id}(0.5)">0.5×</button>
                    <button class='control-button' onclick="setPlaybackRate{seg_id}(1)">1×</button>
                    <button class='control-button' onclick="frameStep{seg_id}(-1)">◀︎</button>
                    <button class='control-button' onclick="frameStep{seg_id}(1)">▶︎</button>
                </div>
            </div>
            <script>
                function setPlaybackRate{seg_id}(rate) {{
                    document.getElementById('video{seg_id}').playbackRate = rate;
                }}
                
                function frameStep{seg_id}(direction) {{
                    const video = document.getElementById('video{seg_id}');
                    const frameTime = {step};
                    video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + (direction * frameTime)));
                }}
            </script>
            """
            st.components.v1.html(html, height=450)
            
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