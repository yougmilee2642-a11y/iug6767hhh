"""Track 3 core: roles vs ACL, denial audit (survives rollback), AI audit trail, task preview/confirm,
open tasks in preparation, risks/summary, feedback, aware time and migrations of an old database."""
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from meetings import api as meet_api
from meetings import extract, llm, migrations, store
from test_meetings import DEMO, FakeLLM, env, login  # noqa: F401  (env is a fixture)


def audit_rows(action=None):
    with store.db() as connection:
        query, args = 'SELECT * FROM audit', []
        if action:
            query += ' WHERE action=?'
            args.append(action)
        return [store.audit_out(r) for r in connection.execute(query + ' ORDER BY id', args)]


def protocol_with_task(client, meeting_id):
    client.put(f'/api/meet/meetings/{meeting_id}/transcript',
               json={'text': (DEMO / 'transcript.txt').read_text(encoding='utf-8')})
    protocol = client.post(f'/api/meet/meetings/{meeting_id}/protocol/draft').json()['protocol']
    return protocol, next(i for i in protocol['items'] if 'оценку рисков' in i['text'])


def confirmed_task(client, meeting_id):
    _protocol, item = protocol_with_task(client, meeting_id)
    return client.post(f'/api/meet/meetings/{meeting_id}/protocol/confirm', json={'item_ids': [item['id']]}).json()['created'][0]


# ---------- roles ----------

def test_me_returns_role_and_capabilities_compatibly(env):
    irina, petr = login(env['app'], 'irina'), login(env['app'], 'petr')
    me = irina.get('/api/meet/me').json()
    assert me['user']['login'] == 'irina' and me['user']['role'] == 'Руководитель проекта'  # old fields kept
    assert me['user']['access_role'] == 'manager' and 'tasks.change' in me['capabilities']
    assert me['role']['key'] == 'manager' and me['timezone'] == 'Europe/Minsk'
    reader = petr.get('/api/meet/me').json()
    assert reader['user']['access_role'] == 'reader'
    assert set(reader['capabilities']) == {'meetings.read', 'prep.generate', 'calendar.view', 'qa.ask',
                                           'overview.read', 'feedback.create'}


def test_reader_role_cannot_write_even_own_meeting(env):
    petr = login(env['app'], 'petr')
    design = env['design_meeting']  # owned by Petr, but his role is read-only
    assert petr.get(f'/api/meet/meetings/{design}').status_code == 200
    attempts = [
        ('patch', f'/api/meet/meetings/{design}', {'json': {'topic': 'x'}}),
        ('patch', f'/api/meet/meetings/{design}', {'json': {'access_user_ids': []}}),
        ('put', f'/api/meet/meetings/{design}/transcript', {'json': {'text': 'Пётр: текст'}}),
        ('post', f'/api/meet/meetings/{design}/utterances', {'json': {'text': 'текст'}}),
        ('put', f'/api/meet/meetings/{design}/speakers', {'json': {'speaker_map': {'a': 'b'}}}),
        ('post', f'/api/meet/meetings/{design}/protocol/draft', {}),
        ('put', f'/api/meet/meetings/{design}/protocol', {'json': {'items': []}}),
        ('post', f'/api/meet/meetings/{design}/protocol/confirm', {'json': {'item_ids': [1]}}),
        ('post', f'/api/meet/meetings/{design}/documents', {'json': {'document_id': 4}}),
        ('post', f'/api/meet/meetings/{design}/next-agenda', {'json': {'create_meeting': True}}),
        ('post', '/api/meet/meetings', {'json': {'title': 'Новая'}}),
        ('post', '/api/meet/documents', {'files': {'file': ('a.txt', 'текст документа'.encode())}}),
        ('get', '/api/meet/audit', {}),
    ]
    for method, path, kwargs in attempts:
        response = getattr(petr, method)(path, **kwargs)
        assert response.status_code == 403 and response.json()['code'] == 'forbidden_role', (method, path, response.text)
    # reading and asking for a briefing remain available
    assert petr.post(f'/api/meet/meetings/{design}/next-agenda', json={}).status_code == 200
    assert petr.post(f'/api/meet/meetings/{design}/prepare').status_code == 200
    denials = [e for e in audit_rows('access_denied') if e['error_code'] == 'forbidden_role']
    assert len(denials) == len(attempts) and all(e['result'] == 'denied' for e in denials)


def test_capability_never_opens_foreign_object_and_sharing_is_owner_only(env):
    irina, petr = login(env['app'], 'irina'), login(env['app'], 'petr')
    with store.db() as connection:  # Petr's private document, never shared with Irina
        private = connection.execute(
            "INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at) "
            "VALUES (2,'Тайный бриф','p.txt','txt',X'00','0',?)", (store.now(),)).lastrowid
    for path in (f'/api/meet/documents/{private}', f'/api/meet/documents/{private}/download'):
        assert irina.get(path).status_code == 404
    design = env['design_meeting']  # Petr owns it, Irina has ACL access: she may edit, never re-share
    assert irina.patch(f'/api/meet/meetings/{design}', json={'topic': 'Новая тема'}).status_code == 200
    response = irina.patch(f'/api/meet/meetings/{design}', json={'access_user_ids': [1, 2]})
    assert response.status_code == 403 and response.json()['code'] == 'owner_only'
    assert irina.post(f'/api/meet/meetings/{design}/documents', json={'document_id': private}).status_code == 404
    # Petr still sees only what he had
    assert [m['id'] for m in petr.get('/api/meet/meetings').json()['meetings']] == [design]


def test_acl_revocation_takes_effect_immediately_and_is_audited(env):
    irina, petr = login(env['app'], 'irina'), login(env['app'], 'petr')
    launch = env['launch_meeting']
    irina.patch(f'/api/meet/meetings/{launch}', json={'access_user_ids': [2]})
    assert petr.get(f'/api/meet/meetings/{launch}').status_code == 200
    irina.patch(f'/api/meet/meetings/{launch}', json={'access_user_ids': []})
    assert petr.get(f'/api/meet/meetings/{launch}').status_code == 404
    change = audit_rows('meeting_access_change')
    assert change[0]['details']['granted'] == [2] and change[1]['details']['revoked'] == [2]


# ---------- denial audit ----------

def test_denials_are_audited_without_titles(env):
    petr = login(env['app'], 'petr')
    launch = env['launch_meeting']
    response = petr.get(f'/api/meet/meetings/{launch}', headers={'X-Request-ID': 'req-denied-0001'})
    assert response.status_code == 404 and 'Орбит' not in response.text
    assert response.headers['X-Request-ID'] == 'req-denied-0001'
    petr.get('/api/meet/fragments/F1')
    petr.get('/api/meet/utterances/U1')
    rows = audit_rows('access_denied')
    assert [(r['object_type'], r['object_id']) for r in rows] == [('meeting', str(launch)), ('fragment', 'F1'),
                                                                   ('utterance', 'U1')]
    assert rows[0]['request_id'] == 'req-denied-0001' and rows[0]['user_id'] == 2
    with store.db() as connection:
        raw = json.dumps([dict(r) for r in connection.execute('SELECT * FROM audit')], ensure_ascii=False)
    assert 'Орбит' not in raw and 'Бюджет' not in raw


def test_denial_survives_rollback_of_the_main_transaction(env):
    irina = login(env['app'], 'irina')
    launch, design = env['launch_meeting'], env['design_meeting']
    _protocol, item = protocol_with_task(irina, launch)
    with store.db() as connection:  # an item that belongs to another meeting
        foreign = connection.execute("INSERT INTO protocol_items(meeting_id,position,kind,text) VALUES (?,1,'task','x')",
                                     (design,)).lastrowid
    response = irina.post(f'/api/meet/meetings/{launch}/protocol/confirm', json={'item_ids': [item['id'], foreign]})
    assert response.status_code == 404
    assert irina.get('/api/meet/tasks').json()['tasks'] == []  # the first task insert was rolled back
    denial = [r for r in audit_rows('access_denied') if r['object_type'] == 'protocol_item']
    assert denial and denial[0]['object_id'] == str(foreign)


# ---------- AI audit trail ----------

def test_ai_requests_are_logged_with_sources_model_and_stage(env):
    irina = login(env['app'], 'irina')
    launch = env['launch_meeting']
    irina.post(f'/api/meet/meetings/{launch}/prepare', headers={'X-Request-ID': 'req-prep-00001'})
    event = audit_rows('ai_prepare')[-1]
    assert event['request_id'] == 'req-prep-00001' and event['model'] == 'fake-local' and event['result'] == 'ok'
    assert event['source_ids'] and all(re.fullmatch(r'F\d+', s) for s in event['source_ids'])
    assert set(event['details']['cited_ids']) <= set(event['source_ids'])
    protocol_with_task(irina, launch)
    draft = audit_rows('protocol_draft')[-1]
    assert draft['source_ids'][0] == 'U1' and draft['details']['stage'] == 'result'
    env['fake'].fail = 'timeout'
    assert irina.post(f'/api/meet/meetings/{launch}/prepare').status_code == 503
    failed = audit_rows('ai_prepare')[-1]
    assert failed['result'] == 'error' and failed['error_code'] == 'model_timeout'
    env['fake'].fail = None
    irina.get('/api/meet/search', params={'q': 'платёж 1,3 ivan@example.com'})
    query = audit_rows('search')[-1]['details']['query']
    assert 'ivan@example.com' not in query['masked'] and '1' not in query['masked'] and query['sha256']
    events = irina.get('/api/meet/audit').json()['events']
    assert events and all(e['user_id'] == 1 for e in events)


# ---------- tasks: preview / confirm ----------

def test_task_change_preview_confirm_cancel_stale_and_foreign_token(env):
    irina, petr = login(env['app'], 'irina'), login(env['app'], 'petr')
    launch = env['launch_meeting']
    task = confirmed_task(irina, launch)
    path = f"/api/meet/tasks/{task['id']}"
    # preview shows before/after and changes nothing
    preview = irina.post(f'{path}/preview', json={'changes': {'status': 'done', 'due': '2026-11-25'}}).json()
    assert preview['preview']['before']['status'] == 'open' and preview['preview']['after']['status'] == 'done'
    assert preview['expires_at'] and set(preview['preview']['changes']) == {'status', 'due'}
    assert irina.get('/api/meet/tasks').json()['tasks'][0]['status'] == 'open'
    # cancel: target unchanged, token unusable
    assert irina.post(f"/api/meet/confirmations/{preview['confirmation_id']}/cancel").json()['status'] == 'cancelled'
    assert irina.get('/api/meet/tasks').json()['tasks'][0]['status'] == 'open'
    cancelled = irina.post(f'{path}/confirm', json={'confirmation_id': preview['confirmation_id'], 'idempotency_key': 'k-cancel-1'})
    assert cancelled.status_code == 409 and cancelled.json()['code'] == 'confirmation_cancelled'
    # stale: two previews of the same version, the first confirm makes the second stale
    first = irina.post(f'{path}/preview', json={'changes': {'status': 'in_progress'}}).json()
    second = irina.post(f'{path}/preview', json={'changes': {'assignee': 'Дмитрий Орлов'}}).json()
    ok = irina.post(f'{path}/confirm', json={'confirmation_id': first['confirmation_id'], 'idempotency_key': 'k-first-1'}).json()
    assert ok['task']['status'] == 'in_progress' and ok['already_confirmed'] is False
    again = irina.post(f'{path}/confirm', json={'confirmation_id': first['confirmation_id'], 'idempotency_key': 'k-first-1'}).json()
    assert again['already_confirmed'] is True and again['task']['version'] == ok['task']['version']
    stale = irina.post(f'{path}/confirm', json={'confirmation_id': second['confirmation_id'], 'idempotency_key': 'k-second-1'})
    assert stale.status_code == 409 and stale.json()['code'] == 'stale'
    reused = irina.post(f'{path}/confirm', json={'confirmation_id': second['confirmation_id'], 'idempotency_key': 'k-first-1'})
    assert reused.status_code == 409 and reused.json()['code'] == 'idempotency_key_reused'
    # foreign token: Petr (even with access to the meeting) cannot use Irina's token
    irina.patch(f'/api/meet/meetings/{launch}', json={'access_user_ids': [2]})
    third = irina.post(f'{path}/preview', json={'changes': {'status': 'done'}}).json()
    foreign = petr.post(f'{path}/confirm', json={'confirmation_id': third['confirmation_id'], 'idempotency_key': 'k-petr-01'})
    assert foreign.status_code == 404 and foreign.json()['code'] == 'confirmation_not_found'
    assert petr.post(f'{path}/preview', json={'changes': {'status': 'done'}}).status_code == 403  # reader role
    # payload cannot be swapped at confirm
    swapped = irina.post(f'{path}/confirm', json={'confirmation_id': third['confirmation_id'], 'idempotency_key': 'k-swap-01',
                                                  'changes': {'status': 'open'}})
    assert swapped.status_code == 422
    # token bound to its task
    other = irina.post(f'/api/meet/tasks/999/confirm', json={'confirmation_id': third['confirmation_id'], 'idempotency_key': 'k-other-1'})
    assert other.status_code == 404
    assert irina.get('/api/meet/tasks').json()['tasks'][0]['status'] == 'in_progress'
    # direct PATCH: foreign → 404, reader → 403, manager → 409 confirmation_required (no bypass)
    assert petr.patch(path, json={'status': 'done'}).status_code == 403
    irina.patch(f'/api/meet/meetings/{launch}', json={'access_user_ids': []})
    assert petr.patch(path, json={'status': 'done'}).status_code == 404
    assert irina.patch(path, json={'status': 'done'}).json()['code'] == 'confirmation_required'
    assert irina.get('/api/meet/tasks').json()['tasks'][0]['status'] == 'in_progress'
    assert irina.post(f'{path}/preview', json={'changes': {'status': 'in_progress'}}).json()['code'] == 'no_changes'


def test_confirmed_due_change_drops_stale_spoken_wording(env):
    irina = login(env['app'], 'irina')
    task = confirmed_task(irina, env['launch_meeting'])
    assert task['due_text'] == 'до 20 ноября'
    preview = irina.post(f"/api/meet/tasks/{task['id']}/preview", json={'changes': {'due': '2026-11-27'}}).json()
    changed = irina.post(f"/api/meet/tasks/{task['id']}/confirm",
                         json={'confirmation_id': preview['confirmation_id'], 'idempotency_key': 'k-due-0001'}).json()['task']
    assert changed['due'] == '2026-11-27' and changed['due_text'] is None and changed['source_quote']['utterance_id']


def test_protocol_confirm_stays_idempotent(env):
    irina = login(env['app'], 'irina')
    launch = env['launch_meeting']
    _protocol, item = protocol_with_task(irina, launch)
    first = irina.post(f'/api/meet/meetings/{launch}/protocol/confirm', json={'item_ids': [item['id'], item['id']]}).json()
    second = irina.post(f'/api/meet/meetings/{launch}/protocol/confirm', json={'item_ids': [item['id']]}).json()
    assert len(first['created']) == 1 and second['created'] == [] and len(second['already_confirmed']) == 1
    assert len(irina.get('/api/meet/tasks').json()['tasks']) == 1


# ---------- preparation with open tasks ----------

def test_prepare_includes_open_tasks_of_accessible_previous_meeting_only(env):
    irina, petr = login(env['app'], 'irina'), login(env['app'], 'petr')
    launch = env['launch_meeting']
    task = confirmed_task(irina, launch)
    follow = irina.post(f'/api/meet/meetings/{launch}/next-agenda', json={'create_meeting': True}).json()['meeting']
    prep = irina.post(f"/api/meet/meetings/{follow['id']}/prepare").json()['prep']
    assert [t['id'] for t in prep['open_tasks']] == [task['id']]
    source = prep['open_tasks'][0]['source']
    assert source['kind'] == 'task' and source['id'] == f"T{task['id']}" and source['source_at'].endswith('+00:00')
    assert prep['task_questions'][0]['task_id'] == task['id'] and 'оценку рисков' in prep['task_questions'][0]['text']
    assert all(t['text'] != task['text'] for t in prep['brief'])  # not mixed into document facts
    # Petr gets the follow-up but not the previous meeting: no foreign task leaks through the link
    irina.patch(f"/api/meet/meetings/{follow['id']}", json={'access_user_ids': [2]})
    seen = petr.get(f"/api/meet/meetings/{follow['id']}").json()['prep']
    assert seen['open_tasks'] == [] and seen['task_questions'] == []
    # done tasks disappear from the live block
    preview = irina.post(f"/api/meet/tasks/{task['id']}/preview", json={'changes': {'status': 'done'}}).json()
    irina.post(f"/api/meet/tasks/{task['id']}/confirm", json={'confirmation_id': preview['confirmation_id'], 'idempotency_key': 'k-done-01'})
    assert irina.get(f"/api/meet/meetings/{follow['id']}").json()['prep']['open_tasks'] == []


# ---------- risks and summary ----------

class RiskLLM(FakeLLM):
    def json(self, system, user, schema, predict=1500):
        result = super().json(system, user, schema, predict)
        if system == extract.PROTOCOL_SYSTEM:
            line = dict((text, uid) for uid, text in re.findall(r'^(U\d+) \| [^:]+: (.+)$', user, re.M))
            uid = next((u for t, u in line.items() if 'отстаёт' in t), 'U999')
            result['items'] += [
                {'kind': 'risk', 'text': 'Интеграция с платёжным шлюзом отстаёт на неделю', 'outcome': 'none',
                 'assignee': '', 'due_text': '', 'utterance_ids': [uid], 'quote': 'Интеграция с платёжным шлюзом отстаёт'},
                {'kind': 'risk', 'text': 'Подрядчик может обанкротиться', 'outcome': 'none', 'assignee': '',
                 'due_text': '', 'utterance_ids': [uid], 'quote': 'Подрядчик может обанкротиться'}]
        return result


def test_risk_items_and_summary_are_verified(env):
    llm.set_llm(RiskLLM())
    irina = login(env['app'], 'irina')
    protocol, _item = protocol_with_task(irina, env['launch_meeting'])
    risks = [i for i in protocol['items'] if i['kind'] == 'risk']
    assert [r['text'] for r in risks] == ['Интеграция с платёжным шлюзом отстаёт на неделю']
    assert risks[0]['quotes'][0]['verified'] and 'отстаёт' in risks[0]['quotes'][0]['text']
    assert any('Риск «Подрядчик может обанкротиться» не включено' in w for w in protocol['warnings'])
    assert extract.KIND_RU['risk'] == 'Риск'
    # unknown owner/date and rejected proposal checks are unchanged
    load = next(i for i in protocol['items'] if 'нагрузочные' in i['text'])
    assert load['assignee_status'] == 'unknown' and load['due_status'] == 'unknown'
    assert next(i for i in protocol['items'] if i['kind'] == 'proposal')['outcome'] == 'rejected'
    statuses = {c['text']: c['status'] for c in protocol['summary']}
    assert statuses['Запуск остаётся 1 декабря'] == 'verified'
    assert statuses['Решили перенести запуск на 15 декабря'] == 'needs_clarification'
    # risk is a valid kind for manual protocol edits too
    saved = irina.put(f"/api/meet/meetings/{env['launch_meeting']}/protocol", json={'items': [
        {'id': risks[0]['id'], 'kind': 'risk', 'text': 'Шлюз отстаёт'}]}).json()['protocol']
    assert saved['items'][0]['kind'] == 'risk'


def test_summary_falls_back_to_items_when_model_fails_on_summary(env):
    class SummaryFails(FakeLLM):
        def json(self, system, user, schema, predict=1500):
            if system == extract.SUMMARY_SYSTEM:
                from providers.local_settings import LocalAIError
                raise LocalAIError('timeout')
            return super().json(system, user, schema, predict)
    llm.set_llm(SummaryFails())
    protocol, _ = protocol_with_task(login(env['app'], 'irina'), env['launch_meeting'])
    assert protocol['summary'] and all(c['status'] == 'verified' and c['quotes'] for c in protocol['summary'])
    assert any('Резюме собрано без модели' in w for w in protocol['warnings'])


# ---------- feedback ----------

def test_feedback_requires_access_and_validates_input(env):
    irina, petr = login(env['app'], 'irina'), login(env['app'], 'petr')
    launch, design = env['launch_meeting'], env['design_meeting']
    protocol, item = protocol_with_task(irina, launch)
    ok = irina.post('/api/meet/feedback', json={'meeting_id': launch, 'target_type': 'protocol_item', 'target_id': item['id'],
                                                'rating': 'incorrect', 'comment': 'Срок не тот'})
    assert ok.status_code == 200 and ok.json()['feedback_id']
    assert irina.post('/api/meet/feedback', json={'target_type': 'protocol_summary', 'target_id': launch,
                                                  'rating': 'useful'}).status_code == 200
    assert petr.post('/api/meet/feedback', json={'target_type': 'meeting', 'target_id': design, 'rating': 'useful'}).status_code == 200
    foreign = petr.post('/api/meet/feedback', json={'target_type': 'protocol_item', 'target_id': item['id'], 'rating': 'useful'})
    assert foreign.status_code == 404 and 'Орбит' not in foreign.text
    assert petr.post('/api/meet/feedback', json={'target_type': 'prep', 'target_id': launch, 'rating': 'useful'}).status_code == 404
    mismatch = irina.post('/api/meet/feedback', json={'meeting_id': design, 'target_type': 'protocol_item',
                                                      'target_id': item['id'], 'rating': 'useful'})
    assert mismatch.status_code == 404
    assert irina.post('/api/meet/feedback', json={'target_type': 'task', 'target_id': 1, 'rating': 'useful',
                                                  'comment': 'x' * 1001}).status_code == 422
    assert irina.post('/api/meet/feedback', json={'target_type': 'task', 'target_id': 1, 'rating': 'meh'}).status_code == 422
    with store.db() as connection:  # Petr's QA answer is not Irina's to rate
        answer = connection.execute("INSERT INTO qa_answers(user_id,question_masked,question_sha256,status,generated_at) "
                                    "VALUES (2,'q','h','grounded',?)", (store.now(),)).lastrowid
    assert irina.post('/api/meet/feedback', json={'target_type': 'qa_answer', 'target_id': answer, 'answer_id': answer,
                                                  'rating': 'useful'}).status_code == 404
    assert petr.post('/api/meet/feedback', json={'target_type': 'qa_answer', 'target_id': answer, 'answer_id': answer,
                                                 'rating': 'useful'}).status_code == 200
    # with the knowledge module delivered, its loader re-checks source ACL: a revoked source → 404
    from meetings import feedback as feedback_module
    from meetings.auth import MeetError

    def revoked(_connection, _user_id, _answer_id):
        raise MeetError(404, 'not_found', 'Не найдено или нет доступа.')
    original = feedback_module._answer_loader
    feedback_module._answer_loader = lambda: revoked
    try:
        assert petr.post('/api/meet/feedback', json={'target_type': 'qa_answer', 'target_id': answer,
                                                     'rating': 'useful'}).status_code == 404
    finally:
        feedback_module._answer_loader = original
    mine = irina.get('/api/meet/feedback').json()['feedback']
    assert len(mine) == 2 and mine[-1]['comment'] == 'Срок не тот'


# ---------- time ----------

def test_meeting_time_is_aware_and_naive_input_needs_explicit_zone(env):
    irina = login(env['app'], 'irina')
    naive = irina.post('/api/meet/meetings', json={'title': 'A', 'scheduled_at': '2026-11-20T10:00'})
    assert naive.status_code == 422 and naive.json()['code'] == 'naive_datetime'
    zoned = irina.post('/api/meet/meetings', json={'title': 'B', 'scheduled_at': '2026-11-20T10:00',
                                                   'timezone': 'Europe/Minsk'}).json()['meeting']
    assert zoned['scheduled_at'] == '2026-11-20T07:00:00+00:00' and zoned['timezone'] == 'Europe/Minsk'
    offset = irina.post('/api/meet/meetings', json={'title': 'C', 'scheduled_at': '2026-11-20T10:00:00+03:00'}).json()['meeting']
    assert offset['scheduled_at'] == zoned['scheduled_at']
    assert irina.post('/api/meet/meetings', json={'title': 'D', 'scheduled_at': '2026-11-20T10:00',
                                                  'timezone': 'Mars/Base'}).json()['code'] == 'invalid_timezone'
    assert irina.post('/api/meet/meetings', json={'title': 'E', 'scheduled_at': 'завтра'}).json()['code'] == 'invalid_datetime'
    # legacy seed value (naive) is presented as Europe/Minsk, not the server zone
    legacy = irina.get(f"/api/meet/meetings/{env['launch_meeting']}").json()['meeting']
    assert legacy['scheduled_at'] == '2026-11-12T07:00:00+00:00'
    assert store.now().endswith('+00:00')
    # date late in the evening in Minsk is still that Minsk date
    late = irina.post('/api/meet/meetings', json={'title': 'F', 'scheduled_at': '2026-11-20T23:30:00+03:00'}).json()['meeting']
    with store.db() as connection:
        row = connection.execute('SELECT * FROM meetings WHERE id=?', (late['id'],)).fetchone()
    assert meet_api._meeting_date(row).isoformat() == '2026-11-20'


# ---------- migrations ----------

def test_migration_upgrades_old_database_and_keeps_data(tmp_path, monkeypatch):
    path = tmp_path / 'old.db'
    old = sqlite3.connect(path)
    old.executescript(store.SCHEMA)  # baseline schema of cb2614b, user_version 0
    old.executescript("""
        INSERT INTO users(id,login,name,role,password_hash) VALUES (1,'irina','Ирина','Руководитель','x'), (2,'petr','Пётр','Подрядчик','y');
        INSERT INTO meetings(id,owner_id,title,scheduled_at,created_at) VALUES (1,1,'Старая','2026-11-12T10:00','2026-11-01T09:00:00+03:00'),
            (2,1,'Свободный текст','в четверг утром','2026-11-01'), (3,1,'С поясом','2026-11-12T10:00:00+00:00','2026-11-01');
        INSERT INTO meeting_access VALUES (1,2);
        INSERT INTO protocols(meeting_id,warnings) VALUES (1,'[]');
        INSERT INTO protocol_items(id,meeting_id,position,kind,text) VALUES (1,1,1,'task','Сделать');
        INSERT INTO tasks(id,meeting_id,protocol_item_id,text,assignee_status,due_status,source_quote,confirmed_by,confirmed_at,created_at,updated_at)
            VALUES (1,1,1,'Сделать','unknown','unknown','{}',1,'t','t','t');
        INSERT INTO audit(at,user_id,action,details) VALUES ('t',1,'login','{}');
    """)
    old.commit()
    old.close()
    monkeypatch.setenv('MEETINGS_DB_PATH', str(path))
    store.reset_cache()
    try:
        with store.db() as connection:
            assert migrations.version(connection) == migrations.LATEST
            users = {r['login']: r['access_role'] for r in connection.execute('SELECT login, access_role FROM users')}
            assert users == {'irina': 'manager', 'petr': 'reader'}
            meetings = {r['id']: r for r in connection.execute('SELECT * FROM meetings')}
            assert meetings[1]['scheduled_at'] == '2026-11-12T07:00:00+00:00'  # Europe/Minsk, not the OS zone
            assert meetings[2]['scheduled_at'] is None and meetings[2]['scheduled_at_legacy'] == 'в четверг утром'
            assert meetings[3]['scheduled_at'] == '2026-11-12T10:00:00+00:00'
            assert meetings[1]['version'] == 1
            assert connection.execute('SELECT version FROM tasks WHERE id=1').fetchone()[0] == 1
            assert connection.execute('SELECT summary FROM protocols').fetchone()[0] == '[]'
            assert connection.execute('SELECT COUNT(*) FROM meeting_access').fetchone()[0] == 1
            old_audit = store.audit_out(connection.execute('SELECT * FROM audit').fetchone())
            assert old_audit['action'] == 'login' and old_audit['result'] == 'ok' and old_audit['source_ids'] == []
            for table in ('confirmations', 'calendar_busy', 'calendar_events', 'calendar_outbox', 'feedback',
                          'qa_answers', 'production_metrics', 'production_metric_access'):
                connection.execute(f'SELECT * FROM {table}').fetchall()
            assert migrations.apply(connection) == []  # idempotent
    finally:
        store.reset_cache()


def test_failed_migration_step_leaves_previous_version(tmp_path, monkeypatch):
    path = tmp_path / 'broken.db'
    connection = sqlite3.connect(path)
    connection.executescript(store.SCHEMA)

    def boom(recorder):
        recorder.execute('CREATE TABLE half_done (id INTEGER)')
        raise RuntimeError('boom')
    monkeypatch.setattr(migrations, 'MIGRATIONS', migrations.MIGRATIONS[:1] + [(2, 'boom', boom)])
    with pytest.raises(RuntimeError):
        migrations.apply(connection)
    assert migrations.version(connection) == 1
    assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='half_done'").fetchone()
    connection.close()


# ---------- router registration ----------

def test_optional_routers_are_registered_only_when_delivered(tmp_path, monkeypatch):
    assert meet_api._optional_routers() == [] or all(r.routes for r in meet_api._optional_routers())
    package = tmp_path / 'fake_track3_module'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'api.py').write_text(
        'from fastapi import APIRouter\n'
        'def router():\n'
        '    api = APIRouter()\n'
        "    @api.get('/api/meet/fake-extension')\n"
        '    def fake():\n'
        "        return {'ok': True}\n"
        '    return api\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(meet_api, 'OPTIONAL_ROUTERS', ('fake_track3_module', 'not_delivered_module'))
    routers = meet_api._optional_routers()
    assert len(routers) == 1 and routers[0].routes[0].path == '/api/meet/fake-extension'
    sys.modules.pop('fake_track3_module', None)
    sys.modules.pop('fake_track3_module.api', None)


def test_users_endpoint_exposes_role_not_password(env):
    users = login(env['app'], 'petr').get('/api/meet/users').json()['users']
    assert {u['login']: u['access_role'] for u in users} == {'irina': 'manager', 'petr': 'reader'}
    assert 'password_hash' not in json.dumps(users)


def test_confirmation_expiry(env, monkeypatch):
    irina = login(env['app'], 'irina')
    task = confirmed_task(irina, env['launch_meeting'])
    preview = irina.post(f"/api/meet/tasks/{task['id']}/preview", json={'changes': {'status': 'done'}}).json()
    with store.db() as connection:
        connection.execute("UPDATE confirmations SET expires_at=? WHERE id=?",
                           (datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat(), preview['confirmation_id']))
    expired = irina.post(f"/api/meet/tasks/{task['id']}/confirm",
                         json={'confirmation_id': preview['confirmation_id'], 'idempotency_key': 'k-expired'})
    assert expired.status_code == 409 and expired.json()['code'] == 'confirmation_expired'
