#!/usr/bin/env python3

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
import numpy as np
import torch

DEFAULT_MODEL = "ViT-B-32"
DEFAULT_PRETRAINED = "laion2b_s34b_b79k"

def parse_args():
    p = argparse.ArgumentParser(description="Search through Video Index")
    p.add_argument("query", help="text query")
    p.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"),
                   help = "The folder that holds the embedding, shot_id json and the database of shots.")
    p.add_argument("--mode", choices=["visual", "text", "both"], default="both", help="How the engine decides to search for answers to submit")
    p.add_argument("--k", type=int, default=20)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--pretrained", default=DEFAULT_PRETRAINED)
    return p.parse_args()

def load_index(data_dir):
    matrix = np.load(data_dir / "embeddings.npy")
    connection = sqlite3.connect(data_dir /"shots.db")

    with open(data_dir / "shot_ids.json") as f:
        shot_ids = json.load(f)
    assert matrix.shape == (len(shot_ids), 512), "Embedding and shot_id's aren't matching"

    return(matrix, shot_ids, connection)

def load_encoder(model_name, pretrained, device):
    import open_clip
    
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
    model = model.to(device).eval()
    tokenizer = open_clip.get_tokenizer(model_name)
    return model, tokenizer 

def encode_text(query, model, tokenizer, device):
    tokens = tokenizer([query]).to(device)
    with torch.no_grad():
        encode = model.encode_text(tokens)
        encode /= encode.norm(dim = -1, keepdim = True)
    return encode.squeeze(0).cpu().numpy().astype("float32")

def visual_search(qvec, matrix, k):
    scores = matrix @ qvec
    top_score = np.argsort(scores)[::-1][:k]
    return[(int(i), float(scores[i])) for i in top_score]

def text_search(db, query, shot_ids, k):
    words = [w for w in query.split() if w]
    if not words:
        return []
    match_query = " OR ".join(f'"{w}"' for w in words)

    rows = db.execute(
        "SELECT shot_id, bm25(transcripts) FROM transcripts "
        "WHERE transcripts MATCH ? ORDER BY bm25(transcripts) LIMIT ?",
        (match_query, k),
    ).fetchall()

    row_of = {sid: i for i, sid in enumerate(shot_ids)}
    return [(row_of[sid], -score) for sid, score in rows if sid in row_of]

def fuse_rrf(rank_lists, k=60, top=None):
    scores = {}
    for ranking in rank_lists:
        for rank, row in enumerate(ranking, start=1):
            scores[row] = scores.get(row, 0.0) + 1.0 / (k + rank)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ranked[:top]

def shot_information(db, shot_id):
    row = db.execute(
        "SELECT video_id, start_ms, end_ms FROM shots WHERE shot_id = ?",
        (shot_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Unknown Shot: {shot_id}")
    return row

def print_results(results, shot_ids, db):
    for rank, (row, score) in enumerate(results, start=1):
        shot_id = shot_ids[row]
        video_id, start_ms, end_ms = shot_information(db, shot_id)
        print(f"{rank:>3} {score:.3f}, {shot_id} video={video_id} {start_ms}-{end_ms} ms")

def main():
    args = parse_args()
    data_dir = Path(args.data_dir)
    matrix, shot_ids, db = load_index(data_dir)

    t0 = time.perf_counter()
    visual, text = [], []

    if args.mode in ("visual", "both"):
        model, tok = load_encoder(args.model, args.pretrained, "auto")
        device = next(model.parameters()).device
        qvec = encode_text(args.query, model, tok, device)
        visual = visual_search(qvec, matrix, 200)

    if args.mode in ("text", "both"):
        text = text_search(db, args.query, shot_ids, 200)

    if args.mode == 'both':
        visual_rows = [row for row, _ in visual]
        text_rows = [row for row, _ in text]
        results = fuse_rrf([visual_rows, text_rows], top=args.k)
    else:
        results = visual or text

    print(f"took {(time.perf_counter() - t0) * 1000:.0f} ms")
    print_results(results[: args.k], shot_ids, db)

if __name__ == "__main__":
    main()