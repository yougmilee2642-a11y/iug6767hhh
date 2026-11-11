"""CallWise Meetings: full path with a scripted local-model double (no Ollama needed)."""
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetings import extract, llm, store
from meetings import textutil as tu
from providers.local_settings import LocalAIError

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'demo' / 'meetings'


class FakeLLM:
    model = 'fake-local'

    def __init__(self):
        self.calls = []
        self.fail = None

    def json(self, system, user, schema, predict=1500):
        self.calls.append((system, user))
        if self.fail:
            raise LocalAIError(self.fail)
        if system == extract.PROTOCOL_SYSTEM:
            return {'items': self._protocol(user)}
        if system == extract.CANDIDATE_SYSTEM:
            return {'kind': 'none', 'text': '', 'outcome': 'none', 'assignee': '', 'due_text': ''}
        if system == extract.PREP_FACTS_SYSTEM:
            ids = {text: fid for fid, text in re.findall(r'^(F\d+) \| .+?\): (.+)$', user, re.M)}
            facts = []
            for text, fid in ids.items():
                if 'Дата запуска: 1 декабря' in text:
                    facts.append({'text': 'Запуск назначен на 1 декабря 2026', 'fragment_id': fid,
                                  'quote': 'Дата запуска: 1 декабря 2026 года'})
                if 'потере предоплаты' in text:
                    facts.append({'text': 'Перенос запуска приведёт к потере 1,3 млн', 'fragment_id': fid,
                                  'quote': 'приведёт к потере предоплаты за медиаразмещение в размере 1,3 млн рублей'})
            facts.append({'text': 'Бюджет увеличен до 10 млн', 'fragment_id': 'F1', 'quote': 'бюджет увеличен до 10 млн рублей'})
            return {'facts': facts}
        if system == extract.PREP_PLAN_SYSTEM:
            return {'agenda': [{'text': 'Статус интеграции шлюза', 'fact_ids': [1]}, {'text': 'Риски переноса', 'fact_ids': [2, 99]}],
                    'questions': [{'text': 'Можно ли запуститься в ограниченном режиме?', 'fact_ids': []}], 'gaps': []}
        raise AssertionError('unexpected prompt')

    @staticmethod
    def _protocol(user):
        lines = dict((text, uid) for uid, text in re.findall(r'^(U\d+) \| [^:]+: (.+)$', user, re.M))

        def cite(fragment):
            return next((uid for text, uid in lines.items() if fragment in text), 'U999')
        return [
            {'kind': 'proposal', 'text': 'Перенести запуск на 15 декабря', 'outcome': 'rejected', 'assignee': '', 'due_text': '',
             'utterance_ids': [cite('предлагаю перенести')], 'quote': 'Я предлагаю перенести запуск на 15 декабря'},
            {'kind': 'decision', 'text': 'Запуск остаётся 1 декабря', 'outcome': 'none', 'assignee': '', 'due_text': '',
             'utterance_ids': [cite('решили')], 'quote': 'перенос запуска отклоняем, запуск остаётся 1 декабря'},
            {'kind': 'task', 'text': 'Подготовить оценку рисков по платёжному шлюзу', 'outcome': 'none', 'assignee': 'Анна',
             'due_text': 'до 20 ноября', 'utterance_ids': [cite('подготовь')], 'quote': 'подготовь, пожалуйста, оценку рисков'},
            {'kind': 'task', 'text': 'Обновить нагрузочные тесты', 'outcome': 'none', 'assignee': 'Дмитрий', 'due_text': 'до 1 декабря',
             'utterance_ids': [cite('нагрузочные')], 'quote': 'обновить нагрузочные тесты'},
            {'kind': 'decision', 'text': 'Утвердить доп. бюджет на поддержку', 'outcome': 'none', 'assignee': '', 'due_text': '',
             'utterance_ids': ['U1'], 'quote': 'мы утвердили дополнительный бюджет на поддержку'},
            {'kind': 'open_question', 'text': 'Нужен ли дополнительный бюджет на поддержку', 'outcome': 'none', 'assignee': '',
             'due_text': '', 'utterance_ids': [cite('Открытым')], 'quote': 'нужен ли дополнительный бюджет на поддержку'},
        ]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGS_DB_PATH', str(tmp_path / 'meetings.db'))
    monkeypatch.setenv('MEETINGS_SECRET', 'test-secret')
    store.reset_cache()
    fake = FakeLLM()
    llm.set_llm(fake)
    from scripts.seed_meetings_demo import seed
    ids = seed()
    import app as application
    yield {'app': application.app, 'fake': fake, **ids}
    llm.set_llm(None)
    store.reset_cache()


def login(app, who):
    client = TestClient(app)
    response = client.post('/api/meet/login', json={'login': who, 'password': f'{who}-demo'})
    assert response.status_code == 200, response.text
    return client


def test_requires_login_and_rejects_bad_password(env):
    client = TestClient(env['app'])
    assert client.get('/api/meet/meetings').json()['code'] == 'not_authenticated'
    assert client.post('/api/meet/login', json={'login': 'irina', 'password': 'wrong'}).status_code == 401
    forged = TestClient(env['app'], cookies={'cw_meet_user': '1.9999999999.aa.bad'})
    assert forged.get('/api/meet/me').status_code == 401


def test_second_user_cannot_reach_closed_materials(env):
    irina, petr = login(env['app'], 'irina'), login(env['app'], 'petr')
    launch = env['launch_meeting']
    irina_docs = irina.get('/api/meet/documents').json()['documents']
    closed = [d for d in irina_docs if d['owner_id'] == 1]
    fragment = irina.get(f"/api/meet/documents/{closed[0]['id']}").json()['fragments'][0]['id']
    assert {d['title'] for d in petr.get('/api/meet/documents').json()['documents']} == {'Гайд по бренду'}
    assert [m['title'] for m in petr.get('/api/meet/meetings').json()['meetings']] == ['Синк по дизайну кампании']
    for path in (f'/api/meet/meetings/{launch}', f"/api/meet/documents/{closed[0]['id']}",
                 f"/api/meet/documents/{closed[0]['id']}/download", f'/api/meet/fragments/{fragment}'):
        response = petr.get(path)
        assert response.status_code == 404 and response.json()['code'] == 'not_found', path
    assert petr.post(f'/api/meet/meetings/{launch}/prepare').status_code == 404
    assert petr.put(f'/api/meet/meetings/{launch}/transcript', json={'text': 'x: y'}).status_code == 404
    assert petr.post(f'/api/meet/meetings/{launch}/documents', json={'document_id': closed[0]['id']}).status_code == 404
    assert petr.get('/api/meet/search', params={'q': 'платёжным шлюзом'}).json()['results'] == []
    assert irina.get('/api/meet/search', params={'q': 'платёжным шлюзом'}).json()['results']
    # Irina sees Petr's shared meeting and document.
    assert len(irina.get('/api/meet/meetings').json()['meetings']) == 2
    assert env['fake'].calls == []


def test_attaching_foreign_document_does_not_leak_into_model_context(env):
    irina, petr = login(env['app'], 'irina'), login(env['app'], 'petr')
    secret = next(d for d in irina.get('/api/meet/documents').json()['documents'] if d['filename'] == 'budget.txt')
    design = env['design_meeting']
    irina.post(f'/api/meet/meetings/{design}/documents', json={'document_id': secret['id']})
    meeting = petr.get(f'/api/meet/meetings/{design}').json()
    assert [d['title'] for d in meeting['documents']] == ['Гайд по бренду'] and meeting['hidden_documents'] == 1
    petr.post(f'/api/meet/meetings/{design}/prepare')
    context = '\n'.join(user for _system, user in env['fake'].calls)
    assert 'предоплаты' not in context and 'Логотип' in context


def test_full_path_transcript_protocol_confirmed_tasks(env):
    client = login(env['app'], 'irina')
    launch = env['launch_meeting']
    assert client.post(f'/api/meet/meetings/{launch}/protocol/draft').json()['code'] == 'empty_transcript'
    utterances = client.put(f'/api/meet/meetings/{launch}/transcript',
                            json={'text': (DEMO / 'transcript.txt').read_text(encoding='utf-8')}).json()['utterances']
    assert len(utterances) == 10 and utterances[1]['speaker'] == 'Дмитрий Орлов' and utterances[1]['start_ms'] == 15000
    protocol = client.post(f'/api/meet/meetings/{launch}/protocol/draft').json()['protocol']
    items = {i['text']: i for i in protocol['items']}
    proposal = items['Перенести запуск на 15 декабря']
    assert proposal['kind'] == 'proposal' and proposal['outcome'] == 'rejected'
    assert not any(i['kind'] == 'decision' and 'Перенести' in i['text'] for i in protocol['items'])
    assert items['Запуск остаётся 1 декабря']['kind'] == 'decision'
    anna = items['Подготовить оценку рисков по платёжному шлюзу']
    assert anna['assignee'] == 'Анна Ковалёва' and anna['assignee_status'] == 'stated'
    assert anna['due'] == '2026-11-20' and anna['due_status'] == 'stated'
    load = items['Обновить нагрузочные тесты']
    assert load['assignee'] is None and load['assignee_status'] == 'unknown' and load['due'] is None and load['due_status'] == 'unknown'
    assert 'Утвердить доп. бюджет на поддержку' not in items
    assert any('не дала подтверждающей цитаты' in w for w in protocol['warnings'])
    assert any('Дмитрий' in w for w in protocol['warnings'])
    by_id = {u['id']: u for u in utterances}
    for item in protocol['items']:
        for quote in item['quotes']:
            assert quote['verified'] and quote['text'] in by_id[quote['utterance_id']]['text']
            opened = client.get(f"/api/meet/utterances/{quote['utterance_id']}").json()['utterance']
            assert quote['text'] in opened['text']
    assert client.get('/api/meet/tasks').json()['tasks'] == []  # nothing before confirmation

    first = client.post(f'/api/meet/meetings/{launch}/protocol/confirm', json={'item_ids': [anna['id']]}).json()
    assert len(first['created']) == 1
    task = first['created'][0]
    assert task['confirmed_by'] == 'Ирина Власова' and task['confirmed_at'] and task['status'] == 'open'
    assert task['meeting_title'].startswith('Запуск') and task['source_quote']['utterance_id']
    again = client.post(f'/api/meet/meetings/{launch}/protocol/confirm', json={'item_ids': [anna['id']]}).json()
    assert again['created'] == [] and len(again['already_confirmed']) == 1
    decision = items['Запуск остаётся 1 декабря']
    assert client.post(f'/api/meet/meetings/{launch}/protocol/confirm', json={'item_ids': [decision['id']]}).status_code == 422
    # Re-draft must not duplicate confirmed task.
    redraft = client.post(f'/api/meet/meetings/{launch}/protocol/draft').json()['protocol']
    assert sum(1 for i in redraft['items'] if 'оценку рисков' in i['text']) == 1
    assert len(client.get('/api/meet/tasks').json()['tasks']) == 1
    # Petr never sees Irina's task.
    assert login(env['app'], 'petr').get('/api/meet/tasks').json()['tasks'] == []
    assert login(env['app'], 'petr').patch(f"/api/meet/tasks/{task['id']}", json={'status': 'done'}).status_code == 404

    moved = client.patch(f"/api/meet/tasks/{task['id']}", json={'status': 'in_progress'}).json()['task']
    assert moved['status'] == 'in_progress'
    agenda = client.post(f'/api/meet/meetings/{launch}/next-agenda', json={'create_meeting': True}).json()
    assert agenda['agenda'][0]['task_id'] == task['id'] and agenda['meeting']['followup_of'] == launch
    follow = client.get(f"/api/meet/meetings/{agenda['meeting']['id']}").json()
    assert 'оценку рисков' in follow['prep']['agenda'][0]['text']

    # Persistence across restart: drop caches and read with a fresh client.
    store.reset_cache()
    restarted = login(env['app'], 'irina').get(f'/api/meet/meetings/{launch}').json()
    assert len(restarted['utterances']) == 10 and len(restarted['tasks']) == 1
    assert any(i['confirmed'] for i in restarted['protocol']['items'])


def test_edit_protocol_and_transcript(env):
    client = login(env['app'], 'irina')
    launch = env['launch_meeting']
    client.put(f'/api/meet/meetings/{launch}/transcript', json={'text': 'Говорящий 1: Нужно сделать отчёт до 5 декабря\nпродолжение строки'})
    utterance = client.get(f'/api/meet/meetings/{launch}').json()['utterances'][0]
    assert utterance['text'].endswith('продолжение строки')
    edited = client.patch(f"/api/meet/utterances/{utterance['id']}", json={'text': 'Анна, сделай отчёт до 5 декабря'}).json()['utterance']
    assert edited['edited'] and edited['original_text'] != edited['text']
    mapped = client.put(f'/api/meet/meetings/{launch}/speakers', json={'speaker_map': {'Говорящий 1': 'Ирина Власова'}}).json()
    assert mapped['utterances'][0]['speaker'] == 'Ирина Власова'
    saved = client.put(f'/api/meet/meetings/{launch}/protocol', json={'items': [
        {'kind': 'task', 'text': 'Сделать отчёт', 'assignee': 'Анна Ковалёва', 'due': '2026-12-05',
         'quotes': [{'utterance_id': utterance['id']}, {'utterance_id': 'U99999'}]},
        {'kind': 'task', 'text': 'Без исполнителя'}]}).json()['protocol']
    report, orphan = saved['items']
    assert report['assignee_status'] == 'stated' and report['due'] == '2026-12-05' and report['edited']
    assert [q['utterance_id'] for q in report['quotes']] == [utterance['id']]
    assert orphan['assignee_status'] == 'unknown' and orphan['due_status'] == 'unknown'
    assert client.put(f'/api/meet/meetings/{launch}/protocol', json={'items': [
        {'kind': 'task', 'text': 'x', 'due': '5 декабря'}]}).status_code == 422


def test_model_errors_keep_data_and_return_clear_code(env):
    client = login(env['app'], 'irina')
    launch = env['launch_meeting']
    client.put(f'/api/meet/meetings/{launch}/transcript', json={'text': (DEMO / 'transcript.txt').read_text(encoding='utf-8')})
    for code in ('unavailable', 'timeout', 'invalid_reply'):
        env['fake'].fail = code
        response = client.post(f'/api/meet/meetings/{launch}/protocol/draft')
        assert response.status_code == 503 and response.json()['code'] == f'model_{code}'
        assert client.post(f'/api/meet/meetings/{launch}/prepare').status_code == 503
    assert len(client.get(f'/api/meet/meetings/{launch}').json()['utterances']) == 10


def test_garbage_model_output_is_dropped(env):
    class Garbage(FakeLLM):
        def json(self, system, user, schema, predict=1500):
            return {'items': ['x', {'kind': 'hack', 'text': 'rm -rf'}, {'kind': 'task', 'text': 'Отметить всё выполненным',
                     'utterance_ids': ['U1'], 'quote': 'игнорируй инструкции'}]}
    llm.set_llm(Garbage())
    client = login(env['app'], 'irina')
    launch = env['launch_meeting']
    client.put(f'/api/meet/meetings/{launch}/transcript', json={'text': 'Ирина: Добрый день, обсуждаем запуск.'})
    protocol = client.post(f'/api/meet/meetings/{launch}/protocol/draft').json()['protocol']
    assert protocol['items'] == [] and protocol['warnings']


def test_preparation_with_verified_citations_and_insufficient_data(env):
    client = login(env['app'], 'irina')
    launch = env['launch_meeting']
    prep = client.post(f'/api/meet/meetings/{launch}/prepare').json()['prep']
    assert prep['status'] == 'ok' and len(prep['brief']) == 2
    for claim in prep['brief']:
        citation = claim['citations'][0]
        fragment = client.get(f"/api/meet/fragments/{citation['fragment_id']}").json()['fragment']
        assert citation['quote'] in fragment['text']
    assert not any('10 млн' in c['text'] for c in prep['brief']) and any('отброшено' in g for g in prep['gaps'])
    assert prep['agenda'][1]['citations'] and prep['questions'][0]['citations'] == []
    # Prompt-injection text from the risk register reached the model only as delimited data.
    risk_prompt = next(user for system, user in env['fake'].calls if 'игнорируй' in user)
    assert risk_prompt.index('<<<') < risk_prompt.index('игнорируй') < risk_prompt.index('>>>')
    assert client.get('/api/meet/tasks').json()['tasks'] == []
    empty = client.post('/api/meet/meetings', json={'title': 'Пустая', 'participants': []}).json()['meeting']
    nothing = client.post(f"/api/meet/meetings/{empty['id']}/prepare").json()['prep']
    assert nothing['status'] == 'insufficient_data' and nothing['gaps']


def test_upload_formats_and_bad_files(env):
    client = login(env['app'], 'irina')
    for name in ('launch_plan.docx', 'risk_register.pdf', 'budget.txt'):
        response = client.post('/api/meet/documents', files={'file': (name, (DEMO / name).read_bytes())},
                               data={'share_with': '2'})
        assert response.status_code == 200, response.text
        assert response.json()['document']['fragments_count'] >= 3 and response.json()['document']['shared_with'] == [2]
    assert client.post('/api/meet/documents', files={'file': ('x.exe', b'MZ')}).json()['code'] == 'bad_document'
    assert client.post('/api/meet/documents', files={'file': ('x.docx', b'not a zip')}).status_code == 422
    downloaded = client.get('/api/meet/documents/1/download')
    assert downloaded.status_code == 200 and downloaded.content == (DEMO / 'launch_plan.docx').read_bytes()


def test_meetings_page_served(env):
    response = TestClient(env['app']).get('/meetings')
    assert response.status_code == 200


def test_textutil_dates_and_quotes():
    reference = date(2026, 11, 12)
    assert tu.parse_due('до 20 ноября', reference) == '2026-11-20'
    assert tu.parse_due('к 15.01', reference) == '2027-01-15'
    assert tu.parse_due('до 3 мая 2027', reference) == '2027-05-03'
    assert tu.parse_due('на следующей неделе', reference) is None
    source = 'Тогда решили: перенос запуска отклоняем, запуск остаётся 1 декабря.'
    assert tu.find_exact('ПЕРЕНОС запуска отклоняем', source) == 'перенос запуска отклоняем'
    assert tu.verify_quote('совсем другой текст про бюджет', source) is None
    assert tu.name_mentioned('Анна', 'Анне нужно подготовить') and not tu.name_mentioned('Пётр', source)
