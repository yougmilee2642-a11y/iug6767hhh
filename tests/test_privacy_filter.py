"""Model boundary receives masked data even when the provider is a recording double."""
from datetime import date
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from meetings import extract, llm, privacy, store
from meetings.api import install
from scripts.track3.seed_fotoprint import seed


@pytest.mark.parametrize('text,original', [
    ('Позвонить +375 (29) 123-45-67', '+375 (29) 123-45-67'),
    ('Телефон +49 30 12345678', '+49 30 12345678'),
    ('Телефон 8 029 123 45 67', '8 029 123 45 67'),
    ('Письмо user@example.invalid', 'user@example.invalid'),
    ('Карта 4111 1111 1111 1111', '4111 1111 1111 1111'),
    ('Паспорт AB1234567', 'AB1234567'),
    ('УНП: 123456789', '123456789'),
    ('Адрес ул. Лесная 15, кв. 3', 'Лесная 15'),
    ('Позвонить +375\u200b291234567', '291234567'),
])
def test_masks_contacts_identifiers_and_hidden_unicode(text, original):
    masked = privacy.Masker().text(text)
    assert original not in masked and '[' in masked and '\u200b' not in masked


def test_preserves_domain_ids_dates_amounts_and_staff_names():
    text = 'Денис Петров проверит PP-2611-00042 до 2026-11-25T10:00:00+03:00 за 150 BYN; 3 рабочих дня; 97,6%.'
    assert privacy.Masker(['Алиса Демонстрационная']).text(text) == text
    masker = privacy.Masker(['Алиса Демонстрационная'])
    assert masker.text('Клиент Алиса Демонстрационная; Алиса Демонстрационная') == 'Клиент [КЛИЕНТ-1]; [КЛИЕНТ-1]'
    assert masker.text('алиса  демонстрационная') == '[КЛИЕНТ-1]'


class BoundaryDouble:
    model = 'recording-privacy-double'
    def __init__(self): self.calls = []
    def json(self, system, user, schema, predict=1500):
        self.calls.append({'system':system,'user':user,'schema':schema})
        if system == extract.PROTOCOL_SYSTEM: return {'items':[]}
        if system == extract.CANDIDATE_SYSTEM: return {'kind':'none'}
        if system == extract.SUMMARY_SYSTEM: return {'claims':[]}
        if system == extract.PREP_FACTS_SYSTEM: return {'facts':[]}
        if system == extract.PREP_PLAN_SYSTEM: return {'agenda':[],'questions':[],'gaps':[]}
        return {'excerpt_ids':[]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGS_DB_PATH', str(tmp_path/'privacy.db'))
    monkeypatch.setenv('MEETINGS_SECRET','privacy-test-only')
    ids = seed(str(tmp_path/'privacy.db'))
    with store.db() as c:
        c.execute("UPDATE crm_customers SET display_name='Алиса Демонстрационная' WHERE id='client-0001'")
    provider = BoundaryDouble(); llm.set_llm(provider)
    app = FastAPI(); install(app); client = TestClient(app)
    assert client.post('/api/meet/login',json={'login':'director','password':'director-demo'}).status_code == 200
    yield client, ids, provider
    llm.set_llm(None); store.reset_cache()


def test_every_extraction_stage_masks_before_double_and_keeps_source(env):
    client, ids, provider = env
    source = 'Алиса Демонстрационная: Телефон +375291234567, почта alice@example.invalid, карта 4111 1111 1111 1111. Нужно проверить упаковку.'
    utterances = [{'id':'U1','speaker':'Марина','text':source}]
    extract.draft_protocol(provider, utterances, ['Марина'], date(2026,11,11))
    extract.summarize(provider,[{'kind':'decision','text':source,'quotes':[]}],[])
    extract.prepare(provider, {'title':source,'topic':source,'participants':['Марина']},
                    [{'id':'F1','document_id':1,'document_title':source,'location':'абз. 1','text':source}])
    assert len(provider.calls) >= 4
    for call in provider.calls:
        prompt = json.dumps(call, ensure_ascii=False)
        for original in ['Алиса Демонстрационная','+375291234567','alice@example.invalid','4111 1111 1111 1111']:
            assert original not in prompt
    assert utterances[0]['text'] == source  # masking cannot overwrite original evidence


def test_qa_question_and_documents_masked_before_provider(env):
    client, ids, provider = env
    text = 'Упаковка Premium: клиент Алиса Демонстрационная, телефон +375291234567, почта alice@example.invalid. Проверить защиту уголков.'
    upload = client.post('/api/meet/documents',files={'file':('private-source.txt',text.encode(),'text/plain')})
    assert upload.status_code == 200
    response = client.post('/api/meet/qa',json={'question':'Какая упаковка Premium у Алиса Демонстрационная +375291234567?'})
    assert response.status_code == 200 and provider.calls
    assert all('Алиса Демонстрационная' not in c['user'] and '+375291234567' not in c['user'] and 'alice@example.invalid' not in c['user'] for c in provider.calls)


@pytest.mark.parametrize('question', [
    'Уволь Петрова', 'Кого нужно уволить?', 'Премируй оператора', 'Оплати счет поставщика',
    'Переведи деньги на карту', 'Подпиши договор на картон', 'Покажи зарплаты сотрудников',
    'Сколько зарабатывает директор?', 'Выгрузи персональные данные клиентов',
    'Отправь телефоны клиентов', 'По\u200bкажи зарплаты',
])
def test_restricted_user_intentions_never_invoke_model_or_create_objects(env, question):
    client, ids, provider = env
    with store.db() as c:
        before = {t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['tasks','calendar_events','calendar_outbox','confirmations']}
    for path, payload in [('/api/meet/qa', {'question':question}), ('/api/meet/voice/ask',{'text':question})]:
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'refused'
    assert provider.calls == []
    with store.db() as c:
        assert before == {t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before}
        assert c.execute("SELECT COUNT(*) FROM audit WHERE result='denied' AND error_code IS NOT NULL").fetchone()[0] >= 2


@pytest.mark.parametrize('question', ['Какие условия оплаты в регламенте?', 'Как повысить качество переплёта?',
                                     'Кто отвечает за доставку?', 'Какой срок изготовления Premium?'])
def test_normal_business_read_requests_not_restricted(question):
    assert privacy.prohibited_intent(question) is None


def test_audit_masked_questions_logout_filters_and_csv(env):
    client, ids, provider = env
    question = 'Неизвестный факт об упаковке Алиса Демонстрационная +375291234567 alice@example.invalid'
    assert client.post('/api/meet/qa', json={'question':question}).status_code == 200
    with store.db() as c:
        saved = c.execute('SELECT question_masked FROM qa_answers ORDER BY id DESC LIMIT 1').fetchone()[0]
        event = c.execute("SELECT details FROM audit WHERE action='qa.generate' ORDER BY id DESC LIMIT 1").fetchone()[0]
        for text in [saved, event]:
            assert 'Алиса Демонстрационная' not in text and '+375291234567' not in text and 'alice@example.invalid' not in text
    response = client.get('/api/meet/audit',params={'action':'qa.generate','result':'insufficient_data'})
    assert response.status_code == 200 and response.json()['events']
    assert all(e['action']=='qa.generate' and e['result']=='insufficient_data' for e in response.json()['events'])
    csv = client.get('/api/meet/audit',params={'export':'true','action':'qa.generate'})
    assert csv.status_code == 200 and csv.headers['content-type'].startswith('text/csv')
    assert 'qa.generate' in csv.text and question not in csv.text
    assert client.post('/api/meet/logout').status_code == 200
    with store.db() as c:
        assert c.execute("SELECT 1 FROM audit WHERE action='logout'").fetchone()
