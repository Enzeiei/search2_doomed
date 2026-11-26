#!/usr/bin/env python3
"""
search_clip.py - search engine core.

Everything the hot path needs lives in memory, so a query never scans SQLite or rebuilds a lookup table:

  * embeddings: one (N, 512) tensor, fp16 on the GPU (fp32 on CPU)
  * row -> video / start / end: arrays aligned with the embedding rows
  * video -> row range: shots are stored ordered by (video_id, n), so a video is a contiguous slice
  * transcripts: FTS5 is only used for ranking; text is fetched by rowid in one batched lookup
  * per-thread read-only SQLite connections, LRU caches for text embeddings and fused results
"""

import argparse
import json
import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch

DEFAULT_MODEL = "ViT-B-32"
DEFAULT_PRETRAINED = "laion2b_s34b_b79k"
CANDIDATES = 200          # candidates taken from each ranker before fusion / grouping

# Words that would make an FTS5 "a OR b OR ..." query match most of the transcript table and force
# BM25 to score all of it. If a query is made only of these, the original words are used instead.
STOPWORDS = frozenset("""
a an and are as at be but by for from has have he her his i if in into is it its me my no not of on or our
she so that the their them then there these they this to us was we were what when where which who will with
you your am do does did how
""".split())


def parse_args():
    p = argparse.ArgumentParser(description="Search through Video Index")
    p.add_argument("query", help="text query")
    p.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"),
                   help="The folder that holds the embedding, shot_id json and the database of shots.")
    p.add_argument("--mode", choices=["visual", "text", "both"], default="both",
                   help="How the engine decides to search for answers to submit")
    p.add_argument("--k", type=int, default=20)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--pretrained", default=DEFAULT_PRETRAINED)
    return p.parse_args()


class LRU:
    """Tiny thread-safe LRU cache."""

    def __init__(self, size):
        self.size, self.data, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            value = self.data.get(key)
            if value is not None:
                self.data.move_to_end(key)
            return value

    def put(self, key, value):
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)


def fts_query(query):
    words = re.findall(r"\w+", query.lower())
    kept = [w for w in words if w not in STOPWORDS] or words
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(kept))


# Ranking algorithm to merge the rankings of visual and text search.
def fuse_rrf(rank_lists, k=60, top=None, weights=None):
    if weights is None:
        weights = [1.0] * len(rank_lists)
    scores = {}
    for weight, ranking in zip(weights, rank_lists):
        for rank, row in enumerate(ranking, start=1):
            scores[row] = scores.get(row, 0.0) + weight / (k + rank)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ranked[:top]


class Engine:
    def __init__(self, data_dir, model_name=DEFAULT_MODEL, pretrained=DEFAULT_PRETRAINED, device="auto"):
        data_dir = Path(data_dir)
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.on_gpu = device.startswith("cuda")
        self.dtype = torch.float16 if self.on_gpu else torch.float32

        self.db_path = data_dir / "shots.db"
        self._local = threading.local()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fts")
        self._enc_lock = threading.Lock()
        self.text_cache = LRU(1024)        # normalised query -> text embedding
        self.result_cache = LRU(256)       # (query, mode, ...) -> fused [(row, score)]
        self.video_shots_cache = LRU(512)  # video_id -> shot list

        self._load_index(data_dir)
        self._load_encoder(model_name, pretrained)
        self._warm_up()

    # ---------------------------------------------------------------- loading
    def db(self):
        """One read-only connection per thread (a shared connection serialises every request)."""
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            con.execute("PRAGMA mmap_size=2147483648")
            con.execute("PRAGMA cache_size=-16384")
            self._local.con = con
        return con

    def _load_index(self, data_dir):
        matrix = np.load(data_dir / "embeddings.npy")
        with open(data_dir / "shot_ids.json") as f:
            self.shot_ids = json.load(f)
        self.n = len(self.shot_ids)
        assert matrix.shape == (self.n, 512), "Embedding and shot_id's aren't matching"
        self.row_of = {sid: i for i, sid in enumerate(self.shot_ids)}
        self.matrix = torch.from_numpy(matrix).to(self.device, dtype=self.dtype).contiguous()
        del matrix

        # Per-row shot information, aligned with the embedding rows.
        self.video_of = [None] * self.n
        self.start_ms = np.zeros(self.n, dtype=np.int64)
        self.end_ms = np.zeros(self.n, dtype=np.int64)
        db = self.db()
        for sid, vid, start, end in db.execute("SELECT shot_id, video_id, start_ms, end_ms FROM shots"):
            i = self.row_of.get(sid)
            if i is not None:
                self.video_of[i] = vid
                self.start_ms[i], self.end_ms[i] = start, end
        missing = sum(v is None for v in self.video_of)
        assert missing == 0, f"{missing} embedded shots are missing from shots.db"

        # video -> list of contiguous (lo, hi) row runs. Normally exactly one run per video.
        self.video_runs = {}
        prev = None
        for i, vid in enumerate(self.video_of):
            if vid != prev:
                self.video_runs.setdefault(vid, []).append([i, i + 1])
                prev = vid
            else:
                self.video_runs[vid][-1][1] = i + 1

        # Transcript rowid <-> embedding row, so FTS hits and text lookups never touch string ids.
        self.tx_rowid = np.full(self.n, -1, dtype=np.int64)
        try:
            pairs = db.execute("SELECT rowid, shot_id FROM transcripts").fetchall()
            self.has_text = True
        except sqlite3.OperationalError:
            pairs, self.has_text = [], False
        self.tx_row = np.full(max((r for r, _ in pairs), default=0) + 1, -1, dtype=np.int64)
        for rowid, sid in pairs:
            i = self.row_of.get(sid)
            if i is not None:
                self.tx_rowid[i] = rowid
                self.tx_row[rowid] = i

    def _load_encoder(self, model_name, pretrained):
        import open_clip
        self.model, _, _ = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=self.device,
            precision="fp16" if self.on_gpu else "fp32")
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(model_name)

    def _warm_up(self):
        """Compile CUDA kernels and pull the FTS pages into the OS cache before the first real query."""
        self.search("a person talking to the camera", "both")

    def has_video(self, video_id):
        return video_id in self.video_runs

    # ---------------------------------------------------------------- encoding
    def encode_text(self, query):
        key = " ".join(query.lower().split())
        cached = self.text_cache.get(key)
        if cached is not None:
            return cached
        with self._enc_lock, torch.inference_mode():
            tokens = self.tokenizer([query]).to(self.device)
            vec = self.model.encode_text(tokens)
            vec = (vec / vec.norm(dim=-1, keepdim=True)).squeeze(0).to(self.dtype).clone()
        self.text_cache.put(key, vec)
        return vec

    # ---------------------------------------------------------------- rankers
    def visual_search(self, qvec, k, video_id=None):
        """Top-k rows by cosine similarity. Optionally restricted to one video (a slice, not a copy)."""
        with torch.inference_mode():
            lo, gather = 0, None
            if video_id is None:
                scores = self.matrix @ qvec
            else:
                runs = self.video_runs.get(video_id)
                if not runs:
                    return []
                if len(runs) == 1:
                    lo, hi = runs[0]
                    scores = self.matrix[lo:hi] @ qvec
                else:
                    gather = torch.cat([torch.arange(a, b) for a, b in runs]).to(self.device)
                    scores = self.matrix[gather] @ qvec
            values, ids = torch.topk(scores, min(k, scores.shape[0]))
            ids = gather[ids] if gather is not None else ids + lo
            return list(zip(ids.tolist(), values.float().tolist()))

    def text_search(self, query, k, video_id=None):
        if not self.has_text:
            return []
        match = fts_query(query)
        if not match:
            return []
        sql = "SELECT rowid, bm25(transcripts) FROM transcripts WHERE transcripts MATCH ?"
        params = [match]
        if video_id is not None:
            sql += " AND video_id = ?"
            params.append(video_id)
        sql += " ORDER BY bm25(transcripts) LIMIT ?"
        params.append(k)
        out = []
        for rowid, score in self.db().execute(sql, params):
            row = int(self.tx_row[rowid]) if rowid < len(self.tx_row) else -1
            if row >= 0:
                out.append((row, -score))
        return out

    def similar(self, shot_id, k=CANDIDATES):
        """Rows most similar to a shot (excluding itself). Raises KeyError for an unknown shot."""
        key = ("similar", shot_id, k)
        cached = self.result_cache.get(key)
        if cached is not None:
            return cached, {"cache": 0.0}
        row = self.row_of[shot_id]
        t = time.perf_counter()
        results = [(r, s) for r, s in self.visual_search(self.matrix[row], k + 1) if r != row][:k]
        self.result_cache.put(key, results)
        return results, {"visual": (time.perf_counter() - t) * 1000}

    @staticmethod
    def _timed(fn, *args):
        t = time.perf_counter()
        return fn(*args), (time.perf_counter() - t) * 1000

    def search(self, query, mode="both", video_id=None, w=None, k=CANDIDATES):
        """Returns ([(row, score)], timings_ms). Text ranking runs in a worker thread while the GPU does the rest."""
        key = ("search", query.strip(), mode, video_id, w, k)
        cached = self.result_cache.get(key)
        if cached is not None:
            return cached, {"cache": 0.0}

        timings, visual, text, future = {}, [], [], None
        if mode in ("text", "both"):
            future = self._pool.submit(self._timed, self.text_search, query, k, video_id)
        if mode in ("visual", "both"):
            t = time.perf_counter()
            qvec = self.encode_text(query)
            timings["encode"] = (time.perf_counter() - t) * 1000
            visual, timings["visual"] = self._timed(self.visual_search, qvec, k, video_id)
        if future is not None:
            text, timings["text"] = future.result()

        if mode == "both":
            t = time.perf_counter()
            weights = [w, 1 - w] if w is not None else None
            results = fuse_rrf([[r for r, _ in visual], [r for r, _ in text]], top=k, weights=weights)
            timings["fuse"] = (time.perf_counter() - t) * 1000
        else:
            results = visual or text
        self.result_cache.put(key, results)
        return results, timings

    # ---------------------------------------------------------------- results -> segments
    def group(self, results, gap_ms=1000, max_len=10000):
        """Merge neighbouring shots of one video into segments. Pure in-memory, no SQL."""
        items = sorted(((self.video_of[r], int(self.start_ms[r]), int(self.end_ms[r]), score, r)
                        for r, score in results), key=lambda it: (it[0], it[1]))
        segments = []
        for video_id, start, end, score, row in items:
            prev = segments[-1] if segments else None
            if (prev and prev["video_id"] == video_id and start - prev["end_ms"] <= gap_ms
                    and max(prev["end_ms"], end) - prev["start_ms"] <= max_len):
                prev["end_ms"] = max(prev["end_ms"], end)
                prev["score"] = max(prev["score"], score)
                prev["rows"].append(row)
            else:
                segments.append({"video_id": video_id, "start_ms": start, "end_ms": end,
                                 "score": score, "rows": [row]})
        segments.sort(key=lambda seg: seg["score"], reverse=True)
        return segments

    def texts_for_rows(self, rows):
        """Transcript text for each row (None if none), in one primary-key lookup instead of one scan each."""
        rowids = [int(self.tx_rowid[r]) for r in rows]
        wanted = [x for x in rowids if x >= 0]
        if not wanted:
            return [None] * len(rows)
        sql = f"SELECT rowid, text FROM transcripts WHERE rowid IN ({','.join('?' * len(wanted))})"
        found = dict(self.db().execute(sql, wanted).fetchall())
        return [found.get(x) for x in rowids]

    def segments_to_json(self, segments):
        mids = [seg["rows"][len(seg["rows"]) // 2] for seg in segments]
        texts = self.texts_for_rows(mids)
        out = []
        for seg, mid, text in zip(segments, mids, texts):
            out.append({
                "video_id": seg["video_id"],
                "shot_ids": [self.shot_ids[r] for r in seg["rows"]],
                "start_ms": seg["start_ms"],
                "end_ms": seg["end_ms"],
                "score": seg["score"],
                "thumb_url": f"/thumb/{self.shot_ids[mid]}.png",
                "video_url": f"/video/{seg['video_id']}.mp4",
                "text": text,
            })
        return out

    def video_shots(self, video_id):
        cached = self.video_shots_cache.get(video_id)
        if cached is not None:
            return cached
        rows = self.db().execute(
            "SELECT shot_id, start_ms, end_ms FROM shots WHERE video_id = ? ORDER BY n", (video_id,)).fetchall()
        shots = [{"shot_id": sid, "start_ms": s, "end_ms": e, "thumb_url": f"/thumb/{sid}.png"}
                 for sid, s, e in rows]
        if shots:
            self.video_shots_cache.put(video_id, shots)
        return shots


def print_segments(segments):
    for rank, seg in enumerate(segments, start=1):
        print(f"{rank:>3} {seg['score']:.3f} video={seg['video_id']} "
              f"{seg['start_ms']}-{seg['end_ms']} ms ({len(seg['rows'])} shots)")


def main():
    args = parse_args()
    engine = Engine(args.data_dir, args.model, args.pretrained)
    t0 = time.perf_counter()
    results, timings = engine.search(args.query, args.mode, k=CANDIDATES)
    segments = engine.group(results)
    print(f"took {(time.perf_counter() - t0) * 1000:.0f} ms  "
          + " ".join(f"{k}={v:.1f}" for k, v in timings.items()))
    print_segments(segments[:args.k])


if __name__ == "__main__":
    main()
