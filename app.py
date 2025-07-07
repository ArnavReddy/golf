import streamlit as st
import os
import subprocess
import sqlite3
from pathlib import Path
import re
from datetime import datetime
import tempfile
import time
import base64
import re

# --- Configuration (unchanged) ---
DATA_DIR        = Path("data")
RECORDINGS_DIR  = DATA_DIR / "recordings"
SEGMENTS_DIR    = DATA_DIR / "segments"
DB_PATH         = DATA_DIR / "metadata.db"

def init_db():
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
            bucket        INTEGER,
            notes         TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS buckets (
            id   INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        )
    """)
    for b in ("driver","hybrid","iron","wedge"):
        c.execute("INSERT OR IGNORE INTO buckets(name) VALUES(?)", (b,))
    conn.commit()
    conn.close()

def list_recordings():
    return sorted(RECORDINGS_DIR.glob("*.mp4"))

def list_buckets():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM buckets ORDER BY name")
    names = [r[0] for r in c.fetchall()]
    conn.close()
    return names

def parse_timestamp(ts: str) -> float:
    parts = ts.strip().split(":")
    if not parts or len(parts) > 3:
        raise ValueError("Invalid timestamp format")
    # pad to [HH, MM, SS]
    parts = [float(p) for p in parts]
    if len(parts) == 1:
        hours, mins, secs = 0, 0, parts[0]
    elif len(parts) == 2:
        hours, mins, secs = 0, parts[0], parts[1]
    else:
        hours, mins, secs = parts
    return hours * 3600 + mins * 60 + secs

def format_timestamp(seconds: float) -> str:
    """Format a float seconds into HH:MM:SS (zero-padded)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"  # SS.ss with two decimals

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
    with open(video_path, "rb") as f:
        data = f.read()
    return "data:video/mp4;base64," + base64.b64encode(data).decode()

def create_enhanced_video_player(video_path: Path, video_id: str):
    """Create an enhanced video player with frame-by-frame and speed controls"""
    video_src = video_to_base64(video_path)
    
    frame_duration = 1.0 / 30  # Duration of one frame in seconds
    
    html = f"""
    <script>
        (function() {{
            window._prevInterval_{video_id} = null;
            window._nextInterval_{video_id} = null;
        }})
    </script>
    <div style="background: #000; padding: 8px; border-radius: 8px; margin-bottom: 16px;">
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
            <button 
                    onclick="previousFrame_{video_id}()"
                    onmousedown="window._prevInterval_{video_id} = setInterval(previousFrame_{video_id}, 150)"
                    onmouseup="clearInterval(window._prevInterval_{video_id})"
                    onmouseleave="clearInterval(window._prevInterval_{video_id})"
                    style="margin: 2px; padding: 4px 8px; background: #ff6b35; color: white; border: none; border-radius: 4px; cursor: pointer;">
                ◀ Prev
            </button>
            <button onclick="nextFrame_{video_id}()" 
                    onmousedown="window._nextInterval_{video_id} = setInterval(nextFrame_{video_id}, 150)"
                    onmouseup="clearInterval(window._nextInterval_{video_id})"
                    onmouseleave="clearInterval(window._nextInterval_{video_id})"
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
        <video id="{video_id}" width="100%" controls preload="metadata" 
               style="background: #000; border-radius: 4px;">
            <source src="{video_src}" type="video/mp4">
            Your browser does not support the video tag.
        </video>
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

# --- Streamlit App ---
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

    # — Upload & select recording —
    uploaded = st.file_uploader("Upload a .mp4 recording", type=["mp4"])
    if uploaded:
        save_path = RECORDINGS_DIR / uploaded.name
        save_path.parent.mkdir(exist_ok=True, parents=True)
        if not save_path.exists():
            save_path.write_bytes(uploaded.getbuffer())
            st.success(f"Saved recording: {uploaded.name}")

    recs = list_recordings()
    if not recs:
        st.info("No recordings yet; upload one above.")
        return

    selected = st.selectbox("Select a recording", recs, format_func=lambda p: p.name)
    duration, fps = get_video_info(selected)
    frame_delta = 1.0 / fps

    # — Show original video & meta —
    st.video(str(selected), width = 500)
    size_mb = selected.stat().st_size / (1024*1024)
    st.info(f"Duration: {duration:.2f}s | Size: {size_mb:.1f}MB | FPS: {fps:.1f}")
    start_ts = "00:00:00"
    end_ts = format_timestamp(duration)

    # — Controls for Start and End with frame & 0.5s jumps —
    col_s, col_e = st.columns(2)
    with col_s:
        start_ts = st.text_input(
            "Start (HH:MM:SS)", value=start_ts, key="start_ts"
        )
    with col_e:
        end_ts = st.text_input(
            "End (HH:MM:SS)", value=end_ts, key="end_ts"
        )

    # — Parse & validate —
    parse_error = None
    try:
        start = parse_timestamp(start_ts)
        end   = parse_timestamp(end_ts)
        if start < 0 or end < 0 or start > duration or end > duration:
            parse_error = "Timestamps must be between 00:00:00 and video length."
        elif start >= end:
            parse_error = "Start must be less than end."
    except ValueError:
        parse_error = "Invalid timestamp format—use HH:MM:SS, MM:SS or SS."

    if parse_error:
        st.error(parse_error)
        return
    else:
        st.markdown(f"**Segment window:** {format_timestamp(start)} → {format_timestamp(end)}")


    # — Preview button & inline player —
    if st.button("▶️ Preview Segment"):
        preview_dir = DATA_DIR / "previews"
        preview_dir.mkdir(exist_ok=True, parents=True)
        start_ms = int(start * 1000)
        end_ms   = int(end   * 1000)
        preview_name = f"{selected.stem}_{start_ms}_{end_ms}.mp4"
        preview_path = preview_dir / preview_name

        # only re-create if not already there (fast replay)
        if not preview_path.exists():
            with st.spinner("Creating preview…"):
                subprocess.run([
                    "ffmpeg", "-y",
                    "-i", str(selected),
                    "-ss", str(start),        # seek before input
                    "-t",  f"{end-start:.3f}", # duration of segment
                    # re-encode for accurate seeking
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    str(preview_path)
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        st.video(str(preview_path), width = 200)

    # — Bucket & notes & final save —
    new_bucket = st.text_input("➕ Add a new bucket", key="new_bucket")
    if st.button("Add bucket"):
        b = new_bucket.strip()
        if b:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO buckets(name) VALUES(?)", (b,))
            conn.commit(); conn.close()
            st.success(f"Added bucket: {b}")
            st.experimental_rerun()

    bucket = st.selectbox("Assign bucket", list_buckets())
    notes  = st.text_input("Notes (optional)")

    if st.button("Save Segment"):
        s, e = start, end
        start_ms = int(s * 1000)
        end_ms   = int(e   * 1000)
        if s >= e:
            st.error("Start must be less than end.")
        else:
            segment_dir = SEGMENTS_DIR / selected.stem
            segment_dir.mkdir(exist_ok=True, parents=True)
            out_name = f"seg_{start_ms}_{end_ms}.mp4"
            out_path = segment_dir / out_name
            with st.spinner(f"Writing segment…"):
                subprocess.run([
                    "ffmpeg", "-y",
                    "-i", str(selected),
                    "-ss", str(s),        # seek before input
                    "-t",  f"{e-s:.3f}", # duration of segment
                    # re-encode for accurate seeking
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    str(out_path)
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # record in DB
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO recordings(filename) VALUES(?)", (selected.name,))
            c.execute("SELECT id FROM recordings WHERE filename=?", (selected.name,))
            rec_id = c.fetchone()[0]
            rel_path = str(out_path.relative_to(DATA_DIR))
            c.execute(
                "INSERT INTO segments(recording_id,filename,start_sec,end_sec,bucket,notes) VALUES(?,?,?,?,?,?)",
                (rec_id, rel_path, s, e, bucket, notes)
            )
            conn.commit(); conn.close()
            st.success(f"Saved segment {out_name} in bucket '{bucket}'!")

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
    bucket_names = list_buckets()
    buckets = st.sidebar.multiselect("Filter by bucket", bucket_names, default=bucket_names)

    query = (
        "SELECT s.id, r.filename, s.filename, s.bucket, s.notes "
        "FROM segments s JOIN recordings r ON s.recording_id=r.id"
    )
    params, conds = [], []
    if selected_date != "All":
        conds.append("date(r.imported_at)=?")
        params.append(selected_date)
    if buckets:
        # build a "?,?..." placeholder string matching how many were picked
        placeholder_str = ",".join("?" for _ in buckets)
        conds.append(f"s.bucket IN ({placeholder_str})")
        # extend the params array with the actual bucket *strings*
        params.extend(buckets)
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
                
                file_size = seg_path.stat().st_size
                
                if use_enhanced_player:
                    video_html = create_enhanced_video_player(seg_path, f"video{seg_id}")
                    st.components.v1.html(video_html, height=500)
                else:  # < 10MB, use simple player
                    video_html = create_simple_video_player(seg_path, f"video{seg_id}")
                    st.components.v1.html(video_html, height=400)
                
                # Edit controls
                with st.expander("Edit Details"):
                    if st.button("🗑️ Delete segment", key=f"delete{seg_id}"):
                        # 1) delete the file
                        try:
                            os.remove(seg_path)
                        except OSError:
                            pass

                        # 2) delete the DB row
                        conn = sqlite3.connect(DB_PATH)
                        c = conn.cursor()
                        c.execute("DELETE FROM segments WHERE id=?", (seg_id,))
                        conn.commit()
                        conn.close()

                        st.success(f"Deleted segment {seg_id}")
                        st.rerun()
                    
                    try:
                        idx = bucket_names.index(bucket)
                    except ValueError:
                        idx = 0
                    new_bucket = st.selectbox("Bucket", options=bucket_names, index=idx, key=f"bucket{seg_id}")
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
                
                if use_enhanced_player:
                    video_html = create_enhanced_video_player(seg_path, f"video{seg_id}")
                    st.components.v1.html(video_html, height=500)
                else:
                    # Use streamlit's video player for single column
                    st.video(str(seg_path))
                
                # Edit controls
                col1, col2 = st.columns([3, 1])
                with col1:
                    new_notes = st.text_input("Notes", value=notes or "", key=f"notes{seg_id}")
                with col2:
                    try:
                        idx = bucket_names.index(bucket)
                    except ValueError:
                        idx = 0
                    new_bucket = st.selectbox("Bucket", options=bucket_names, index=idx, key=f"bucket{seg_id}")
                
                if st.button("Update", key=f"update{seg_id}"):
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute("UPDATE segments SET bucket=?, notes=? WHERE id=?", (new_bucket, new_notes, seg_id))
                    conn.commit()
                    conn.close()
                    st.success("Updated segment.")
                    st.rerun()
                
                st.divider()

def main():
    st.sidebar.title("📂 Recordings")
    page = st.sidebar.radio("Navigate", ["Segment", "Browse"])
    init_db()
    if page == "Segment":
        segment_page()
    else:
        browse_page()

if __name__ == "__main__":
    main()