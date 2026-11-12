"""Shift-aware top-three slots, user zones and confirm-time source revalidation."""
from datetime import timedelta

import pytest

from meetings import store
from meetings.calendar import service
from test_track3_calendar import cal, env, at, confirm  # noqa: F401


def find(cal, required=(2,), optional=(), **extra):
    return cal['irina'].post('/api/meet/calendar/slots',json={
        'participant_ids':list(required),'optional_participant_ids':list(optional),
        'range_start':at(cal['day'],9).isoformat(),'range_end':at(cal['day'],18).isoformat(),
        'duration_minutes':30,'timezone':'Europe/Minsk','smart':True,**extra})


def shift(cal, uid=2, start=9, end=16, stale=False):
    with store.db() as c:
        return c.execute('INSERT INTO work_shifts(source_id,as_of,user_id,start_at,end_at,break_start,break_end) VALUES (?,?,?,?,?,?,?)',
            (f'test-shift:{uid}',store.iso_utc(store.parse_aware(store.now())-timedelta(days=2)) if stale else store.now(),
             uid,at(cal['day'],start).isoformat(),at(cal['day'],end).isoformat(),at(cal['day'],12).isoformat(),at(cal['day'],13).isoformat())).lastrowid


def preview_slot(cal, result, optional=(), required=(2,)):
    return cal['irina'].post('/api/meet/calendar/preview',json={
        'meeting_id':cal['design_meeting'],'participant_ids':list(required),'optional_participant_ids':list(optional),
        'start_at':result['slots'][0]['start_at'],'duration_minutes':30,'smart':True})


def test_shift_lunch_buffer_top_three_and_current_timezone(cal):
    shift(cal)
    result=find(cal)
    assert result.status_code==200,result.text
    result=result.json()
    assert len(result['slots'])==3
    assert [s['start_local'][11:16] for s in result['slots']]==['09:15','14:00','14:15']
    assert all(s['reason'] and s['optional_busy_count']==0 for s in result['slots'])
    assert 'Секретная' not in str(result) and 'Личное' not in str(result)
    assert any('график смен не задан' in warning for warning in result['warnings'])
    with store.db() as c:
        c.execute('DELETE FROM calendar_busy')
        c.execute("UPDATE users SET timezone='Asia/Tokyo' WHERE id=1")
    # At 09 Minsk it is 15 Tokyo; no slot extends beyond the organizer's 18 Tokyo.
    slots=find(cal).json()['slots']
    assert slots and all(store.parse_aware(s['end_at']).astimezone(store.zone('Asia/Tokyo')).hour<=18 for s in slots)


def test_optional_conflict_can_be_invited_but_is_explicit(cal):
    with store.db() as c:
        c.execute('DELETE FROM calendar_busy')
        service.add_busy(c,2,at(cal['day'],9),at(cal['day'],18),'Название чужого события')
    result=find(cal,required=(),optional=(2,)).json()
    assert len(result['slots'])==3 and all(s['optional_busy_count']==1 for s in result['slots'])
    assert 'Название чужого' not in str(result)
    p=preview_slot(cal,result,optional=(2,),required=())
    assert p.status_code==200,p.text
    assert any('Необязательных участников' in w for w in p.json()['preview']['warnings'])
    done=confirm(cal['irina'],p.json()['confirmation_id'])
    assert done.status_code==200,done.text
    assert len(done.json()['event']['participants'])==2


def test_optional_attendance_is_ranked_before_time(cal):
    with store.db() as c:
        c.execute('DELETE FROM calendar_busy')
        service.add_busy(c,2,at(cal['day'],9),at(cal['day'],10))
    result=find(cal,required=(),optional=(2,)).json()
    assert all(slot['optional_busy_count']==0 for slot in result['slots'])
    assert result['slots'][0]['start_local'][11:16]=='10:15'


@pytest.mark.parametrize('change',['shift','busy','active','timezone','unavailable','new_warning'])
def test_confirm_revalidates_schedule_and_keeps_calendar_empty(cal,monkeypatch,change):
    shift_id=shift(cal)
    result=find(cal).json();p=preview_slot(cal,result)
    assert p.status_code==200,p.text
    with store.db() as c:
        if change=='shift': c.execute('UPDATE work_shifts SET start_at=? WHERE id=?',(at(cal['day'],10).isoformat(),shift_id))
        if change=='busy': service.add_busy(c,1,at(cal['day'],9),at(cal['day'],10))
        if change=='active': c.execute('UPDATE users SET active=0 WHERE id=2')
        if change=='timezone': c.execute("UPDATE users SET timezone='America/New_York' WHERE id=1")
    if change=='unavailable':monkeypatch.setenv('MOCK_CALENDAR_FAULT','down')
    if change=='new_warning':monkeypatch.setenv('MOCK_CALENDAR_FAULT','stale')
    r=confirm(cal['irina'],p.json()['confirmation_id'])
    assert r.status_code in (409,422,503),r.text
    with store.db() as c:
        assert c.execute('SELECT COUNT(*) FROM calendar_events').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM calendar_outbox').fetchone()[0]==0


def test_unknown_or_corrupt_shift_and_stale_source(cal,monkeypatch):
    sid=shift(cal,stale=True)
    result=find(cal)
    assert result.status_code==200 and any('старше 24 часов' in w for w in result.json()['warnings'])
    with store.db() as c:c.execute("UPDATE work_shifts SET break_end='invalid-time' WHERE id=?",(sid,))
    result=find(cal)
    assert result.status_code==503 and result.json()['code']=='calendar_unavailable'
    monkeypatch.setenv('MOCK_CALENDAR_FAULT','down')
    assert find(cal).status_code==503


def test_no_shifts_in_requested_range_means_no_slot_not_office_fallback(cal):
    sid=shift(cal)
    with store.db() as c:
        c.execute('UPDATE work_shifts SET start_at=?,end_at=? WHERE id=?',
                  (at(cal['day']+timedelta(days=1),9).isoformat(),at(cal['day']+timedelta(days=1),16).isoformat(),sid))
    assert find(cal).json()['slots']==[]


def test_absence_and_role_denial_without_hr_details(cal):
    with store.db() as c:
        c.execute("UPDATE users SET personnel_code='TEST-ABSENCE' WHERE id=2")
        c.execute("INSERT INTO departments(id,code,name) VALUES (99,'TEST','Тест')")
        c.execute('UPDATE users SET department_id=99 WHERE id=2')
        c.execute('INSERT INTO hr_absences(source_id,as_of,department_id,personnel_code,start_at,end_at,reason) VALUES (?,?,?,?,?,?,?)',
                  ('test:absence',store.now(),99,'TEST-ABSENCE',at(cal['day'],0).isoformat(),at(cal['day'],23).isoformat(),'Не раскрывать причину'))
    result=find(cal)
    assert result.status_code==200 and result.json()['slots']==[] and 'Не раскрывать' not in result.text
    with store.db() as c:c.execute("UPDATE users SET level='auditor' WHERE id=1")
    assert find(cal).status_code==403


def test_smart_cancel_and_repeat_one_event(cal):
    shift(cal);result=find(cal).json();p=preview_slot(cal,result).json()
    c=cal['irina']
    assert c.post(f"/api/meet/confirmations/{p['confirmation_id']}/cancel").status_code==200
    assert confirm(c,p['confirmation_id']).status_code==409
    p=preview_slot(cal,result).json();a=confirm(c,p['confirmation_id']);b=confirm(c,p['confirmation_id'])
    assert a.status_code==200 and b.json()['already_confirmed']
    assert a.json()['event']['id']==b.json()['event']['id']


def test_optional_ids_must_use_smart_mode_and_invalid_range(cal):
    r=find(cal,required=(),optional=(2,),smart=False)
    assert r.status_code==422
    assert find(cal,range_end=at(cal['day'],8).isoformat()).status_code==422
    assert find(cal,work_start='19:00',work_end='18:00').status_code==422


def test_inactive_or_contentless_user_is_not_an_invitee(cal):
    with store.db() as c:c.execute("UPDATE users SET level='admin' WHERE id=2")
    assert find(cal).status_code==422
    directory=cal['irina'].get('/api/meet/calendar/participants').json()['participants']
    assert {person['id'] for person in directory}=={1}


def test_availability_audits_counts_and_failed_source_without_titles(cal,monkeypatch):
    assert find(cal).status_code==200
    monkeypatch.setenv('MOCK_CALENDAR_FAULT','down')
    assert find(cal).status_code==503
    with store.db() as c:
        events=[dict(row) for row in c.execute("SELECT * FROM audit WHERE action LIKE 'availability_%'")]
    assert {event['action'] for event in events}=={'availability_search','availability_unavailable'}
    assert all('Секретная' not in str(event) and 'Личное' not in str(event) for event in events)
