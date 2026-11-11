"""Release tools, real handlers and frozen scorer. No live model quality claims."""
import copy
import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from scripts.track3.cleanup import cleanup
from scripts.track3.evaluate import frozen_check, score_tasks, GOLD
from scripts.track3.seed import seed
from scripts.track3.paths import explicit_db
from meetings import store, llm
from meetings.api import install

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('MEETINGS_DB_PATH',str(tmp_path/'fixture.db'))
    monkeypatch.setenv('MEETINGS_SECRET','release-test-secret')
    ids=seed(str(tmp_path/'fixture.db'))
    app=FastAPI();install(app)
    clients={}
    for user in ('irina','petr'):
        clients[user]=TestClient(app)
        assert clients[user].post('/api/meet/login',json={'login':user,'password':user+'-demo'}).status_code==200
    yield {'path':tmp_path/'fixture.db','ids':ids,**clients}
    llm.set_llm(None);store.reset_cache()


def counts():
    with store.db() as c:
        tables=['users','documents','fragments','meetings','utterances','protocols','protocol_items','tasks',
                'production_metrics','production_metric_access','calendar_busy']
        return {t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in tables}


def test_frozen_dataset_has_coverage():
    assert frozen_check()
    data=json.loads((ROOT/'demo/track3/manifest.json').read_text())
    gold=json.loads(GOLD.read_text())
    assert len(data['documents'])>=20 and len(data['meetings'])==3 and len(gold['questions'])>=15
    assert len({d['document_type'] for d in data['documents']})>=5
    assert len({d['authored_at'] for d in data['documents']})>5
    assert {t['status'] for t in data['history_tasks']}=={'open','in_progress','done'}
    for m,g in zip(data['meetings'],gold['transcripts']):
        text=(ROOT/'demo/track3/transcripts'/m['transcript']).read_text()
        assert hashlib.sha256(text.encode()).hexdigest()==g['transcript_sha256']
        assert len(g['tasks'])==6
        for t in g['tasks']: assert t['quote'] in text


def test_idempotent_seed_and_orbita_coexist(env):
    before=counts()
    assert seed(str(env['path']))==env['ids']
    assert before==counts()
    from scripts.seed_meetings_demo import seed as orbita
    orbita()
    after=counts()
    seed(str(env['path']))
    assert after==counts()
    assert env['irina'].get('/api/meet/meetings').status_code==200


def test_roles_acl_denial_audit_and_kpi(env):
    i,p=env['irina'],env['petr'];mid=env['ids']['meetings']['delay']
    assert p.get(f'/api/meet/meetings/{mid}').status_code==404
    did=env['ids']['documents']['private_budget']
    assert p.get(f'/api/meet/documents/{did}/download').status_code==404
    assert p.post('/api/meet/meetings',json={'title':'Denied'}).status_code==403
    audit=i.get('/api/meet/audit',params={'scope':'my_objects'}).json()['events']
    assert any(a['action']=='access_denied' for a in audit)
    r=i.get('/api/meet/overview',params={'as_of':'2026-11-11T12:00:00+00:00'})
    assert r.status_code==200,r.text
    metrics={m['key']:m for m in r.json()['metrics']}
    expected={'on_time_orders':90,'defect_rate':2,'capacity_utilization':75,'open_tasks':2,'overdue_tasks':1}
    assert {k:metrics[k]['value'] for k in expected}==expected
    for m in metrics.values():
        s=m['source']
        assert i.get(f"/api/meet/sources/{s['kind']}/{s['id']}").status_code==200
    assert i.get('/api/meet/sources/metric/fp-private-20261111').status_code==404


def test_task_cancel_confirm_idempotent_and_restart(env):
    i=env['irina'];task=next(t for t in i.get('/api/meet/tasks').json()['tasks'] if t['status']=='open');tid=task['id']
    preview=i.post(f'/api/meet/tasks/{tid}/preview',json={'changes':{'status':'done'}}).json()
    cid=preview['confirmation_id']
    assert i.post(f'/api/meet/confirmations/{cid}/cancel').status_code==200
    assert i.post(f'/api/meet/tasks/{tid}/confirm',json={'confirmation_id':cid,'idempotency_key':'cancelled'}).status_code==409
    assert next(t for t in i.get('/api/meet/tasks').json()['tasks'] if t['id']==tid)['status']==task['status']
    cid=i.post(f'/api/meet/tasks/{tid}/preview',json={'changes':{'status':'in_progress'}}).json()['confirmation_id']
    payload={'confirmation_id':cid,'idempotency_key':'one-operation'}
    first=i.post(f'/api/meet/tasks/{tid}/confirm',json=payload)
    assert first.status_code==200,first.text
    assert i.post(f'/api/meet/tasks/{tid}/confirm',json=payload).json()['already_confirmed'] is True
    store.reset_cache()
    assert next(t for t in i.get('/api/meet/tasks').json()['tasks'] if t['id']==tid)['status']=='in_progress'


def test_safe_cleanup_default_dry_run_and_explicit_artifacts(env,tmp_path):
    report=tmp_path/'observations.json';report.write_text('{}')
    unrelated=tmp_path/'unrelated.txt';unrelated.write_text('keep')
    assert cleanup(str(env['path']),artifacts=[str(report)])['dry_run']
    assert env['path'].exists() and report.exists()
    cleanup(str(env['path']),True,[str(report)])
    assert not env['path'].exists() and not report.exists() and unrelated.exists()


@pytest.mark.parametrize('path',['relative.db','/tmp/../tmp/track3.db'])
def test_cleanup_rejects_ambiguous_paths(path):
    with pytest.raises(ValueError): explicit_db(path)


def test_cleanup_refuses_live_and_symlinks(tmp_path):
    with pytest.raises(ValueError): explicit_db(str(ROOT/'data/meetings.db'))
    actual=tmp_path/'real.db';actual.touch()
    link=tmp_path/'link.db';link.symlink_to(actual)
    with pytest.raises(ValueError): explicit_db(str(link))
    with pytest.raises(ValueError): cleanup(str(actual),True)
    with pytest.raises(ValueError): seed(str(actual))
    assert actual.exists()


def scoring_fixture():
    tasks=json.loads(GOLD.read_text())['transcripts'][0]['tasks']
    utterances=[{'id':f'U{g["utterance_index"]}','idx':g['utterance_index'],'text':g['quote']} for g in tasks]
    predictions=[dict(kind='task',text=g['text'],assignee=g['assignee'],due=g['due'],
                      assignee_status='stated' if g['assignee'] else 'unknown',due_status='stated' if g['due'] else 'unknown',
                      quotes=[{'utterance_id':f'U{g["utterance_index"]}','text':g['quote'],'verified':True}]) for g in tasks]
    return tasks,utterances,predictions


def test_scorer_one_to_one_duplicate_false_and_wrong_owner_due():
    gold,u,p=scoring_fixture()
    assert score_tasks(gold,p,u)['recall']==1
    p.append(copy.deepcopy(p[0]))
    s=score_tasks(gold,p,u)
    assert s['recall']==1 and s['precision']==6/7 and len(s['false_or_unresolved_tasks'])==1
    p=p[:6];p[0]['assignee']='Пётр';p[1]['due']='2026-11-30'
    s=score_tasks(gold,p,u)
    assert s['recall']==4/6 and s['action_recall']==1 and len(s['owner_errors'])==len(s['due_errors'])==1


def test_scorer_rejects_fake_citation_and_routes_semantics_for_review():
    gold,u,p=scoring_fixture()
    p[0]['quotes'][0]['text']='выдуманная цитата'
    assert score_tasks(gold,p,u)['recall']==5/6
    gold,u,p=scoring_fixture()
    p[0]['text']='Уточнить статус поставщика ламината'
    s=score_tasks(gold,p,u)
    assert s['recall']==5/6 and len(s['manual_review_pending'])==1
    review=[dict(prediction_index=0,gold_id=gold[0]['id'],verdict='match',reviewer='independent evaluator',
                 reviewer_kind='independent_human',reason='Action is equivalent and exact quote identifies supplier check')]
    assert score_tasks(gold,p,u,review)['recall']==1
    p[0]['quotes'][0]['text']='forged'
    with pytest.raises(ValueError): score_tasks(gold,p,u,review)


def test_cleanup_tracks_start_files_but_rejects_tampered_marker(env,monkeypatch):
    from scripts.track3.start import configure
    import storage
    monkeypatch.setattr(storage,'DB_PATH',storage.DB_PATH)
    monkeypatch.setattr(storage,'DATA_DIR',storage.DATA_DIR)
    configure(env['path'])
    cabinet=env['path'].with_name(env['path'].stem+'.cabinet.db')
    cabinet.touch()
    unrelated=env['path'].parent/'not-owned.txt';unrelated.write_text('keep')
    marker=Path(str(env['path'])+'.track3.json')
    declared=json.loads(marker.read_text())
    assert str(cabinet) in declared['start_files']
    declared['start_files'].append(str(unrelated));marker.write_text(json.dumps(declared))
    with pytest.raises(ValueError): cleanup(str(env['path']),True)
    assert unrelated.exists() and cabinet.exists()
    declared['start_files'].remove(str(unrelated));marker.write_text(json.dumps(declared))
    cleanup(str(env['path']),True)
    assert not cabinet.exists() and unrelated.exists()


def test_summary_failed_transcript_stays_in_denominator():
    from scripts.track3.evaluate import summarize
    gold,u,p=scoring_fixture()
    score=score_tasks(gold,p,u)
    report={'transcripts':[{'scores':score},{'http_status':503},{'http_status':503}],'questions':[]}
    summarize(report)
    assert report['overall']['gold_tasks']==18 and report['overall']['recall']==6/18
    assert report['status']=='failed'


def test_scorer_weak_quote_and_wrong_duplicate_cannot_hide_correct_task():
    gold,u,p=scoring_fixture()
    p[0]['quotes'][0]['text']='12 ноября 2026 года'
    assert score_tasks(gold,p,u)['recall']==5/6
    gold,u,p=scoring_fixture()
    wrong=copy.deepcopy(p[0]);wrong['assignee']='Пётр'
    score=score_tasks(gold,[wrong]+p,u)
    assert score['recall']==1 and score['precision']==6/7
