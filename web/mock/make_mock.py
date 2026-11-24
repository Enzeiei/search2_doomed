"""[B] Generate realistic fixtures from data/shots.db. Run from the repo root:
    python web/mock/make_mock.py
Writes search.json, similar.json, video_shots.json, status.json, submit_*.json here.
Thumbnails: extract a few <v3cId>.zip files into web/mock/thumbs/<video>/ (git-ignored, it is collection data).
ASSUMPTION: shots(shot_id, video_id, n, start_ms, end_ms) and videos(video_id, title) as described in the brief.
Adjust column names if prep/ used different ones.
"""
import json, sqlite3, random, pathlib
out = pathlib.Path(__file__).parent
db = sqlite3.connect("data/shots.db"); db.row_factory = sqlite3.Row

def result(r, score):
    # [A] The real backend should return exactly this shape.
    return dict(shot_id=r["shot_id"], video_id=r["video_id"], n=r["n"],
                start_ms=r["start_ms"], end_ms=r["end_ms"], score=score,
                thumb_url=f"mock/thumbs/{r['video_id']}/shot{r['video_id']}_{r['n']}.png",
                video_url=f"mock/videos/{r['video_id']}.mp4",   # [A] real: /media/video/<id>.mp4 with Range
                video_title=None, text="")

rows = db.execute("SELECT * FROM shots ORDER BY RANDOM() LIMIT 100").fetchall()
json.dump([result(r, round(random.random(), 3)) for r in rows], open(out/"search.json","w"), indent=1)
json.dump([result(r, round(random.random(), 3)) for r in rows[:40]], open(out/"similar.json","w"), indent=1)

vid = rows[0]["video_id"]
vs = db.execute("SELECT * FROM shots WHERE video_id=? ORDER BY n", (vid,)).fetchall()
json.dump([result(r, 0) for r in vs], open(out/"video_shots.json","w"), indent=1)

# [A] Proposed submit/status shapes; edit when the real ones are agreed.
json.dump({"status":"ok","verdict":"CORRECT","message":"Submission correct"}, open(out/"submit_ok.json","w"))
json.dump({"status":"ok","verdict":"WRONG","message":"Submission incorrect"}, open(out/"submit_wrong.json","w"))
json.dump({"status":"ok","verdict":"DUPLICATE","message":"Duplicate submission"}, open(out/"submit_dup.json","w"))
json.dump({"error":"No active task"}, open(out/"submit_none.json","w"))
json.dump({"logged_in":True,"task_active":True,"task_name":"practice-kis-1","time_left_s":240}, open(out/"status.json","w"))
print("wrote fixtures; first video:", vid)
