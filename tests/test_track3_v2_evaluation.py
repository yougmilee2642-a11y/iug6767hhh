"""Frozen controls and an explicit double must never masquerade as live quality."""
from copy import deepcopy
import hashlib
import json
import shutil
import pytest
from scripts.track3 import evaluate, evaluate_v2 as v2


@pytest.fixture(scope='module')
def pipeline_report(tmp_path_factory):
    from meetings import llm
    report=evaluate.initial_report()
    # Any attempt to reach Ollama in the double path is a test failure.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(llm,'MeetingLLM',lambda *a,**k:pytest.fail('Real model constructed'))
        patch.setattr(evaluate,'model_info',lambda *a,**k:pytest.fail('Model endpoint contacted'))
        v2.run_evaluation(report,False,lambda r:None,scripted_double=True)
    return report


def test_frozen_sizes_categories_and_call():
    gold=json.loads(v2.GOLD.read_text())
    assert v2.frozen_check()==hashlib.sha256(v2.GOLD.read_bytes()).hexdigest()
    assert len(gold['transcripts'])==5
    assert sum(len(t['tasks']) for t in gold['transcripts'])==30
    assert len(gold['questions'])==36
    for tag,minimum in [('acl_negative',6),('no_data',4),('injection',4),('stale',3)]:
        assert sum(tag in q['tags'] for q in gold['questions'])>=minimum
    assert gold['call_control']['transcript_key']=='call_defect'


def test_double_full_pipeline_is_not_a_model_pass(pipeline_report):
    r=pipeline_report
    assert r['status']=='pipeline_passed' and r['execution_kind']=='scripted_double'
    assert r['quality_status'].startswith('not_measured')
    assert r['model']['ollama_version'] is None and r['model_metadata_status']!='observed'
    assert r['overall']['correct_tasks']==30 and r['overall']['recall']==1
    assert r['overall']['precision']==1 and r['overall']['rights_violations']==0 and r['overall']['false_actions']==0
    assert len(r['questions'])==36 and all(q['passed'] for q in r['questions'])
    assert all(item['scores']['recall']==1 for item in r['transcripts'])
    assert r['call_control']['E7_call_analytics']=='not_run'


def test_missing_window_blocks_before_any_model_construction(monkeypatch):
    from meetings import llm
    monkeypatch.setattr(llm,'MeetingLLM',lambda *a,**k:pytest.fail('Real model constructed'))
    report=evaluate.initial_report();report['dirty']=False
    with pytest.raises(evaluate.EvaluationBlocked,match='exclusive_gpu_window_not_confirmed'):
        v2.run_evaluation(report,False,lambda r:None)
    assert report['status']=='not_run' and report['model_metadata_status']=='not_run'


def test_tampered_dataset_is_rejected(tmp_path,monkeypatch):
    hashes=json.loads(v2.FROZEN.read_text())
    for name in hashes:
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(v2.ROOT/name,target)
    monkeypatch.setattr(v2,'ROOT',tmp_path)
    path=tmp_path/'demo/track3/transcripts/call_defect.txt'
    path.write_text(path.read_text()+'\nНовая строка')
    with pytest.raises(evaluate.EvaluationBlocked,match='frozen_v2_dataset_changed'):v2.frozen_check()


def test_roster_identity_is_exact_and_duplicate_is_not_double_credit(pipeline_report):
    r=deepcopy(pipeline_report); item=r['transcripts'][0]
    control=json.loads(v2.GOLD.read_text())['transcripts'][0]
    p=item['predictions']; anna=next(x for x in p if (x.get('assignee') or '').startswith('Анна'))
    assert anna['assignee']=='Анна Морозова'
    extra=deepcopy(anna);extra['assignee']='Анна Выдуманная'
    score=v2.score_control(control,p+[deepcopy(anna),extra],item['utterances'])
    assert score['correct_tasks']==6 and score['predicted_tasks']==8 and score['precision']==.75
    assert len(score['false_or_unresolved_tasks'])==2
    wrong=deepcopy(p);wrong[0]['assignee']='Чужой исполнитель'
    score=v2.score_control(control,wrong,item['utterances'])
    assert score['recall']<1 and score['owner_errors']


def test_partial_or_spoofed_live_report_fails(pipeline_report):
    partial=deepcopy(pipeline_report);partial['transcripts'].pop()
    v2.summarize(partial)
    assert partial['status']=='failed' and 'missing_transcripts' in partial['evaluation_integrity']['issues']
    fake=deepcopy(pipeline_report);fake['execution_kind']='live_model'
    v2.summarize(fake)
    assert fake['status']=='failed' and 'unverified_model_or_gpu_window' in fake['evaluation_integrity']['issues']
    changed=deepcopy(pipeline_report);changed['questions'][0]['response']['answer']='Подменено'
    v2.summarize(changed)
    assert changed['status']=='failed' and 'qa_observations_hash_mismatch' in changed['evaluation_integrity']['issues']


def test_human_review_is_bound_to_observations_and_cannot_create_evidence(pipeline_report):
    report=deepcopy(pipeline_report)
    review={'predictions_sha256':report['predictions_sha256'],'transcripts':{}}
    v2.rescore(report,review)
    assert report['status']=='pipeline_passed' and report['quality_status'].startswith('not_measured')
    bad=deepcopy(review);bad['predictions_sha256']='0'*64
    with pytest.raises(ValueError,match='hash mismatch'):v2.rescore(deepcopy(report),bad)
    bad=deepcopy(review);bad['transcripts']={'delay':[{'prediction_index':0,'verdict':'match','gold_id':'delay-1',
        'reviewer':'Same model','reviewer_kind':'model','reason':'looks right'}]}
    with pytest.raises(ValueError,match='independent_human'):v2.rescore(deepcopy(report),bad)


def test_cli_double_preserves_report_and_labels_quality(tmp_path):
    import subprocess,sys
    path=tmp_path/'observed.json'
    command=[sys.executable,str(v2.ROOT/'scripts/track3/evaluate.py'),'--dataset','photoprint-v2','--scripted-double','--output',str(path)]
    result=subprocess.run(command,cwd=v2.ROOT,capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stderr+result.stdout
    report=json.loads(path.read_text())
    assert report['status']=='pipeline_passed' and report['quality_status'].startswith('not_measured')
    original=path.read_bytes()
    again=subprocess.run(command,cwd=v2.ROOT,capture_output=True,text=True,timeout=15)
    assert again.returncode!=0 and path.read_bytes()==original
