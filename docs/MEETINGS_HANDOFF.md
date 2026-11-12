# Track 3 handoff notice

The legacy notes below predate Track 3. Current handoffs: [Claude](track3-handoffs/claude.md),
[Codex 2](track3-handoffs/codex2.md), [Codex 1](track3-handoffs/codex1.md),
[Codex 3](track3-handoffs/codex3.md). Current release evidence: [status](track3-release/STATUS.md).
Use the isolated runbook; do not reset the working data/ database for smoke.


## Claude → Codex (backend ready)
- Backend is committed: `meetings/` package, routes `/api/meet/*` and `GET /meetings` are live (registered via `install_meetings(app)` in app.py — those 2 lines in app.py are Claude's; keep them when you commit app.py).
- Demo data: `.venv\Scripts\python scripts\seed_meetings_demo.py` (users irina/irina-demo, petr/petr-demo). Paste text: `demo/meetings/transcript.txt`; upload files in `demo/meetings/`.
- Extra fields beyond contract: meeting GET returns `hidden_documents` (count of attached docs the user cannot read) — show «N документов недоступны вам». Prep citations carry `document_title`, `location`, `document_id`. Task `due_text` may be set while `due` is null (vague date) — show due_text.
- `due_status: "stated"` may come with `due: null` + `due_text` — render as «Срок: <due_text> (дата не распознана)».
- Backend tests: `tests/test_meetings.py` (11 passing). Model: qwen2.5:7b via MEETINGS_MODEL (default), protocol draft can take 30–120 s — show progress.

## Codex status

- Implemented the Russian meetings UI for demo sign-in, meeting creation, document upload/attachment, prep claims and gaps, editable transcripts and utterances, speaker mapping, protocol editing/confirmation, per-meeting and global task boards, document search, and citation source panels with downloads. User and document content is rendered with DOM text nodes and textContent.
- Voice capture reuses the PCM AudioWorklet and WAV encoder, submits 15-second chunks to /api/transcribe with speaker_mode=all, and keeps recognized text editable before saving it as a voice utterance. Meeting capture requires a signed-in meeting user, access to the meeting, and an explicit all-participants consent attestation. When diarized segments are absent, the speaker label defaults to Говорящий ? for manual mapping. The service defaults to the existing primary-speaker filter and skips it in all mode.
- Added fake route, meeting-authorization, consent, and speaker-filter routing tests in tests/test_meeting_voice_mode.py. `node --check static/meetings.js` passed. The Node test runner passed all 66 existing JavaScript tests. `git diff --check` passed.
- Python tests could not run: `.venv\Scripts\python.exe` attempts to start `C:\Users\leha\AppData\Local\Programs\Python\Python311\python.exe`, which is denied by the current execution environment; `py` reports no installed Python. The local HTTP smoke could not run because no server was listening at `127.0.0.1:8000`.
- Limitation: the real browser/API path and local model operations still need a smoke run in an environment that can execute the project Python environment and serve the app.
