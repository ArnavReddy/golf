#!/usr/bin/env python3
import datetime
import sqlite3
import shutil
from pathlib import Path

# --- Paths ---
DATA_DIR    = Path("data")
DB_PATH     = DATA_DIR / "metadata.db"
EXPORT_ROOT = Path("export")

def main():
    EXPORT_ROOT.mkdir(exist_ok=True)
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

    # Pull each segment's relative filename and its bucket name (stored as text)
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
        if filter_date:
            print(f"No segments found for recordings imported on {filter_date}.")
        else:
            print("No segments found in the database.")
        return

    for rel_path, bucket_name in rows:
        src = DATA_DIR / rel_path
        if not src.exists():
            print(f"⚠️  Missing file, skipping: {src}")
            continue

        # Make a folder per bucket
        dest_dir = EXPORT_ROOT / bucket_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        print(f"Copied {src} → {dest}")

    if filter_date:
        zip_date = filter_date
    else:
        zip_date = datetime.date.today().isoformat()
    zip_base = f"export_{zip_date}"
    # make the zip (will create export_{date}.zip in cwd)
    zip_path = shutil.make_archive(zip_base, "zip", root_dir=str(EXPORT_ROOT))
    print(f"\n✅ Export complete! Zipped to {zip_path}")

if __name__ == "__main__":
    main()
