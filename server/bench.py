"""
bench.py - measures query latency of the running backend for Table 2 of the report.

Usage (start the server first, in another terminal):
    Ubuntu:   python3 bench.py --base http://localhost:8000
    Windows:  python bench.py --base http://localhost:8000
"""

import argparse
import math
import platform
import statistics
import time

import requests

QUERIES = [
    "a dog on a beach", "a person playing guitar", "cooking in a kitchen",
    "a crowd at a concert", "a car driving on a road", "people walking in a city street",
    "a man giving a speech", "a close up of a flower", "children playing football",
    "a woman talking to the camera", "welcome to the channel", "thanks for watching",
    "how to make", "in this video", "a mountain landscape", "a bowl of food",
    "someone riding a bicycle", "a baby laughing", "an aerial view of a city", "a person typing on a laptop",
]


def percentile(values, p):
    ordered = sorted(values)
    index = max(0, math.ceil(p / 100 * len(ordered)) - 1)
    return ordered[index]


def summarise(label, times):
    if not times:
        print(f"{label:<28} no successful runs")
        return
    print(f"{label:<28} median {statistics.median(times):>7.0f} ms   "
        f"p95 {percentile(times, 95):>7.0f} ms   runs {len(times)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--reps", type=int, default=3, help="repeats per query")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    s = requests.Session()
    print(f"machine: {platform.platform()} | python {platform.python_version()}")
    print(f"queries: {len(QUERIES)} x {args.reps} reps, limit={args.limit}\n")

    # warm-up (not counted): first requests can be slower
    for _ in range(3):
        s.get(f"{args.base}/api/search", params={"q": QUERIES[0], "mode": "both", "limit": args.limit}, timeout=60)

    # Results are cached server-side, so only rep 0 of each query is a cold lookup; later reps add a word to
    # change the cache key and stay cold too. 'server' is the backend's own took_ms (now the full request);
    # 'round trip' is measured here and also includes the network and JSON parsing.
    shots_for_similar = []
    for mode in ("visual", "text", "both"):
        server, rtt, stages = [], [], {}
        for q in QUERIES:
            for rep in range(args.reps):
                query = q if rep == 0 else f"{q} {'again ' * rep}".strip()   # rep 0 = cold, later reps differ slightly
                t = time.perf_counter()
                r = s.get(f"{args.base}/api/search",
                        params={"q": query, "mode": mode, "limit": args.limit}, timeout=60)
                elapsed = (time.perf_counter() - t) * 1000
                if r.status_code != 200:
                    continue
                body = r.json()
                server.append(body["took_ms"])
                rtt.append(elapsed)
                for name, ms in body.get("timings", {}).items():
                    stages.setdefault(name, []).append(ms)
                if mode == "both" and body["results"] and len(shots_for_similar) < len(QUERIES):
                    shots_for_similar.append(body["results"][0]["shot_ids"][0])
        summarise(f"{mode} query (server)", server)
        summarise(f"{mode} query (round trip)", rtt)
        for name, values in stages.items():
            if name != "total":
                summarise(f"  {name}", values)

    server, rtt = [], []
    for sid in shots_for_similar:
        for _ in range(args.reps):
            t = time.perf_counter()
            r = s.get(f"{args.base}/api/similar/{sid}", params={"limit": args.limit}, timeout=60)
            elapsed = (time.perf_counter() - t) * 1000
            if r.status_code == 200:
                server.append(r.json()["took_ms"])
                rtt.append(elapsed)
    summarise("more like this (server)", server)
    summarise("more like this (round trip)", rtt)


if __name__ == "__main__":
    main()