#!/usr/bin/env python3

import argparse
import json
import os
import sys
import requests

DEFAULT_URL = "https://csc1103.interactivevideoretrieval.com/"

class DRESClient:
    def __init__(self, base_url=None, username=None, password=None, timeout=20):
        self.base_url = (base_url or os.environ.get("DRES_URL", DEFAULT_URL)).rstrip("/")
        self.username = username or os.environ.get("DRES_USER")
        self.password = password or os.environ.get("DRES_PASS")
        self.timeout = timeout
        self.http = requests.Session()
        self.logged_in = False

    def login(self):
        if not self.username or not self.password:
            raise RuntimeError("Username and password neds to be set...")
        r = self.http.post(f"{self.base_url}/api/v2/login",
            json={"username": self.username, "password": self.password},
            timeout=self.timeout)
        r.raise_for_status()
        self.logged_in = True
        return r.json()

    def _post_submission(self, evaluation_id, body):
        return self.http.post(f"{self.base_url}/api/v2/submit/{evaluation_id}", json=body, timeout=self.timeout)

    def submit(self, evaluation_id, video_id, start_ms, end_ms, collection=None):
        if not self.logged_in:
            self.login()
        answer = {"mediaItemName": str(video_id), "start": int(start_ms), "end": int(end_ms)}
        body = {"answerSets": [{"answers": [answer]}]}

        r = self._post_submission(evaluation_id, body)
        if r.status_code == 401:
            self.login()
            r = self._post_submission(evaluation_id, body)
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        return {"http_status": r.status_code, "accepted": r.status_code in (200, 202), "response" : data}


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Checks the validity of credentials")
    s = sub.add_parser("submit", help="Submits a shot to DRES")
    s.add_argument("--eval", required=True, help="evaluation/run ID")
    s.add_argument("--video", required=True, help="Video ID (00031, 00036, etc)")
    s.add_argument("--start", type=int, required=True, help="Start time in milliseconds")
    s.add_argument("--end", type=int, required=True, help="End time in milliseconds")
    s.add_argument("--collection", help="media collection name, optional")
    args = p.parse_args()

    client = DRESClient()
    try:
        if args.command == "login":
            print(json.dumps(client.login(), indent = 2))
        else:
            result = client.submit(args.eval, args.video, args.start, args.end, args.collection)
            print(json.dumps(result, indent = 2))
    except (requests.RequestException, RuntimeError) as e:
        sys.exit(f"DRES error: {e}")


if __name__ == "__main__":
    main()