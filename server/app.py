import os
import re
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query 
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from server import search_clip as sc
from server.dres_client import DRESClient
import time

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
VIDEO_DIR = Path(os.environ.get("VIDEO_DIR", "video"))
THUMB_DIR = Path(os.environ.get("THUMB_DIR", "thumb"))
WEB_DIR = Path(os.environ.get("WEB_DIR", "web"))

state = {}

@asynccontextmanager
async def lifespan(app):
    matrix, shot_ids, db = sc.load_index(DATA_DIR)
    model, token = sc.load_encoder(sc.DEFAULT_MODEL, sc.DEFAULT_PRETRAINED, "auto")
    state.update(
        matrix=matrix, shot_ids=shot_ids, db=db, model=model, tok=token, device=next(model.parameters()).device,
        dres=(DRESClient(
            os.environ.get("DRES_URL", "https://csc1103.interactivevideoretrieval.com"),
            os.environ["DRES_USER"], os.environ["DRES_PASS"],
        )if os.environ.get("DRES_USER") and os.environ.get("DRES_PASS") else None),
    )
    yield

app = FastAPI(lifespan=lifespan)
@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

def respond(query, results, limit, t0):
    """Group ranked shots into segments, cut to `limit` and build the JSON reply."""
    segments = sc.group_results(results, state["shot_ids"], state["db"])
    return {
        "query": query,
        "took_ms": int((time.perf_counter() - t0) * 1000),
        "results": segments_to_json(segments[:limit]),
    }

def segments_to_json(segments):
    db = state["db"]
    output= []
    
    for segment in segments:
        mid = segment["shot_ids"][len(segment["shot_ids"]) // 2]
        output.append({
            "video_id": segment["video_id"],
            "shot_ids": segment["shot_ids"],
            "start_ms": segment["start_ms"],
            "end_ms" : segment["end_ms"],
            "score": segment["score"],
            "thumb_url": f"/thumb/{mid}.png",
            "video_url": f"/video/{segment['video_id']}.mp4",
            "text": sc.text_retrival(db, mid)
        })
    return output

@app.get("/api/search")
def api_search(q: str, mode: str = "both", video_id: str | None = None, limit: int= Query(60, ge=1, le=500), w: float | None = Query(None, ge=0, le=1)):
    if w is not None:
        mode = 'visual' if w >= 0.999 else "text" if w <= 0.001 else "both"
    if mode not in ("visual", "text", "both") or not q.strip():
        raise HTTPException(400, "Error on query")
    
    t0 = time.perf_counter()
    matrix, shot_ids, db = state["matrix"], state["shot_ids"], state["db"]
    visual, text = [], []
    rows = sc.rows_of_video(db, video_id, shot_ids) if video_id else None
    
    if mode in ("visual", "both"):
        qvec = sc.encode_text(q, state["model"], state["tok"], state["device"])
        visual = sc.visual_search(qvec, matrix, 200, rows=rows)
    
    if mode in ("text", "both"):
        text = sc.text_search(db, q, shot_ids, 200, video_id=video_id)
    
    if mode == "both":
        visuals = [row for row, _ in visual]
        texts = [row for row, _ in text]
        weights = [w, 1 - w] if w is not None else None
        results = sc.fuse_rrf([visuals, texts], top=200, weights=weights)
    else:
        results = visual or text
        
    return respond(q, results, limit, t0)

@app.get("/thumb/{shot_id}.png")
def thumb(shot_id):
    match = re.fullmatch(r"shot(\d+)_(\d+)", shot_id)
    if not match:
        raise HTTPException(400, "Error on the Shot ID, check again")
    zip_path = THUMB_DIR / f"{match.group(1)}.zip"
    if not zip_path.exists():
        raise HTTPException(404, "no thumbnails for that video")
    with zipfile.ZipFile(zip_path) as zf:
        try:
            data = zf.read(f"{shot_id}.png")
        except KeyError:
            raise HTTPException(404, "no such thumbnail")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/video/{video_id}.mp4")
def video(video_id: str):
    if not re.fullmatch(r"\d+", video_id):
        raise HTTPException(400, "bad video_id")
    path = VIDEO_DIR / f"{video_id}.mp4"
    if not path.exists():
        raise HTTPException(404, "no such video")
    return FileResponse(path, media_type="video/mp4")

@app.get("/api/similar/{shot_id}")
def api_similarity(shot_id, limit: int = 60):
    t0 = time.perf_counter()
    try:
        results = sc.similarities(shot_id, state["matrix"], state["shot_ids"], 200)
    except KeyError:
        raise HTTPException(404, "unknown shot")

    return respond(shot_id, results, limit, t0)

@app.get("/api/video/{video_id}/shots")
def api_video_shots(video_id):
    if not re.fullmatch(r"\d+", video_id):
        raise HTTPException(400, "Bad Video_ID")
    rows = state["db"].execute(
        "SELECT shot_id, start_ms, end_ms FROM shots WHERE video_id = ? ORDER BY n",
        (video_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(404, "Video Unknown")
    return{
        "video_id": video_id,
        "shots": [
            {"shot_id": sid, "start_ms": s, "end_ms": e, "thumb_url": f"/thumb/{sid}.png"} for sid, s, e in rows
        ]
    }
    
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
    if body.start_ms < 0 or body.end_ms < body.start_ms:
        raise HTTPException(400, "bad time range")
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