#!/usr/bin/env python3

import argparse
import re
import sqlite3
from pathlib import Path

TIME = r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})"
CUE_TIME = re.compile(TIME + r"\s*-->\s*" + TIME)
# Whisper writes these labels when there is no speech; they would only add noise to the text index.
NON_SPEECH = {"music", "applause", "laughter", "silence", "singing", "inaudible", "blank audio"}

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, help="shots.db built by build_shots_db.py")
    p.add_argument("--srt-dir", required=True, help="Folder holding a <v3cId>.srt for each video")
    return p.parse_args()

def to_ms(h, m, s, ms):
    return((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, '0')[:3])

# Parses a single SRT file and returns a list of (start_ms, end_ms, text) tuples
def parse_srt(srt_path):
    raw = Path(srt_path).read_text(encoding="utf-8-sig", errors="replace")
    cues = []
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = CUE_TIME.search(line)
            if m:
                g = m.groups()
                text = " ".join(l.strip() for l in lines[i + 1:]).strip()
                cues.append((to_ms(*g[:4]), to_ms(*g[4:]), text))
                break
    return cues

def is_speech(text):
    cleaned = re.sub(r"[^a-z0-9]+", "", text.lower()).strip()
    return bool(cleaned) and cleaned not in NON_SPEECH

def build(db_path, srt_dir):
    connection= sqlite3.connect(db_path)
    connection.executescript("""
        DROP TABLE IF EXISTS transcripts;
        CREATE VIRTUAL TABLE transcripts USING fts5(shot_id UNINDEXED, video_id UNINDEXED, text);
    """)
    videos = [r[0] for r in connection.execute("SELECT DISTINCT video_id FROM shots ORDER BY video_id")]

    missing, n_cues, n_dropped, n_rows = [], 0, 0, 0
    for v in videos:
        srt = Path(srt_dir) / f"{v}.srt"
        if not srt.exists():
            missing.append(v)
            continue
        
        all_cues = parse_srt(srt)
        cues = [c for c in all_cues if is_speech(c[2])]
        n_cues += len(cues)
        n_dropped += len(all_cues) - len(cues)
        
        shots = connection.execute("SELECT shot_id, start_ms, end_ms FROM shots WHERE video_id=? ORDER BY n", (v,)).fetchall()
        rows = []
        for shot_id, start_ms, end_ms in shots:
            texts = [t for cs, ce, t in cues if cs < end_ms and ce > start_ms]
            if texts:
                rows.append((shot_id, v, " ".join(texts)))
        connection.executemany("INSERT INTO transcripts VALUES(?, ?, ?)", rows)
        n_rows += len(rows)
    connection.commit()
    connection.close()
    print(f"{len(videos) - len(missing)} of {len(videos)} videos had a transcript file ({len(missing)} missing)")
    print(f"{n_cues} speech cues kept, {n_dropped} non-speech cues dropped")
    print(f"{n_rows} shots have transcript text")


if __name__ == "__main__":
    args = parse_args()
    build(args.db, args.srt_dir)