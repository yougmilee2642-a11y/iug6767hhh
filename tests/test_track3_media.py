import io
import json
import wave
from datetime import timedelta
import pytest
from meetings import retention,store
from meetings.media import backend,pipeline
from tests.test_track3_briefing import env


def wav():
    output=io.BytesIO()
    with wave.open(output,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\x01\x00'*16000)
    return output.getvalue()


def meeting(env):
    r=env['prod_head'].post('/api/meet/meetings',json={'title':'Проверка аудио','participants':['Денис Петров','Марина Зелёнова']})
    assert r.status_code==200,r.text
    return r.json()['meeting']['id']


def upload(env,mid,consent=True,data=None):
    return env['prod_head'].post(f'/api/meet/meetings/{mid}/audio',data={'consent':str(consent).lower()},
                                files={'file':('test.wav',wav() if data is None else data,'audio/wav')})


def fake(monkeypatch,*,error=None):
    monkeypatch.setattr(backend,'ready',lambda:True)
    class Double:
        def __init__(self):self.index=0
        def diarize(self,audio):
            if error:raise backend.MediaError(error)
            return [{'start':0,'end':0.6,'speaker':'a'},{'start':0.4,'end':1,'speaker':'b'}]
        def transcribe(self,audio):
            self.index+=1
            return ['Проверить картон.','Решили заказать образцы.'][self.index-1]
    monkeypatch.setattr(backend,'Backend',Double)


def test_no_consent_or_invalid_file_creates_nothing(env,monkeypatch):
    monkeypatch.setattr(backend,'ready',lambda:False);mid=meeting(env)
    assert upload(env,mid,False).status_code==403
    assert upload(env,mid,data=b'<script>not audio</script>').status_code==422
    monkeypatch.setenv('MEETINGS_AUDIO_MAX_MB','1')
    assert upload(env,mid,data=b'X'*(1024*1024+1)).status_code==413
    with store.db() as c:
        assert not c.execute('SELECT 1 FROM media_assets').fetchone()
        assert c.execute("SELECT 1 FROM audit WHERE action='audio_uploaded'").fetchone() is None


def test_missing_models_returns_503_without_losing_audio_and_acl(env,monkeypatch):
    monkeypatch.setattr(backend,'ready',lambda:False);mid=meeting(env)
    r=upload(env,mid);assert r.status_code==503,r.text
    job=r.json()['job'];assert job['error_code']=='asr_unavailable'
    route=f"/api/meet/media-assets/{job['asset_id']}/audio"
    assert env['prod_head'].get(route).content==wav()
    assert env['designer'].get(route).status_code==404
    assert env['admin'].get(route).status_code==404
    assert env['designer'].get(f"/api/meet/media-jobs/{job['id']}").status_code==404
    assert upload(env,mid).json()['job']['id']==job['id']
    assert env['prod_head'].post(f"/api/meet/media-jobs/{job['id']}/retry").status_code==503
    with store.db() as c:assert c.execute('SELECT count(*) FROM media_assets').fetchone()[0]==1


def test_pipeline_segments_preview_cancel_confirm_replay_and_metrics(env,monkeypatch):
    fake(monkeypatch);mid=meeting(env);r=upload(env,mid);assert r.status_code==202,r.text
    jid=r.json()['job']['id'];route=f'/api/meet/media-jobs/{jid}'
    job=env['prod_head'].get(route).json()['job']
    assert job['status']=='done' and job['duration_ms']==1000 and len(job['segments'])==2
    with store.db() as c:assert not c.execute('SELECT 1 FROM utterances WHERE meeting_id=?',(mid,)).fetchone()
    mapping={'speaker_map':{'Говорящий 1':'Денис Петров','Говорящий 2':'Марина Зелёнова'}}
    p=env['prod_head'].post(route+'/import/preview',json=mapping);assert p.status_code==200,p.text
    token=p.json()['confirmation_id']
    assert env['prod_head'].post(f'/api/meet/confirmations/{token}/cancel').status_code==200
    assert env['prod_head'].post(route+'/import/confirm',json={'confirmation_id':token,'idempotency_key':'cancel-audio'}).status_code==409
    p=env['prod_head'].post(route+'/import/preview',json=mapping)
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'confirm-audio'}
    r=env['prod_head'].post(route+'/import/confirm',json=token);assert r.status_code==200,r.text
    assert len(r.json()['utterance_ids'])==2
    assert env['prod_head'].post(route+'/import/confirm',json=token).json()['already_confirmed']
    with store.db() as c:
        rows=store.utterances(c,mid)
        assert len(rows)==2 and rows[0]['start_ms']==0 and rows[0]['end_ms']==600 and rows[0]['media_job_id']==jid
        assert rows[0]['text']==rows[0]['original_text']
        assert c.execute("SELECT 1 FROM notifications WHERE kind='media_ready'").fetchone()
    a=env['prod_head'].get(f'/api/meet/meetings/{mid}/analytics');assert a.status_code==200,a.text
    assert a.json()['overlap_ms']==200 and all(p['share_percent']==50 for p in a.json()['speakers'])
    assert env['designer'].get(f'/api/meet/meetings/{mid}/analytics').status_code==404


def test_edited_transcript_and_forged_speaker_mapping_rejected(env,monkeypatch):
    fake(monkeypatch);mid=meeting(env);jid=upload(env,mid).json()['job']['id'];route=f'/api/meet/media-jobs/{jid}'
    assert env['prod_head'].post(route+'/import/preview',json={'speaker_map':{'Говорящий 1':'Неизвестный'}}).status_code==422
    p=env['prod_head'].post(route+'/import/preview',json={});assert p.status_code==200,p.text
    assert env['prod_head'].put(f'/api/meet/meetings/{mid}/transcript',json={'text':'Марина: Ручная правка'}).status_code==200
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'stale-audio'}
    assert env['prod_head'].post(route+'/import/confirm',json=token).status_code==409
    with store.db() as c:assert len(store.utterances(c,mid))==1


def test_worker_failure_keeps_source_and_retry_works(env,monkeypatch):
    fake(monkeypatch,error='diarization_unavailable');mid=meeting(env);jid=upload(env,mid).json()['job']['id']
    route=f'/api/meet/media-jobs/{jid}'
    job=env['prod_head'].get(route).json()['job']
    assert job['status']=='failed' and job['asset_id'] and job['error_code']=='diarization_unavailable'
    fake(monkeypatch)
    assert env['prod_head'].post(route+'/retry').status_code==200
    assert env['prod_head'].get(route).json()['job']['status']=='done'


def test_retention_removes_original_audio_after_review_keeps_manual_provenance(env,monkeypatch):
    fake(monkeypatch);mid=meeting(env);jid=upload(env,mid).json()['job']['id'];route=f'/api/meet/media-jobs/{jid}'
    p=env['prod_head'].post(route+'/import/preview',json={})
    assert env['prod_head'].post(route+'/import/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'retention-audio'}).status_code==200
    p=env['prod_head'].post('/api/meet/assistant/actions/preview',json={'kind':'task','meeting_id':mid,'text':'Ручное поручение'})
    t=env['prod_head'].post('/api/meet/assistant/actions/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'manual-retention'}).json()
    with store.db() as c:
        retention.clean(c)
        assert not c.execute('SELECT 1 FROM media_assets WHERE meeting_id=?',(mid,)).fetchone()
        assert c.execute('SELECT count(*) FROM media_segments WHERE job_id=?',(jid,)).fetchone()[0]==2
        c.execute('UPDATE meetings SET created_at=? WHERE id=?',(store.iso_utc(store.parse_aware(store.now())-timedelta(days=181)),mid))
        retention.clean(c)
        assert not store.utterances(c,mid)
        task=c.execute('SELECT source_quote FROM tasks WHERE id=?',(t['task_id'],)).fetchone()
        assert json.loads(task[0])['kind']=='manual_request'


def test_startup_marks_interrupted_job_failed_but_keeps_audio(env,monkeypatch):
    from fastapi.testclient import TestClient
    fake(monkeypatch);monkeypatch.setattr(pipeline,'run',lambda *_:None)
    mid=meeting(env);job=upload(env,mid).json()['job']
    assert job['status']=='queued'
    with TestClient(env['app']):
        with store.db() as c:
            row=c.execute('SELECT * FROM media_jobs WHERE id=?',(job['id'],)).fetchone()
            assert row['status']=='failed' and row['error_code']=='processing_interrupted'
            assert c.execute('SELECT content FROM media_assets WHERE id=?',(row['asset_id'],)).fetchone()[0]==wav()


def test_secret_audio_is_retained_without_decode_or_model(env,monkeypatch):
    mid=meeting(env)
    with store.db() as c:c.execute("UPDATE meetings SET confidentiality='secret' WHERE id=?",(mid,))
    monkeypatch.setattr(backend,'ready',lambda:True)
    def forbidden(*_):raise AssertionError('Secret recording reached a decoder/model')
    monkeypatch.setattr(backend,'decode',forbidden);monkeypatch.setattr(backend,'Backend',forbidden)
    r=upload(env,mid);assert r.status_code==202,r.text
    job=env['prod_head'].get('/api/meet/media-jobs/'+str(r.json()['job']['id'])).json()['job']
    assert job['status']=='failed' and job['error_code']=='secret_model_denied' and job['asset_id']
    assert env['prod_head'].get(f"/api/meet/media-assets/{job['asset_id']}/audio").content==wav()
