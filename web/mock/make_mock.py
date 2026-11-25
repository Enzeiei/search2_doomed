"""[B] Fixtures in the REAL backend shapes, built from data/shots.db. Run from the repo root:
    python web/mock/make_mock.py
Writes search.json, similar.json, video_shots/<id>.json, submit_*.json into web/mock/.
Thumbnails: extract the matching <video>.zip files into web/mock/thumbs/<video>/ (git-ignored, collection data).
Videos: put a few mp4s in web/mock/videos/<video>.mp4. Then open index.html?mock=1 (add &fail=wrong|indet|none|net).
"""
import json, random, sqlite3, pathlib
out = pathlib.Path(__file__).parent
(out / "video_shots").mkdir(exist_ok=True)
db = sqlite3.connect("data/shots.db"); db.row_factory = sqlite3.Row
cache = {}
def shots_of(v):
    if v not in cache:
        cache[v] = db.execute("SELECT shot_id, n, start_ms, end_ms FROM shots WHERE video_id=? ORDER BY n", (v,)).fetchall()
    return cache[v]

def segment(r):
    shots = shots_of(r["video_id"])
    i = next(k for k, s in enumerate(shots) if s["shot_id"] == r["shot_id"])
    span = shots[i:i + random.choice([1, 1, 2, 3])]          # some results are grouped, as in the real backend
    ids = [s["shot_id"] for s in span]; mid = ids[len(ids) // 2]
    v = r["video_id"]
    return {"video_id": v, "shot_ids": ids, "start_ms": span[0]["start_ms"], "end_ms": span[-1]["end_ms"],
            "score": round(random.random(), 3), "thumb_url": f"mock/thumbs/{v}/{mid}.png",
            "video_url": f"mock/videos/{v}.mp4", "text": None}

rows = db.execute("SELECT shot_id, video_id FROM shots ORDER BY RANDOM() LIMIT 60").fetchall()
segs = [segment(r) for r in rows]
json.dump({"query": "mock", "took_ms": 0, "results": segs}, open(out / "search.json", "w"), indent=1)
json.dump({"query": "mock", "took_ms": 0, "results": segs[:30]}, open(out / "similar.json", "w"), indent=1)
for v in {s["video_id"] for s in segs}:
    json.dump({"video_id": v, "shots": [{"shot_id": s["shot_id"], "start_ms": s["start_ms"], "end_ms": s["end_ms"],
               "thumb_url": f"mock/thumbs/{v}/{s['shot_id']}.png"} for s in shots_of(v)]},
              open(out / "video_shots" / f"{v}.json", "w"))

def dres(code, ok, body): return {"http_status": code, "accepted": ok, "response": body}
for name, data in {
    "submit_ok": dres(200, True, {"status": True, "submission": "CORRECT", "description": "Submission correct"}),
    "submit_wrong": dres(200, True, {"status": True, "submission": "WRONG", "description": "Submission incorrect"}),
    "submit_indet": dres(200, True, {"status": True, "submission": "INDETERMINATE", "description": "Submission received"}),
    "submit_none": dres(412, False, {"status": False, "description": "No active task"}),
}.items():
    json.dump(data, open(out / f"{name}.json", "w"))
print("wrote fixtures for", len({s['video_id'] for s in segs}), "videos")
