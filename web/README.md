Served by the backend from the same origin: from the repo root run `uvicorn server.app:app --port 8000`
(set `DATA_DIR`, `VIDEO_DIR`, `THUMB_DIR`, `DRES_USER`, `DRES_PASS` first), then open http://localhost:8000/.
Enter the DRES **evaluation ID** in the top bar; the backend requires it ahead of submissions.

## Backend contract used (server/app.py)
`GET /api/search?q&mode&video_id&limit`, `GET /api/similar/{shot_id}`, `GET /api/video/{id}/shots`,
`POST /api/submit {evaluation_id, video_id, start_ms, end_ms}`, media at `/thumb/<shot_id>.png` and `/video/<id>.mp4`.
Results are grouped segments; the UI keys each one by its middle shot. Not implemented by the backend, so not in the UI:
image search, search weight `w`, DRES task status. Weight isn't really used by the end user, despite its integration.
