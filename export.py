#!/usr/bin/env python3
import datetime
import sqlite3
import shutil
from pathlib import Path
import argparse

# --- Paths ---
DATA_DIR    = Path("data")
DB_PATH     = DATA_DIR / "metadata.db"
EXPORT_ROOT = Path("export")
SITE_ROOT   = Path("docs")

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Golf Swings Review</title>
  <style>
    body {{ font-family: sans-serif; margin: 1rem; }}
    select {{ font-size: 1rem; margin-bottom: 1rem; }}
    .video-grid {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
    .clip {{ width: 320px; }}
    video {{ width: 100%; height: auto; border: 1px solid #ccc; }}
    .hidden {{ display: none; }}
  </style>
</head>
<body>
  <h1>Golf Swing Clips</h1>
  <label for="bucketFilter">Filter by bucket:</label>
  <select id="bucketFilter">
    <option value="__all__">All</option>
    {options}
  </select>
  <div class="video-grid">
    {videos}
  </div>
  <script>
    const filter = document.getElementById('bucketFilter');
    filter.addEventListener('change', () => {{
      const sel = filter.value;
      document.querySelectorAll('.clip').forEach(div => {{
        div.classList.toggle('hidden',
          sel !== '__all__' && div.dataset.bucket !== sel
        );
      }});
    }});
  </script>
</body>
</html>"""

def main():
    EXPORT_ROOT.mkdir(exist_ok=True)
    SITE_ROOT.mkdir(exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 1) Fetch all distinct import dates
    c.execute("SELECT DISTINCT date(imported_at) FROM recordings ORDER BY date(imported_at)")
    dates = [row[0] for row in c.fetchall() if row[0] is not None]

    if not dates:
        print("No recordings found in the database.")
        return

    # 2) Print menu
    print("Select a date to export segments for recordings imported on that day:")
    print("  0) All dates")
    for i, d in enumerate(dates, start=1):
        print(f"  {i}) {d}")

    # 3) Prompt for choice
    choice = None
    while choice is None:
        sel = input(f"Enter number (0–{len(dates)}): ").strip()
        if sel.isdigit():
            idx = int(sel)
            if 0 <= idx <= len(dates):
                choice = idx
        if choice is None:
            print("❌  Invalid choice, try again.")

    # 4) Determine filter_date
    if choice == 0:
        filter_date = None
        print("→ Exporting for all dates")
    else:
        filter_date = dates[choice - 1]
        print(f"→ Exporting for recordings imported on {filter_date}")

    # 5) Pull segments
    if filter_date:
        query = """
            SELECT s.filename, s.bucket
              FROM segments AS s
              JOIN recordings AS r
                ON s.recording_id = r.id
             WHERE date(r.imported_at) = ?
        """
        params = (filter_date,)
    else:
        query = "SELECT filename, bucket FROM segments"
        params = ()
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    if not rows:
        print("No segments found for that date." if filter_date else "No segments at all.")
        return

    # 6) Copy into export/<bucket> and also into site/videos/<bucket>
    for rel_path, bucket_name in rows:
        src = DATA_DIR / rel_path
        if not src.exists():
            print(f"⚠️  Missing file, skipping: {src}")
            continue

        for root in (EXPORT_ROOT, SITE_ROOT / 'videos'):
            dest_dir = root / bucket_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_dir / src.name)
            print(f"Copied {src} → {root / bucket_name / src.name}")

    # 7) Zip up the export folder
    zip_date = filter_date or datetime.date.today().isoformat()
    zip_base = f"export_{zip_date}"
    zip_path = shutil.make_archive(zip_base, "zip", root_dir=str(EXPORT_ROOT))
    print(f"\n✅ Export complete! Zipped to {zip_path}")

    # 8) Generate site/index.html
    buckets = sorted({b for (_, b) in rows})
    options_html = "\n    ".join(f'<option value="{b}">{b}</option>' for b in buckets)

    videos_html = []
    for rel_path, bucket_name in rows:
        name = Path(rel_path).name
        # point src to "videos/<bucket>/<filename>"
        videos_html.append(
            f'<div class="clip" data-bucket="{bucket_name}">'
            f'<video src="videos/{bucket_name}/{name}" controls preload="metadata"></video>'
            f'<div>{bucket_name} / {name}</div>'
            f'</div>'
        )
    with open(SITE_ROOT / "index.html", "w") as f:
        f.write(INDEX_HTML.format(options=options_html,
                                  videos="\n    ".join(videos_html)))
    print(f"\n✅ Static site generated in `{SITE_ROOT}/`")

    print("\n→ To publish on GitHub Pages:")
    print("  1) Push to GitHub, then in your repo Settings → Pages → Source select `docs/` branch.")
    print("  2) Your site will be live at `https://<your-user>.github.io/<your-repo>/`.")

if __name__ == "__main__":
    main()
