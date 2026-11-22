#!/usr/bin/env python3
import argparse
import io
import json
import os
import sqlite3
import time
import zipfile
from pathlib import Path
import numpy as np

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, help="SQLite file output")
    p.add_argument("--thumbnails", required=True, help="Folder holding a <v3cId>.zip for each video")
    p.add_argument("--cache-dir", default="data/embed_cache", help="Folder to cache per-video, makes runs resumable")
    p.add_argument("--out", default="data/embeddings")
    p.add_argument("--ids-out", default="data/shot_ids.json")
    p.add_argument("--model", default="ViT-B-32", help="OpenCLIP model name")
    p.add_argument("--pretrained", default="laion2b_s34b_b79k", help="OpenCLIP pretrained tag") # This is the model we chose to use for the assignment.
    p.add_argument("--device", default="auto", help="auto, cpu or cuda")
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--limit", type=int, help="only embed the first N videos still to do, only for a test run")
    p.add_argument("--merge-only", action="store_true", help="skip embedding, just merge the cache files")
    return p.parse_args()

def video_ids(db_path):
    connection = sqlite3.connect(db_path)
    rows = connection.execute("SELECT DISTINCT video_id FROM shots ORDER BY video_id").fetchall()
    connection.close()
    return [r[0] for r in rows]

def shot_order(db_path):
    connection = sqlite3.connect(db_path)
    rows = connection.execute("SELECT shot_id FROM shots ORDER BY video_id, n").fetchall()
    connection.close()
    return [r[0] for r in rows]

# Turns each shot name into a number for numerical sorting (shot00031_1.png -> 1)
def shot_number(shot_name):
    return int(Path(shot_name).stem.rsplit('_', 1)[1])

# Embeds all png's in a video's thumbnail zip, and returns a list of shot ids and a numpy array of embeddings
def embed_video(zip_path, encode, batch_size):
    from PIL import Image
    ids, vectors = [], []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = sorted((n for n in zf.namelist() if n.lower().endswith('.png')), key=shot_number)
        for i in range(0, len(names), batch_size):
            chunk =  names[i:i+batch_size]
            images = [Image.open(io.BytesIO(zf.read(n))).convert('RGB') for n in chunk]
            vectors.append(encode(images))
            ids.extend(Path(n).stem for n in chunk)
    return ids, np.concatenate(vectors)

# Loads the OpenCLIP model and returns a function that encodes a list of PIL images into normalized numpy arrays
def build_encoder(model_name, pretrained, device):
    import torch
    import open_clip

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
    model = model.to(device).eval()

    @torch.no_grad()
    def encode(images):
        batch = torch.stack([preprocess(image) for image in images]).to(device)
        with torch.autocast(device_type=device.split(':')[0], enabled=device.startswith("cuda")):
            features = model.encode_image(batch)
        features /= features.norm(dim=-1, keepdim=True)
        return features.float().cpu().numpy()
    return encode

def embed_all_videos(args):
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    thumbnails_dir = Path(args.thumbnails)

    to_do, no_zip = [], []
    for v in video_ids(args.db):
        if (cache_dir / f"{v}.npz").exists():
            continue
        if not (thumbnails_dir / f"{v}.zip").exists():
            no_zip.append(v)
            continue
        to_do.append(v)
    if args.limit:
        to_do = to_do[:args.limit]
    print(f"{len(to_do)} videos to embed, {len(no_zip)} skipped because their thumbnail zip is not downloaded yet")
    if not to_do:
        return

    encode = build_encoder(args.model, args.pretrained, args.device)
    start = time.time()
    completed_shots = 0
    for k, v in enumerate(to_do, 1):
        ids, vectors = embed_video(thumbnails_dir / f"{v}.zip", encode, args.batch_size)
        temp = cache_dir / f"{v}.tmp.npz"
        np.savez(temp, ids=np.array(ids), vectors=vectors)
        os.replace(temp, cache_dir / f"{v}.npz")
        completed_shots += len(ids)
        rate = completed_shots / (time.time() - start)
        print(f"[{k}/{len(to_do)}] {v}: {len(ids)} shots  ({rate:.1f} shots/s)", flush=True)

# Merges all the per-video cache files and builds the files our search engine will load.
def merge_cache(db_path, cache_dir, out_path, ids_out_path):
    
    all_ids, all_vectors = [], []
    for f in sorted(Path(cache_dir).glob("*.npz")):
   
        if f.name.endswith(".tmp.npz"):
            continue
        data = np.load(f)
        all_ids.extend(data["ids"])
        all_vectors.append(data["vectors"])

    if not all_vectors:
        raise SystemExit(f"No cache files found in {cache_dir}")
    
    matrix = np.concatenate(all_vectors)
    pos = {sid: i for i, sid in enumerate(all_ids)}
    order = shot_order(db_path)
    ids = [s for s in order if s in pos]
    matrix = matrix[[pos[s] for s in ids]]
    np.save(out_path, matrix.astype(np.float32))
    with open(ids_out_path, "w", encoding="utf-8") as fh:
        json.dump(ids, fh)
    print(f"Saved {matrix.shape[0]} x {matrix.shape[1]} embeddings to {out_path} and the ids to {ids_out_path}")


if __name__ == "__main__":
    args = parse_args()
    if not args.merge_only:
        embed_all_videos(args)
    merge_cache(args.db, args.cache_dir, args.out, args.ids_out)