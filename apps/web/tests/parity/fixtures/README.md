# Captured API fixtures

Captured from the REAL backend (`uv run uvicorn vera_api.app:create_app --factory --port 8210`,
VERA_ENV=synthetic, after `POST /api/demo/reset`) at backend commit `main` merged into ticket/VER-012-F1
(merge of 1f11546 with main; see `git log`). Parity specs fulfil `/api/*` with these bodies so pixels are
compared on real data shapes. Re-capture after a backend contract change; do not hand-edit values.
