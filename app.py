import streamlit as st
import os
import subprocess
import sqlite3
from pathlib import Path
import base64
import re
from datetime import datetime
import threading
import requests                # to fetch from our local server
from flask import Flask, request, jsonify

# --- Configuration ---
DATA_DIR        = Path("data")
RECORDINGS_DIR  = DATA_DIR / "recordings"
SEGMENTS_DIR    = DATA_DIR / "segments"
DB_PATH         = DATA_DIR / "metadata.db"
FLASK_PORT = 5001 

# --- Flask server to hold start/end in memory ---
flask_app = Flask(__name__)
# initialize with zeros; will be overwritten by slider's initial 'update' event
current_bounds = {"start": 0.0, "end": 0.0}

@flask_app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST"
    return resp

@flask_app.route("/update", methods=["POST"])
def update_bounds():
    data = request.get_json() or {}
    if "start" in data:
        current_bounds["start"] = float(data["start"])
    if "end" in data:
        current_bounds["end"]   = float(data["end"])
    return jsonify(success=True)

@flask_app.route("/current", methods=["GET"])
def get_current():
    return jsonify(current_bounds)

def run_flask():
    # disable reloader, run in background thread
    flask_app.run(port=FLASK_PORT, threaded=True, use_reloader=False)

# start Flask in the background
threading.Thread(target=run_flask, daemon=True).start()


# --- Helper functions & DB init ---
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
    names = [row[0] for row in c.fetchall()]
    conn.close()
    return names

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

# --- Streamlit App ---
def main():
    st.set_page_config(page_title="Slomo Golf Clip Manager", layout="wide")
    if "flask_thread" not in st.session_state:
        thread = threading.Thread(
            target=lambda: flask_app.run(
                port=FLASK_PORT, threaded=True, use_reloader=False
            ),
            daemon=True
        )
        thread.start()
        st.session_state["flask_thread"] = thread
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
        st.info("No recordings yet; upload a .mp4 file.")
        return

    selected = st.selectbox("Select a recording", recs, format_func=lambda p: p.name)
    duration, fps = get_video_info(selected)

    # Build the HTML + JS for video, slider, set/jump buttons
    video_id = "segment_video"
    video_uri = selected.resolve()
    html = create_simple_video_player(video_path=video_uri, video_id=video_id)
    html += f"""
    <!-- noUiSlider CSS & JS -->
    <link rel="stylesheet"
          href="https://cdnjs.cloudflare.com/ajax/libs/noUiSlider/14.7.0/nouislider.min.css"/>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/noUiSlider/14.7.0/nouislider.min.js"></script>

    <style>
      #rangeSlider {{ margin:12px 16px; }}
      .controls {{
        display:flex;
        gap:8px;
        align-items:center;
        margin-top:8px;
      }}
      .controls button {{
        padding:6px 12px;
        border:none;
        border-radius:4px;
        cursor:pointer;
        color:white;
        font-family:sans-serif;
      }}
      .start {{ background:#007bff; }}
      .end   {{ background:#28a745; }}
    </style>

    <script>
      // initial
      window.start = 0.0;
      window.end   = {duration:.2f};

      window.addEventListener('DOMContentLoaded', () => {{
        const videoEl  = document.getElementById('{video_id}');
        const sliderEl = document.getElementById('rangeSlider');

        const slider = noUiSlider.create(sliderEl, {{
          start: [0, {duration:.2f}],
          connect: true,
          range: {{ min: 0, max: {duration:.2f} }},
          step: 0.01,
          tooltips: [true, true],
          format: {{
            to: v => parseFloat(v).toFixed(2),
            from: v => parseFloat(v)
          }}
        }});

        // on every update, POST to our Flask
        slider.on('update', (values) => {{
          window.start = parseFloat(values[0]);
          window.end   = parseFloat(values[1]);
          fetch('http://localhost:{FLASK_PORT}/update', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ start: window.start, end: window.end }})
          }});
        }});

        // set from video
        window.setStartFromVideo = () => {{
          const t = videoEl.currentTime;
          slider.set([t, null]);
          fetch('http://localhost:{FLASK_PORT}/update', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ start: t }})
          }});
        }};
        window.setEndFromVideo = () => {{
          const t = videoEl.currentTime;
          slider.set([null, t]);
          fetch('http://localhost:{FLASK_PORT}/update', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ end: t }})
          }});
        }};

        // jump helpers (no POST needed)
        window.jumpToStart = () => {{ videoEl.currentTime = window.start; }};
        window.jumpToEnd   = () => {{ videoEl.currentTime = window.end; }};
      }});
    </script>

    <div id="rangeSlider"></div>

    <div class="controls">
      <button class="start" onclick="setStartFromVideo()">Set segment start</button>
      <button class="end"   onclick="setEndFromVideo()">Set segment end</button>
    </div>

    <div class="controls">
      <button class="start" onclick="jumpToStart()">↤ Jump to start</button>
      <button class="end"   onclick="jumpToEnd()">Jump to end ↦</button>
    </div>

    <script>
        window.addEventListener("load", () => {{
            Streamlit.setFrameHeight(document.documentElement.scrollHeight);
        }});
    </script>
    """

    # render it all in one iframe
    st.components.v1.html(html, height=1000)

    new_bucket = st.text_input("➕ Add a new bucket type", key="new_bucket")
    if st.button("Add bucket type"):
        if new_bucket.strip():
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO buckets(name) VALUES(?)", (new_bucket.strip(),))
            conn.commit()
            conn.close()
            st.success(f"Added bucket type: {new_bucket}")

    # Now when the user clicks Save, we fetch the latest from our Flask
    bucket_names = list_buckets()
    bucket = st.selectbox("Assign bucket", bucket_names)
    notes  = st.text_input("Notes (optional)")

    if st.button("Save Segment"):
        try:
            r = requests.get(f"http://localhost:{FLASK_PORT}/current", timeout=1.0)
            r.raise_for_status()
            data = r.json()
            start, end = data["start"], data["end"]
        except Exception:
            st.error("⚠️ Couldn't fetch segment bounds from local server.")
            return

        if start >= end:
            st.error("Start must be less than end.")
        else:
            # create segment
            segment_dir = SEGMENTS_DIR / selected.stem
            segment_dir.mkdir(parents=True, exist_ok=True)
            out_name = f"seg_{int(start*1000)}_{int(end*1000)}.mp4"
            out_path = segment_dir / out_name
            with st.spinner(f"Creating segment...from {start} to {end}"):
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

if __name__ == "__main__":
    main()