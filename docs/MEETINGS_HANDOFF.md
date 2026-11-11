
## Claude → Codex (backend ready)
- Backend is committed: `meetings/` package, routes `/api/meet/*` and `GET /meetings` are live (registered via `install_meetings(app)` in app.py — those 2 lines in app.py are Claude's; keep them when you commit app.py).
- Demo data: `.venv\Scripts\python scripts\seed_meetings_demo.py --reset` (users irina/irina-demo, petr/petr-demo). Paste text: `demo/meetings/transcript.txt`; upload files in `demo/meetings/`.
- Extra fields beyond contract: meeting GET returns `hidden_documents` (count of attached docs the user cannot read) — show «N документов недоступны вам». Prep citations carry `document_title`, `location`, `document_id`. Task `due_text` may be set while `due` is null (vague date) — show due_text.
- `due_status: "stated"` may come with `due: null` + `due_text` — render as «Срок: <due_text> (дата не распознана)».
- Backend tests: `tests/test_meetings.py` (11 passing). Model: qwen2.5:7b via MEETINGS_MODEL (default), protocol draft can take 30–120 s — show progress.
