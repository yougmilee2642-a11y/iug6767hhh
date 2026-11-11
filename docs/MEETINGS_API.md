# CallWise Meetings — API contract (MVP)

Legacy MVP ownership (current roles and contracts are appended below). Owner of backend: Claude (`meetings/` package, `scripts/seed_meetings_demo.py`, `demo/meetings/`, `tests/test_meetings*.py`).
Owner of frontend + voice meeting mode: Codex (`static/meetings.html|js|css`, nav link in `static/index.html`,
`services/dual_asr.py`, `services/local_speech.py`, `/api/transcribe` in `app.py`, `tests/test_meeting_voice*.py`, browser smoke).
Do not edit the other side's files; if you need a change there, write it in `docs/MEETINGS_HANDOFF.md`.

All endpoints are JSON, prefix `/api/meet`. Errors: `{"detail": "русский текст", "code": "machine_code"}`.
- 401 `not_authenticated` — no demo-user session.
- 404 `not_found` — resource missing **or not accessible** (never reveal existence to another user).
- 422 validation, 409 conflict, 503 `model_unavailable` / `model_invalid_reply` / `model_timeout` (local LLM problem; data is kept, user may retry).

Page: `GET /meetings` serves `static/meetings.html` (route added by backend).

## Auth (demo users, server-side checks on every endpoint)
Cookie `cw_meet_user` (httponly, samesite=strict, signed).
- `POST /api/meet/login` `{login, password}` → `{user}`
- `POST /api/meet/logout`
- `GET /api/meet/me` → `{user: {id, login, name, role}}` or 401
- `GET /api/meet/users` → `{users: [{id, login, name}]}`
Demo users: `irina` / `irina-demo` — «Ирина Власова, руководитель проекта» (sees the launch meeting + its 3 documents);
`petr` / `petr-demo` — «Пётр Смирнов, подрядчик» (sees only his own meeting «Синк по дизайну» and doc «Гайд по бренду»; must NOT see launch materials).

## Documents
- `POST /api/meet/documents` multipart: `file` (.txt/.docx/.pdf text, ≤ 5 MB), optional `meeting_id`, optional `share_with` (comma-separated user ids). → `{document}`
- `GET /api/meet/documents` → `{documents: [Document]}` (only accessible)
- `GET /api/meet/documents/{id}` → `{document, fragments: [Fragment]}`
- `GET /api/meet/documents/{id}/download` → original file
- `GET /api/meet/fragments/{fragment_id}` → `{fragment}` (open citation in source)
- `GET /api/meet/search?q=...` → `{results: [Fragment & {snippet}]}` (only accessible)

Document: `{id, title, filename, kind: "txt"|"docx"|"pdf", owner_id, fragments_count, created_at}`
Fragment: `{id: "F12", document_id, document_title, idx, location: "стр. 2, фрагмент 3", text}`

## Meetings
- `POST /api/meet/meetings` `{title, topic, scheduled_at?: "2026-11-12T10:00", participants: ["Ирина Власова","Анна Ковалёва",...], access_user_ids?: [ids]}` → `{meeting}`
- `GET /api/meet/meetings` → `{meetings: [Meeting]}`
- `GET /api/meet/meetings/{id}` → `{meeting, documents: [Document], utterances: [Utterance], prep: Prep|null, protocol: Protocol|null, tasks: [Task]}`
- `PATCH /api/meet/meetings/{id}` partial meeting fields
- `POST /api/meet/meetings/{id}/documents` `{document_id}` attach existing accessible doc; `DELETE .../documents/{document_id}` detach

Meeting: `{id, title, topic, scheduled_at, participants: [str], owner_id, access_user_ids, speaker_map: {label: name}, created_at}`

## Preparation
- `POST /api/meet/meetings/{id}/prepare` → `{prep}` (local LLM, chunked over attached accessible docs)

Prep: `{status: "ok"|"insufficient_data", brief: [Claim], agenda: [Claim], questions: [Claim], gaps: [str], generated_at, model}`
Claim: `{text, citations: [{fragment_id, quote, verified: true}]}` — only verified citations are returned; claims without
verified citation are dropped from brief or moved to `gaps`. Agenda/questions may have empty citations.

## Transcript
- `PUT /api/meet/meetings/{id}/transcript` `{text}` — pasted text; lines like `Ирина: ...`, `[00:12] Анна: ...`, or plain lines (speaker `Говорящий ?`). Replaces transcript. → `{utterances}`
- `POST /api/meet/meetings/{id}/utterances` `{text, speaker_label?: "Говорящий 1", source: "voice"|"manual", start_ms?}` → `{utterance}` (append, used by live recording)
- `PATCH /api/meet/utterances/{id}` `{text?, speaker_label?}` → `{utterance}` (keeps `original_text`)
- `DELETE /api/meet/utterances/{id}`
- `GET /api/meet/utterances/{id}` → `{utterance, meeting_title}` (open quote in source)
- `PUT /api/meet/meetings/{id}/speakers` `{speaker_map: {"Говорящий 1": "Анна Ковалёва"}}` → `{meeting, utterances}`

Utterance: `{id: "U5"-style string id, meeting_id, idx, speaker_label, speaker (resolved name), text, original_text, edited: bool, source, start_ms}`

## Protocol
- `POST /api/meet/meetings/{id}/protocol/draft` → `{protocol}` (local LLM, chunked; replaces unconfirmed draft items, keeps confirmed ones)
- `PUT /api/meet/meetings/{id}/protocol` `{items: [ProtocolItem (editable fields)]}` → `{protocol}`
- `POST /api/meet/meetings/{id}/protocol/confirm` `{item_ids: [ids]}` → `{created: [Task], already_confirmed: [Task], protocol}` (idempotent; only kind=task items)

Protocol: `{meeting_id, status: "draft"|"partially_confirmed", items: [ProtocolItem], warnings: [str], generated_at, model}`
ProtocolItem: `{id, kind: "decision"|"proposal"|"task"|"open_question", text,
  outcome: "accepted"|"rejected"|"discussed"|null  (for proposals),
  assignee: str|null, assignee_status: "stated"|"unknown",
  due: "YYYY-MM-DD"|null, due_text: str|null, due_status: "stated"|"unknown",
  quotes: [{utterance_id, speaker, text, verified: bool}],
  confirmed: bool, confirmed_by: user_name|null, confirmed_at: iso|null, task_id: int|null, edited: bool}`
Decision and task items always have ≥1 verified quote; otherwise they are moved to `warnings` / demoted to open_question.
A rejected proposal is `kind: "proposal", outcome: "rejected"` — never a decision.

## Tasks board
- `GET /api/meet/tasks?status=` → `{tasks}` (from accessible meetings only)
- `PATCH /api/meet/tasks/{id}` → `409 confirmation_required` after ACL/role checks in Track 3. Use preview/confirm below.
- `POST /api/meet/meetings/{id}/next-agenda` `{create_meeting?: bool}` → `{agenda: [{task_id, text, assignee, due, status}], meeting?: Meeting}`

Task: `{id, text, assignee, assignee_status, due, due_status, status, meeting_id, meeting_title, protocol_item_id,
  source_quote: {utterance_id, text}, confirmed_by, confirmed_at, created_at}`

## Voice meeting mode (Codex)
`POST /api/transcribe` accepts extra form field `speaker_mode=all` → skips the primary-speaker filter, keeps all participants.
Response may include `segments: [{speaker_label, text, start_ms}]` if diarization is cheap; otherwise UI appends one utterance
with `speaker_label="Говорящий ?"` and the user maps speakers manually. Default mode unchanged.


# Track 3 current API extensions

Source of truth: integrated core cd06b4d, knowledge e03536b, UI 3dc09e7 and their handoffs.
All dates for new meetings/calendar have an offset or an explicit timezone; Europe/Minsk
is the business date zone. Errors are `{code, detail}` and may include fields; every
route carries X-Request-ID. Hidden objects → 404, available object with insufficient
capability → 403. Role never grants an object ACL.

| Endpoint | Request / behavior |
|---|---|
| GET /api/meet/me | user.access_role, user.capabilities plus top-level capabilities, role, timezone |
| POST /api/meet/tasks/{id}/preview | `{changes:{status?,assignee?,due?}}` → confirmation_id, expires_at, preview.before/after/version |
| POST /api/meet/tasks/{id}/confirm | `{confirmation_id,idempotency_key}` (8–80 chars key); repeat returns already_confirmed |
| POST /api/meet/confirmations/{id}/cancel | Cancel only the caller’s preview; target unchanged |
| GET /api/meet/calendar/participants | Synthetic directory `{participants:[{id,name}]}` |
| POST /api/meet/calendar/slots | participant_ids, range_start/end, duration_minutes, timezone, optional work_start/end/include_weekends; aware time, ≤31 days |
| POST /api/meet/calendar/preview | meeting_id, participant_ids, start_at, duration_minutes, timezone → preview incl. local invitation bodies |
| POST /api/meet/calendar/confirm | confirmation_id, idempotency_key → event, invitations, already_confirmed; provider mock |
| GET /api/meet/calendar/events and /outbox | Own/participating events and local_outbox_only; no actual mail |
| POST /api/meet/qa | `{question,meeting_id?}` → answer_id, status grounded/insufficient_data, claims/sources with kind/id/title/source_at/quote/locator |
| GET /api/meet/qa/{answer_id} | Caller’s answer; ACL and source integrity checked again; revoked → 404, stale → 409 |
| GET /api/meet/overview?as_of=... | Aware ISO cutoff; metrics with key/value/unit/formula/source, overdue_tasks, warnings; zero denominator=null |
| GET /api/meet/sources/{kind}/{source_id} | kind=task or metric, dynamic source resolver; fragments/utterances keep existing endpoints |
| POST /api/meet/feedback | target_type, target_id, rating useful/incorrect, optional meeting_id/answer_id/comment; target ACL checked |
| GET /api/meet/feedback | Caller’s feedback only |
| GET /api/meet/audit?scope=mine\|my_objects | Manager; response `{events,scope}`; my_objects includes safe denial metadata for owned objects |

Roles: reader can read/generate prep/view calendar/QA/overview/feedback within ACL;
manager additionally edits/shares/uploads/confirms/invites/audit. Detail and examples:
[core](track3-handoffs/claude.md), [knowledge](track3-handoffs/codex2.md).
Protocol adds kind=risk and summary with verified/needs_clarification, quotes and note.
Prep adds current-ACL open_tasks/task_questions from followup chain. Reader-generated
prep is personal and unsaved. Transcript change during draft → 409 stale_transcript.
Calendar/task stale/expired/cancelled/conflicting confirmations → 409.

Source dates: document source_at is upload timestamp, not authored date; transcript
citation shows meeting date, not a fabricated utterance timestamp. Overview as_of is
oldest included snapshot; generated_at is calculation time. Task counts use current
statuses even with historical as_of. Aggregated source IDs are opaque signed IDs,
never authorization. QA returns extractive verified claims; lexical retrieval is
limited and may refuse relevant synonyms. Model failures → 503 model_*; no hidden
cloud fallback. Remote inference/data boundaries are in the runbook.
