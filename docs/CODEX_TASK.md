# Task for Codex — CallWise Meetings MVP (frontend + voice meeting mode)

You work in parallel with Claude in `D:\projects\Callwise-local` (FastAPI + vanilla JS, local Ollama/STT, git repo).
Read `docs/MEETINGS_API.md` first — it is the contract and lists file ownership. Claude builds the backend
(`meetings/` package, routes `/api/meet/*`, `GET /meetings` page route, demo data, seed script). Do NOT edit Claude's files.
If you need a backend change, append a note to `docs/MEETINGS_HANDOFF.md` (create if missing) and work around it.
Commit your work regularly with `git add <your files> && git commit -m "codex: ..."` (only your files; never `git add -A`).
Language of UI: Russian. Do not break existing CallWise screens/tests.

## Your scope
1. **UI page `static/meetings.html` + `static/meetings.js` + `static/meetings.css`** (vanilla JS ES modules, reuse look of
   `static/style.css`/`product.css` where reasonable; no external CDN). Flow:
   - Login screen for demo users (irina/irina-demo, petr/petr-demo), current user + logout in header.
   - Meetings list + "Новая встреча" (title, topic, date, participants, access to users).
   - Meeting screen with tabs/steps: **1 Подготовка** (attach/upload TXT/DOCX/PDF, list attached docs, "Сформировать справку" →
     brief/agenda/questions with citation chips; "Недостаточно данных" state + gaps shown explicitly),
     **2 Материалы** (textarea paste transcript → save; utterance list with inline edit of text and speaker; speaker mapping
     "Говорящий 1 → Анна"; live recording button using meeting voice mode, see 3),
     **3 Протокол** (draft button; items grouped: Решения / Предложения (with outcome badge «отклонено»/«принято»/«обсуждалось») /
     Поручения / Открытые вопросы; each with quote chips; editable text/assignee/due; unknown assignee/due shown as a visible
     red/amber badge «Ответственный не назван» / «Срок не назван»; checkboxes + "Подтвердить выбранные"; confirmed items show
     «Подтвердил: Ирина Власова, 11.11.2026 12:03» and are not re-confirmable),
     **4 Задачи** (local task board columns open / in_progress / done, change status, source meeting link, "Повестка следующей
     встречи" button using next-agenda).
   - Global "Задачи" board and document search box.
   - **Every citation chip opens the source**: fragment (`GET /api/meet/fragments/{id}`) or utterance (`GET /api/meet/utterances/{id}`)
     in a side panel/modal showing the full fragment/utterance with the quote highlighted, plus a link to download doc.
   - Model errors (503 with code model_*) → clear message + "Повторить", nothing lost. Long ops → spinner, disable button.
   - Render all user/document content with textContent (no innerHTML of data) — documents are untrusted data.
   - Add nav item «Встречи» to `static/index.html` sidebar linking to `/meetings` (minimal change).
2. **Voice meeting mode**: `/api/transcribe` in `app.py` (only that endpoint function) + `services/dual_asr.py` /
   `services/local_speech.py`: new form field `speaker_mode` (`primary` default = current behaviour, `all` = keep every speaker,
   skip `filter_speaker`). Optionally return `segments` with per-speaker labels from the already-loaded pyannote segmentation
   if it is cheap and reliable; otherwise no segments. Reuse existing mic capture code (`static/app.js`, `pcm-capture-worklet.js`,
   `incremental-stt.js`) in meetings.js: record chunks (e.g. on pause / every ~15 s), send with `speaker_mode=all`, append via
   `POST /api/meet/meetings/{id}/utterances` with `source: "voice"`. Recognised text must be editable before/after save.
   Add pytest tests for speaker_mode routing using fakes (no real models in unit tests) and keep existing voice tests green.
3. **Checks**: run `.venv\Scripts\python -m pytest -q -x tests` for the parts you touch plus `node --test` style JS tests if
   present; once Claude's backend responds on `/api/meet/*` (check with the running server or TestClient), do a browser/HTTP
   smoke of the whole demo path. Write results to `docs/MEETINGS_HANDOFF.md` under "Codex status".

## Until the backend is ready
Build the UI against the contract; you may add a tiny mock (`static/meetings-mock.js`, only enabled with `?mock=1`) for
development. Poll for `meetings/api.py` existing in the repo to integrate.

## Done when
UI covers the full path documented above against the real backend, voice mode tests pass, existing tests you touched pass,
and you've written a short status (what works, what's limited) in `docs/MEETINGS_HANDOFF.md`.
