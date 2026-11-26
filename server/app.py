import os
import re
import threading
import time
import zipfile
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from server.search_clip import Engine, CANDIDATES
from server.dres_client import DRESClient

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
VIDEO_DIR = Path(os.environ.get("VIDEO_DIR", "video"))
THUMB_DIR = Path(os.environ.get("THUMB_DIR", "thumb"))
WEB_DIR = Path(os.environ.get("WEB_DIR", "web"))

state = {}

# Open thumbnail zips are kept around: re-opening one means re-reading its central directory on every request.
ZIP_CACHE_SIZE = 128
_zips, _zips_lock = OrderedDict(), threading.Lock()

def open_zip(path):
    key = str(path)
    with _zips_lock:
        zf = _zips.get(key)
        if zf is not None:
            _zips.move_to_end(key)
            return zf
    zf = zipfile.ZipFile(path)          # raises FileNotFoundError if the video has no thumbnails
    with _zips_lock:
        _zips[key] = zf
        _zips.move_to_end(key)
        while len(_zips) > ZIP_CACHE_SIZE:
            _zips.popitem(last=False)   # dropped, not closed: a request still using it keeps its own reference
    return zf

@asynccontextmanager
async def lifespan(app):
    engine = Engine(DATA_DIR)           # loads the index onto the GPU and warms it up
    dres = (DRESClient(
        os.environ.get("DRES_URL", "https://csc1103.interactivevideoretrieval.com"),
        os.environ["DRES_USER"], os.environ["DRES_PASS"],
    ) if os.environ.get("DRES_USER") and os.environ.get("DRES_PASS") else None)
    if dres is not None:
        try:
            dres.login()                # so the first submit does not pay for a login round trip
        except Exception as exc:
            print(f"DRES pre-login failed ({exc}); it will be retried on the first submit")
    state.update(engine=engine, dres=dres)
    yield

app = FastAPI(lifespan=lifespan)
@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

def respond(query, results, limit, t0, timings):
    """Group ranked shots into segments, cut to `limit` and build the JSON reply (with per-stage timings)."""
    engine = state["engine"]
    t = time.perf_counter()
    segments = engine.group(results)
    timings["group"] = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    payload = engine.segments_to_json(segments[:limit])
    timings["lookup"] = (time.perf_counter() - t) * 1000
    timings["total"] = (time.perf_counter() - t0) * 1000
    server_timing = ", ".join(f"{name};dur={ms:.1f}" for name, ms in timings.items())
    return JSONResponse(
        {"query": query, "took_ms": int(timings["total"]),
         "timings": {name: round(ms, 1) for name, ms in timings.items()}, "results": payload},
        headers={"Server-Timing": server_timing})

@app.get("/api/search")
def api_search(q: str, mode: str = "both", video_id: str | None = None, limit: int = Query(60, ge=1, le=500), w: float | None = Query(None, ge=0, le=1)):
    if w is not None:
        mode = "visual" if w >= 0.999 else "text" if w <= 0.001 else "both"
    if mode not in ("visual", "text", "both") or not q.strip():
        raise HTTPException(400, "Error on query")

    engine = state["engine"]
    if video_id is not None and not engine.has_video(video_id):
        raise HTTPException(404, "Video Unknown")
    t0 = time.perf_counter()
    results, timings = engine.search(q, mode, video_id, w if mode == "both" else None, CANDIDATES)
    return respond(q, results, limit, t0, timings)

@app.get("/thumb/{shot_id}.png")
def thumb(shot_id):
    match = re.fullmatch(r"shot(\d+)_(\d+)", shot_id)
    if not match:
        raise HTTPException(400, "Error on the Shot ID, check again")
    try:
        zf = open_zip(THUMB_DIR / f"{match.group(1)}.zip")
    except FileNotFoundError:
        raise HTTPException(404, "no thumbnails for that video")
    try:
        data = zf.read(f"{shot_id}.png")
    except KeyError:
        raise HTTPException(404, "no such thumbnail")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/video/{video_id}.mp4")
def video(video_id: str):
    if not re.fullmatch(r"\d+", video_id):
        raise HTTPException(400, "bad video_id")
    path = VIDEO_DIR / f"{video_id}.mp4"
    if not path.exists():
        raise HTTPException(404, "no such video")
    return FileResponse(path, media_type="video/mp4")

@app.get("/api/similar/{shot_id}")
def api_similarity(shot_id: str, limit: int = Query(60, ge=1, le=500)):
    t0 = time.perf_counter()
    try:
        results, timings = state["engine"].similar(shot_id, CANDIDATES)
    except KeyError:
        raise HTTPException(404, "unknown shot")
    return respond(shot_id, results, limit, t0, timings)

@app.get("/api/video/{video_id}/shots")
def api_video_shots(video_id):
    if not re.fullmatch(r"\d+", video_id):
        raise HTTPException(400, "Bad Video_ID")
    shots = state["engine"].video_shots(video_id)
    if not shots:
        raise HTTPException(404, "Video Unknown")
    return {"video_id": video_id, "shots": shots}

class Submission(BaseModel):
    evaluation_id : str | None = None
    video_id: str
    start_ms: int
    end_ms: int

@app.post("/api/submit")
def api_submit(body: Submission):
    dres = state.get("dres")
    if dres is None:
        raise HTTPException(503, "Username/Password for DRES hasn't been set")
    if body.start_ms < 0 or body.end_ms < body.start_ms:
        raise HTTPException(400, "Error with Time Ranges")

    evaluation_id = body.evaluation_id or os.environ.get("DRES_EVALUATION_ID")
    if not evaluation_id:
        raise HTTPException(400, "no evaluation_id (send one, or set DRES_EVALUATION_ID)")
    try:
        result = dres.submit(evaluation_id, body.video_id, body.start_ms, body.end_ms)
    except Exception as exc:
        raise HTTPException(502, f"DRES error: {exc}")
    reply = result.get("response") or {}
    return {
        **result,  # keeps http_status, accepted and response which web/js/submit.js reads
        "status": "ok" if result.get("accepted") else "error",
        "verdict": reply.get("submission"),
        "message": reply.get("description", ""),
    }

if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html = True), name="web")
