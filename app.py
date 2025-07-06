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

def video_to_base64(video_path: Path):
    """Convert video file to base64 data URI"""
    with open(video_path, 'rb') as f:
        video_data = f.read()
    video_b64 = base64.b64encode(video_data).decode()
    return f"data:video/mp4;base64,{video_b64}"

def create_enhanced_video_player(video_path: Path, video_id: str, fps: float = 30.0):
    """Create an enhanced video player with frame-by-frame and speed controls"""
    file_size = video_path.stat().st_size
    
    # For files larger than 50MB, show a warning and use file path
    if file_size > 50 * 1024 * 1024:
        st.warning(f"Video file is {file_size // (1024*1024)}MB. Large files may not play properly.")
        # Try to use file:// URL (works in some browsers)
        video_src = f"file://{video_path.absolute()}"
    else:
        # Use base64 encoding for smaller files
        video_src = video_to_base64(video_path)
    
    frame_duration = 1.0 / fps  # Duration of one frame in seconds
    
    html = f"""
    <div style="background: #000; padding: 8px; border-radius: 8px; margin-bottom: 16px;">
        <video id="{video_id}" width="100%" controls preload="metadata" 
               style="background: #000; border-radius: 4px;">
            <source src="{video_src}" type="video/mp4">
            Your browser does not support the video tag.
        </video>
        
        <!-- Speed Controls -->
        <div style="margin-top: 8px; text-align: center;">
            <strong style="color: white; margin-right: 10px;">Speed:</strong>
            <button onclick="setSpeed_{video_id}(0.1)" 
                    style="margin: 2px; padding: 4px 8px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer;">
                0.1×
            </button>
            <button onclick="setSpeed_{video_id}(0.25)" 
                    style="margin: 2px; padding: 4px 8px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer;">
                0.25×
            </button>
            <button onclick="setSpeed_{video_id}(0.5)" 
                    style="margin: 2px; padding: 4px 8px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer;">
                0.5×
            </button>
            <button onclick="setSpeed_{video_id}(1)" 
                    style="margin: 2px; padding: 4px 8px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer;">
                1×
            </button>
        </div>
        
        <!-- Frame Controls -->
        <div style="margin-top: 8px; text-align: center;">
            <strong style="color: white; margin-right: 10px;">Frame:</strong>
            <button onclick="previousFrame_{video_id}()" 
                    style="margin: 2px; padding: 4px 8px; background: #ff6b35; color: white; border: none; border-radius: 4px; cursor: pointer;">
                ◀ Prev
            </button>
            <button onclick="nextFrame_{video_id}()" 
                    style="margin: 2px; padding: 4px 8px; background: #ff6b35; color: white; border: none; border-radius: 4px; cursor: pointer;">
                Next ▶
            </button>
            <button onclick="pauseVideo_{video_id}()" 
                    style="margin: 2px; padding: 4px 8px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer;">
                Pause
            </button>
        </div>
        
        <!-- Current Time Display -->
        <div style="margin-top: 8px; text-align: center;">
            <span id="timeDisplay_{video_id}" style="color: white; font-family: monospace; font-size: 14px;">
                0.00s
            </span>
        </div>
    </div>
    
    <script>
        (function() {{
            const video = document.getElementById('{video_id}');
            const timeDisplay = document.getElementById('timeDisplay_{video_id}');
            const frameDuration = {frame_duration};
            
            // Update time display
            function updateTimeDisplay() {{
                if (video && timeDisplay) {{
                    timeDisplay.textContent = video.currentTime.toFixed(2) + 's';
                }}
            }}
            
            if (video) {{
                video.addEventListener('timeupdate', updateTimeDisplay);
                video.addEventListener('loadedmetadata', updateTimeDisplay);
            }}
            
            // Speed control
            window.setSpeed_{video_id} = function(rate) {{
                if (video) {{
                    video.playbackRate = rate;
                }}
            }}
            
            // Frame navigation
            window.previousFrame_{video_id} = function() {{
                if (video) {{
                    video.pause();
                    video.currentTime = Math.max(0, video.currentTime - frameDuration);
                    updateTimeDisplay();
                }}
            }}
            
            window.nextFrame_{video_id} = function() {{
                if (video) {{
                    video.pause();
                    video.currentTime = Math.min(video.duration || 0, video.currentTime + frameDuration);
                    updateTimeDisplay();
                }}
            }}
            
            window.pauseVideo_{video_id} = function() {{
                if (video) {{
                    if (video.paused) {{
                        video.play();
                    }} else {{
                        video.pause();
                    }}
                }}
            }}
            
            // Keyboard shortcuts
            document.addEventListener('keydown', function(e) {{
                // Only if this video is in focus area
                const rect = video.getBoundingClientRect();
                const isInView = rect.top >= 0 && rect.top <= window.innerHeight;
                
                if (isInView && video) {{
                    switch(e.key) {{
                        case 'ArrowLeft':
                            e.preventDefault();
                            window.previousFrame_{video_id}();
                            break;
                        case 'ArrowRight':
                            e.preventDefault();
                            window.nextFrame_{video_id}();
                            break;
                        case ' ':
                            e.preventDefault();
                            window.pauseVideo_{video_id}();
                            break;
                    }}
                }}
            }});
        }})();
    </script>
    """
    return html

def create_simple_video_player(video_path: Path, video_id: str):
    """Create a simple video player without localhost server"""
    file_size = video_path.stat().st_size
    
    # For files larger than 50MB, show a warning and use file path
    if file_size > 50 * 1024 * 1024:
        st.warning(f"Video file is {file_size // (1024*1024)}MB. Large files may not play properly.")
        # Try to use file:// URL (works in some browsers)
        video_src = f"file://{video_path.absolute()}"
    else:
        # Use base64 encoding for smaller files
        video_src = video_to_base64(video_path)
    
    html = f"""
    <div style="background: #000; padding: 8px; border-radius: 8px; margin-bottom: 16px;">
        <video id="{video_id}" width="100%" controls preload="metadata" 
               style="background: #000; border-radius: 4px;">
            <source src="{video_src}" type="video/mp4">
            Your browser does not support the video tag.
        </video>
        <div style="margin-top: 8px; text-align: center;">
            <button onclick="setSpeed_{video_id}(0.25)" 
                    style="margin: 2px; padding: 4px 8px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer;">
                0.25×
            </button>
            <button onclick="setSpeed_{video_id}(0.5)" 
                    style="margin: 2px; padding: 4px 8px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer;">
                0.5×
            </button>
            <button onclick="setSpeed_{video_id}(1)" 
                    style="margin: 2px; padding: 4px 8px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer;">
                1×
            </button>
        </div>
    </div>
    <script>
        function setSpeed_{video_id}(rate) {{
            const video = document.getElementById('{video_id}');
            if (video) {{
                video.playbackRate = rate;
            }}
        }}
    </script>
    """
    return html

def main():
    st.set_page_config(page_title="Slomo Golf Clip Manager", layout="wide")
    DATA_DIR.mkdir(exist_ok=True)
    RECORDINGS_DIR.mkdir(exist_ok=True)
    SEGMENTS_DIR.mkdir(exist_ok=True)
    init_db()

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

    # -- Video preview --
    video_id = "segment_video"
    video_uri = selected.resolve()
    start, end = st.slider(
        "Select segment window (seconds)",
        min_value=0.0,
        max_value=duration,
        value=(0.0, duration),
        step=0.01,
        format="%.2f"
    )
    html = create_simple_video_player(video_path=video_uri, video_id=video_id)
    html = html + f"""
        <script>
        window.jump_to = function(t) {{
            const v = document.getElementById('{video_id}');
            if (v) v.currentTime = t;
        }}
        </script>
        <div style="display:flex; gap:8px; margin-top:8px;">
            <button onclick="jump_to({start:.2f})"
                    style="padding:6px 12px; border:none;
                            border-radius:4px; background:#007bff;
                            color:#fff; cursor:pointer;">
                ↤ Jump to start ({start:.2f}s)
            </button>

            <button onclick="jump_to({end:.2f})"
                    style="padding:6px 12px; border:none;
                            border-radius:4px; background:#28a745;
                            color:#fff; cursor:pointer;">
                Jump to end ({end:.2f}s) ↦
            </button>
        </div>
    """

    st.components.v1.html(html, height=1000)

    bucket = st.selectbox("Assign bucket (0=worst, 5=best)", list(range(6)))
    notes = st.text_input("Notes (optional)")

    if start >= end:
        st.error("Start must be less than end.")
    elif st.button("Save Segment"):
        segment_dir = SEGMENTS_DIR / selected.stem
        segment_dir.mkdir(parents=True, exist_ok=True)
        out_name = f"seg_{int(start*1000)}_{int(end*1000)}.mp4"
        out_path = segment_dir / out_name

        with st.spinner("Creating segment..."):
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
    
    # Add info about keyboard shortcuts
    st.info("💡 **Keyboard Shortcuts:** Use ← → arrow keys for frame navigation, Space to pause/play (when video is in view)")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, filename, imported_at FROM recordings ORDER BY imported_at DESC")
    recs = c.fetchall()
    dates = sorted({datetime.fromisoformat(r[2]).date() for r in recs}) if recs else []
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
    if buckets:
        conds.append(f"s.bucket IN ({','.join(map(str,buckets))})")
    if conds:
        query += " WHERE " + " AND ".join(conds)
    c.execute(query, params)
    segments = c.fetchall()
    conn.close()

    if not segments:
        st.info("No segments found for selected filters.")
        return

    # Enhanced video player option
    use_enhanced_player = st.sidebar.checkbox("Use Enhanced Video Player", value=True, help="Enables frame-by-frame navigation and more speed options")
    use_columns = st.sidebar.checkbox("Show in columns", value=True)
    
    if use_columns:
        cols = st.columns(2)
        for idx, (seg_id, rec_file, seg_file, bucket, notes) in enumerate(segments):
            col = cols[idx % 2]
            seg_path = DATA_DIR / seg_file
            
            with col:
                st.markdown(f"**Segment {seg_id} - Bucket {bucket}**")
                
                # Get video info for frame rate
                try:
                    original_path = RECORDINGS_DIR / rec_file
                    if original_path.exists():
                        _, fps = get_video_info(original_path)
                    else:
                        fps = 30.0  # Default fallback
                except:
                    fps = 30.0  # Default fallback
                
                file_size = seg_path.stat().st_size
                
                if use_enhanced_player and file_size < 10 * 1024 * 1024:  # < 10MB, use enhanced player
                    video_html = create_enhanced_video_player(seg_path, f"video{seg_id}", fps)
                    st.components.v1.html(video_html, height=500)
                elif file_size < 10 * 1024 * 1024:  # < 10MB, use simple player
                    video_html = create_simple_video_player(seg_path, f"video{seg_id}")
                    st.components.v1.html(video_html, height=400)
                else:
                    # For larger files, use streamlit's video player
                    st.video(str(seg_path))
                    if use_enhanced_player:
                        st.info("Enhanced controls not available for large files. Use browser's built-in controls.")
                
                # Edit controls
                with st.expander("Edit Details"):
                    new_bucket = st.selectbox("Bucket", options=list(range(6)), index=bucket, key=f"bucket{seg_id}")
                    new_notes = st.text_input("Notes", value=notes or "", key=f"notes{seg_id}")
                    if st.button("Update", key=f"update{seg_id}"):
                        conn = sqlite3.connect(DB_PATH)
                        c = conn.cursor()
                        c.execute("UPDATE segments SET bucket=?, notes=? WHERE id=?", (new_bucket, new_notes, seg_id))
                        conn.commit()
                        conn.close()
                        st.success("Updated segment.")
                        st.rerun()
    else:
        # Single column layout
        for seg_id, rec_file, seg_file, bucket, notes in segments:
            seg_path = DATA_DIR / seg_file
            
            with st.container():
                st.markdown(f"### Segment {seg_id} - Bucket {bucket}")
                
                # Get video info for frame rate
                try:
                    original_path = RECORDINGS_DIR / rec_file
                    if original_path.exists():
                        _, fps = get_video_info(original_path)
                    else:
                        fps = 30.0  # Default fallback
                except:
                    fps = 30.0  # Default fallback
                
                if use_enhanced_player:
                    video_html = create_enhanced_video_player(seg_path, f"video{seg_id}", fps)
                    st.components.v1.html(video_html, height=500)
                else:
                    # Use streamlit's video player for single column
                    st.video(str(seg_path))
                
                # Edit controls
                col1, col2 = st.columns([3, 1])
                with col1:
                    new_notes = st.text_input("Notes", value=notes or "", key=f"notes{seg_id}")
                with col2:
                    new_bucket = st.selectbox("Bucket", options=list(range(6)), index=bucket, key=f"bucket{seg_id}")
                
                if st.button("Update", key=f"update{seg_id}"):
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute("UPDATE segments SET bucket=?, notes=? WHERE id=?", (new_bucket, new_notes, seg_id))
                    conn.commit()
                    conn.close()
                    st.success("Updated segment.")
                    st.rerun()
                
                st.divider()

if __name__ == "__main__":
    main()