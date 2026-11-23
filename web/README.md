# web/ (Partner B)
Open via the backend (same origin) or `python -m http.server` in web/ with `?mock=1`.
1. `python web/mock/make_mock.py` (from repo root) to create fixtures.
2. Extract a few thumbnail zips into `web/mock/thumbs/<video_id>/`.
3. Browse to `index.html?mock=1` (add `&fail=wrong|dup|none` to test submit failures).
Tags in code comments: [A] = depends on / assumed from Partner A's backend, [B] = our UI logic.
