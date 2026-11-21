#!/usr/bin/env python3

import argparse
import csv
import sqlite3
from pathlib import Path

def parse_args():
    p = argparse.ArgumentParser()
    
    p.add_argument("--msb-dir", required=True, help="Folder that holds .tsv files")
    p.add_argument("--db", default="shots.db", help="SQLite file output")
    p.add_argument("--meta", help="Metadata of each video")
    p.add_argument("--first-index", type=int, default=1, help="Number of first shot in each video")

    return p.parse_args()

def load_shots(connection, msb_dir, first_index):
    connection.executescript("""
        DROP TABLE IF EXISTS shots;
        CREATE TABLE shots (
            shot_id     TEXT PRIMARY KEY,
            video_id    TEXT NOT NULL,
            n           INTEGER NOT NULL,
            start_frame INTEGER,
            end_frame   INTEGER NOT NULL,
            start_ms    INTEGER NOT NULL,
            end_ms      INTEGER NOT NULL
        );
        CREATE INDEX index_shots_video ON shots(video_id, n);
    """)
    files = sorted(Path(msb_dir).glob("*.tsv"))
    if not files:
        raise SystemExit(f"Files in {msb_dir} are missing/not found")

    total, warning_count = 0, 0
    for f in files:
        video_id = f.stem
        rows = []
        with open(f, newline="", encoding="utf-8") as file_handle:
            reader = csv.reader(file_handle, delimiter="\t")
            header = [h.strip().lower() for h in next(reader)]
            index = {name: header.index(name) for name in ("startframe", "starttime", "endframe", "endtime")}

            for n, row in enumerate((r for r in reader if r and any(c.strip() for c in r)), start=first_index):
                sf, ef = int(row[index["startframe"]]), int(row[index["endframe"]])
                st, et = float(row[index["starttime"]]), float(row[index["endtime"]])
                start_ms, end_ms = round(st * 1000), round(et * 1000) # Adjusting the structure of the time for DRES to work
                if end_ms < start_ms:
                    warning_count += 1
                    print(f"{f.name} shot number {n} has wrong start end times") # Checker in case there's an error in the tsv files
                rows.append((f"shot{video_id}_{n}", video_id, n, sf, ef, start_ms, end_ms))
        
        connection.executemany("INSERT INTO shots VALUES(?,?,?,?,?,?,?)", rows)
        total += len(rows)
    connection.commit()
    print(f"Loaded {total} shots from {len(files)} videos. {warning_count} tsv's had errors.")

def load_metadata(connection, meta_csv):
    with open(meta_csv, newline="", encoding="utf-8") as file_handle:
        reader = csv.DictReader(file_handle)
        columns = reader.fieldnames
        connection.execute("DROP TABLE IF EXISTS videos")
        connection.execute("CREATE TABLE videos (" + ", ".join(f'"{c}" TEXT' for c in columns) + ")")
        placeholders = ",".join("?" * len(columns))
        connection.executemany(f"INSERT INTO videos VALUES ({placeholders})", ([row[c] for c in columns] for row in reader))
    connection.commit()
    n = connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    print(f"Loaded {n} rows into videos (columns: {', '.join(columns)})")

if __name__ == "__main__":
    args = parse_args()
    connection = sqlite3.connect(args.db)
    load_shots(connection, args.msb_dir, args.first_index)
    if args.meta:
        load_metadata(connection, args.meta)
    connection.close()