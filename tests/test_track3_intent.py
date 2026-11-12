from datetime import datetime,timezone
from meetings import access,store
from meetings.intent import fields,number_words
from tests.test_track3_briefing import env

NOW=datetime(2026,11,12,10,tzinfo=timezone.utc)


def parsed(env,text,kind='task',who='prod_head'):
    with store.db() as c:return fields(c,access.load_user(c,env['ids']['users'][who]),text,kind,now=NOW)


def test_dative_name_and_weekday_prepare_editable_task(env):
    data=parsed(env,'Поставь задачу Петрову проверить картон до пятницы')
    assert data['assignee_user_id']==env['ids']['users']['operator']
    assert data['due']=='2026-11-13' and data['requires_clarification']==[]
    assert parsed(env,'Поручи Денису проверить картон до завтра')['assignee_user_id']==data['assignee_user_id']


def test_unknown_ambiguous_and_foreign_owner_remain_unknown(env):
    assert parsed(env,'Поставь задачу неизвестному проверить картон')['assignee_user_id'] is None
    assert parsed(env,'Поставь задачу Денису и Марине проверить картон')['assignee_user_id'] is None
    assert parsed(env,'Поставь задачу Олегу проверить доставку завтра')['assignee_user_id'] is None
    assert parsed(env,'Поставь задачу Олегу проверить доставку завтра',who='director')['assignee_user_id']==env['ids']['users']['log_head']


def test_spoken_dates_yo_and_relative_days(env):
    assert number_words('двадцать шестое ноября')=='26 ноября'
    assert parsed(env,'Поставь задачу Зелёновой проверить картон до двадцать шестого ноября')['due']=='2026-11-26'
    assert parsed(env,'Поставь задачу Зеленовой проверить картон до 26 ноября')['due']=='2026-11-26'
    assert parsed(env,'Поставь задачу Петрову через два дня')['due']=='2026-11-14'
    assert parsed(env,'Поставь задачу Петрову до следующей пятницы')['due']=='2026-11-20'
    assert parsed(env,'Поставь задачу Петрову до 31 февраля')['due'] is None
    assert parsed(env,'Поставь задачу Петрову до завтра или пятницы')['due']=='2026-11-13'
    assert parsed(env,'Поставь задачу Петрову до завтра или понедельника')['due'] is None


def test_department_and_date_prefill_slot_search_without_event(env):
    data=parsed(env,'Назначь встречу с логистикой на завтра на тридцать минут','meeting')
    hint=data['calendar_hint']
    assert hint['participant_ids']==[env['ids']['users']['log_head']]
    assert hint['range_start']=='2026-11-13T09:00:00+03:00'
    assert hint['range_end']=='2026-11-13T18:00:00+03:00' and hint['duration_minutes']==30
    assert data['requires_clarification']==['время']
    assert parsed(env,'Встреча с Олегом завтра в 15:30 на полчаса','meeting')['calendar_hint']['range_start']=='2026-11-13T15:30:00+03:00'
    assert 'время' in parsed(env,'Встреча завтра про печать в три слоя','meeting')['requires_clarification']


def test_voice_fields_never_create_confirmation_or_task(env):
    client=env['prod_head']
    with store.db() as c:
        before={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['tasks','calendar_events','calendar_outbox','confirmations']}
    r=client.post('/api/meet/voice/ask',json={'text':'Поставь задачу Петрову проверить картон до пятницы'})
    assert r.status_code==200,r.text
    assert r.json()['route']=='action_draft' and r.json()['proposed_action']['assignee_user_id']==env['ids']['users']['operator']
    with store.db() as c:assert {t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before}==before


def test_meeting_hint_is_frozen_and_confirm_does_not_invite(env):
    client=env['prod_head'];hint=parsed(env,'Встреча с логистикой завтра','meeting')['calendar_hint']
    p=client.post('/api/meet/assistant/actions/preview',json={'kind':'meeting','text':'Проверить доставку фотокниг','calendar_hint':hint})
    assert p.status_code==200,p.text
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'hint-meeting'}
    r=client.post('/api/meet/assistant/actions/confirm',json=token);assert r.status_code==200,r.text
    assert r.json()['calendar_hint']==hint
    with store.db() as c:
        mid=r.json()['meeting_id']
        assert not c.execute('SELECT 1 FROM calendar_events WHERE meeting_id=?',(mid,)).fetchone()
        assert 'Олег Ветров' in c.execute('SELECT participants FROM meetings WHERE id=?',(mid,)).fetchone()[0]
    assert client.post('/api/meet/assistant/actions/confirm',json=token).json()['already_confirmed']


def test_changed_person_or_actor_context_requires_new_preview(env):
    client=env['prod_head'];hint=parsed(env,'Встреча с логистикой завтра','meeting')['calendar_hint']
    p=client.post('/api/meet/assistant/actions/preview',json={'kind':'meeting','text':'Проверить доставку фотокниг','calendar_hint':hint})
    assert p.status_code==200,p.text
    with store.db() as c:
        before=c.execute('SELECT count(*) FROM meetings').fetchone()[0]
        c.execute("UPDATE users SET name='Олег Новоеимя' WHERE login='log_head'")
    r=client.post('/api/meet/assistant/actions/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'stale-hint'})
    assert r.status_code==409,r.text
    with store.db() as c:assert c.execute('SELECT count(*) FROM meetings').fetchone()[0]==before
