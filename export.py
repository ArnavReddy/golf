#!/usr/bin/env python3
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
    # Pull each segment's relative filename and its bucket name (stored as text)
    c.execute("SELECT filename, bucket FROM segments")
    rows = c.fetchall()
    conn.close()

    if not rows:
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

    print("\n✅ Export complete!")

if __name__ == "__main__":
    main()
