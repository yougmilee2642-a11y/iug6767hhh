"""«Фокус» отвечает про встречи, задачи, сроки, решения и документы — только в пределах прав."""
import json
from datetime import datetime, timezone

import pytest

from meetings import voice, voice_agenda

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)  # четверг, 13:00 по Минску


@pytest.mark.parametrize('text, kinds', [
    ('Какие у меня сегодня встречи?', ['meetings']),
    ('Что у меня завтра?', ['meetings']),
    ('Кто будет на следующей встрече?', ['meetings']),
    ('Какие у меня задачи?', ['my_tasks']),
    ('Какие задачи у Анны Морозовой?', ['person_tasks']),
    ('Какие ближайшие сроки?', ['deadlines']),
    ('Какие решения на контроле?', ['decisions']),
    ('Какие у нас новые документы?', ['documents']),
    ('Что в регламенте сказано про брак?', []),
    ('Сколько у нас просроченных задач?', []),
    ('Покажи KPI', []),
])
def test_detect(text, kinds):
    assert voice_agenda.detect(text) == kinds


def test_day_range_and_plural():
    today = NOW.date()
    assert voice_agenda.day_range('что завтра', today)[2] == 'завтра'
    assert voice_agenda.day_range('на этой неделе', today)[1].isoformat() == '2026-11-15'
    assert voice_agenda.day_range('на следующей неделе', today)[0].isoformat() == '2026-11-16'
    assert [voice_agenda.plural(n, 'задача', 'задачи', 'задач') for n in (1, 3, 5, 11, 21)] == \
        ['задача', 'задачи', 'задач', 'задач', 'задача']


@pytest.fixture
def company(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGS_DB_PATH', str(tmp_path / 'm.db'))
    from meetings import store
    store.reset_cache()
    with store.db() as c:
        def user(login, name, role='manager'):
            return c.execute("INSERT INTO users(login,name,role,password_hash,access_role) VALUES (?,?,?,?,?)",
                             (login, name, 'demo', 'x', role)).lastrowid
        boss, anna, guest = user('boss', 'Марина Зелёнова'), user('anna', 'Анна Морозова'), user('guest', 'Пётр Смирнов', 'reader')

        def meeting(title, at, people, access=()):
            mid = c.execute('INSERT INTO meetings(owner_id,title,topic,scheduled_at,participants,created_at) VALUES (?,?,?,?,?,?)',
                            (boss, title, '', at, json.dumps(people, ensure_ascii=False), at)).lastrowid
            for member in access:
                c.execute('INSERT INTO meeting_access(meeting_id,user_id) VALUES (?,?)', (mid, member))
            return mid
        today = meeting('Производственное планирование', '2026-11-12T08:00:00+00:00', ['Марина Зелёнова', 'Анна Морозова'], [anna])
        meeting('Итоги недели', '2026-11-16T11:00:00+00:00', ['Марина Зелёнова'])

        def task(text, who, due, mid=today, item=[0]):
            item[0] += 1
            c.execute('INSERT INTO tasks(meeting_id,protocol_item_id,text,assignee,assignee_status,due,due_status,status,'
                      "source_quote,confirmed_by,confirmed_at,created_at,updated_at) VALUES (?,?,?,?,'stated',?,'stated','open',"
                      "'{}',?,?,?,?)", (mid, item[0], text, who, due, boss, '2026-11-01', '2026-11-01', '2026-11-01'))
        task('Заказать бумагу', 'Анна Морозова', '2026-11-15')
        task('Проверить ламинат', 'Анна', '2026-11-10')
        task('Составить план', 'Марина Зелёнова', '2026-11-13')
    users = {}
    from meetings import access
    with store.db() as c:
        for uid in (boss, anna, guest):
            users[uid] = access.load_user(c, uid)
    yield users, boss, anna, guest
    store.reset_cache()


def run(connection_user, kind, text):
    from meetings import store
    with store.db() as c:
        return voice_agenda.answer(c, connection_user, kind, text, NOW)


def test_meetings_today_and_next(company):
    users, boss, *_ = company
    phrase, items = run(users[boss], 'meetings', 'Какие у меня сегодня встречи?')
    assert phrase == 'Сегодня, 11:00 — «Производственное планирование».' and items[0]['kind'] == 'meeting'
    phrase, _ = run(users[boss], 'meetings', 'Какая следующая встреча?')
    assert '«Итоги недели»' in phrase and '16 ноября' in phrase
    phrase, _ = run(users[boss], 'meetings', 'Кто будет на планировании производства?')
    assert 'Марина Зелёнова и Анна Морозова' in phrase


def test_my_tasks_and_person_tasks(company):
    users, boss, anna, _ = company
    phrase, items = run(users[boss], 'my_tasks', 'Какие у меня задачи?')
    assert phrase.startswith('На вас 1 открытая задача.') and '«Составить план» — срок завтра' in phrase
    phrase, items = run(users[boss], 'person_tasks', 'Какие задачи у Анны Морозовой?')
    # «Анна» без фамилии засчитывается, потому что Анна в составе одна.
    assert phrase.startswith('Анна Морозова: 2 открытые задачи, из них 1 просрочена.')
    assert len(items) == 2 and items[0]['late'] is True


def test_person_unknown_falls_through(company):
    users, boss, *_ = company
    assert run(users[boss], 'person_tasks', 'Какие задачи поставили вчера?') is None


def test_rights_limit_what_is_seen_and_spoken(company):
    users, boss, anna, guest = company
    phrase, items = run(users[guest], 'meetings', 'Какие у меня сегодня встречи?')
    assert phrase == 'Сегодня встреч нет.' and items == []
    from meetings import store
    with store.db() as c:
        _, items = voice_agenda.answer(c, users[boss], 'meetings', 'Какая следующая встреча?', NOW)
        assert voice_agenda.visible_to(c, boss, items) is True
        assert voice_agenda.visible_to(c, anna, items) is False  # «Итоги недели» Анне не открыты


def test_voice_routes_agenda_and_keeps_overview(company, monkeypatch):
    users, boss, *_ = company
    monkeypatch.setattr(voice, 'utc_now', lambda: NOW)
    reply = voice.ask(users[boss], 'Привет, какие у меня сегодня встречи?', None, False, {})
    assert reply['route'] == 'agenda' and reply['display'].endswith('Сегодня, 11:00 — «Производственное планирование».')
    assert reply['answer']['items'][0]['meeting_id']
