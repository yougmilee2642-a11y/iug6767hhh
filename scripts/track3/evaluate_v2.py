"""Frozen photoprint-v2 evaluation. Doubles test plumbing, never model quality."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from scripts.track3 import evaluate as base

ROOT=base.ROOT
GOLD=ROOT/'evaluation/track3/v2/gold.json'
FROZEN=GOLD.with_name('frozen.json')
VERSION=1


def frozen_check():
    base.frozen_check()
    for name,expected in json.loads(FROZEN.read_text(encoding='utf-8')).items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise base.EvaluationBlocked('frozen_v2_dataset_changed')
    return hashlib.sha256(GOLD.read_bytes()).hexdigest()


@contextmanager
def environment(**values):
    previous={key:os.environ.get(key) for key in values}
    try:
        for key,value in values.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value
        yield
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value


def identities(key):
    """Only exact unique roster names present in this control's participants.

    Source 'Анна' and roster 'Анна Морозова' are the same stated employee.
    Never fuzzy-match an invented surname or choose between two namesakes.
    """
    fixture=json.loads((ROOT/'demo/track3/v2/manifest.json').read_text(encoding='utf-8'))
    meeting=next(m for m in fixture['meetings'] if m['key']==key)
    names=[u['name'] for u in fixture['users'] if u['login'] in [meeting['owner'],*meeting['access']]]
    first={base.norm(name.split()[0]) for name in names}
    return {base.norm(name):name.split()[0] for name in names
            if sum(base.norm(other.split()[0])==base.norm(name.split()[0]) for other in names)==1
            and base.norm(name.split()[0]) in first}


def score_control(control,predictions,utterances,reviews=()):
    aliases=identities(control['key']); canonical=deepcopy(predictions)
    for prediction in canonical:
        owner=base.norm(prediction.get('assignee'))
        if owner in aliases: prediction['assignee']=aliases[owner]
    score=base.score_tasks(control['tasks'],canonical,utterances,reviews)
    score['exact_roster_aliases']=aliases
    return score


class ScriptedDouble:
    """Explicit oracle fixtures to test API/validators/scoring, not an extractor.

    It can only return golden tasks whose literal quote is present in the prompt,
    or select offered excerpts containing the fixed expected text. It cannot read
    hidden database rows. Do not cite these metrics as model measurements.
    """
    model='scripted-photoprint-v2-double'

    def __init__(self,gold): self.gold=gold

    def json(self,system,user,schema,predict=1500):
        from meetings import extract
        from meetings.knowledge import service
        if system==extract.PROTOCOL_SYSTEM:
            lines={text:uid for uid,text in re.findall(r'^(U\d+) \| [^:]+: (.+)$',user,re.M)}
            tasks=[]
            for control in self.gold['transcripts']:
                for task in control['tasks']:
                    if task['quote'] not in lines: continue
                    due=task['quote'].rsplit('до ',1)[-1].rstrip('.') if task['due'] else ''
                    tasks.append({'kind':'task','text':task['text'],'outcome':'none','assignee':task['assignee'] or '',
                                  'due_text':due,'utterance_ids':[lines[task['quote']]],'quote':task['quote']})
            return {'items':tasks}
        if system==extract.CANDIDATE_SYSTEM:
            return {'kind':'none','text':'','outcome':'none','assignee':'','due_text':''}
        if system==extract.SUMMARY_SYSTEM: return {'claims':[]}
        if system==service.SYSTEM:
            prompt=json.loads(user)
            case=next((q for q in self.gold['questions'] if q['kind']=='qa' and base.norm(q['question'])==base.norm(prompt['question'])),None)
            if not case: raise AssertionError('Unknown scripted QA fixture')
            if case['expected_status']!='grounded': return {'excerpt_ids':[]}
            expected=case['expected_quote_substrings']
            choices=[item['excerpt_id'] for doc in prompt['untrusted_documents'] for item in doc['excerpts']
                     if all(text in item['text'] for text in expected)]
            return {'excerpt_ids':choices[:1]}
        raise AssertionError('Unexpected model stage in v2 double')


class Observed:
    def __init__(self,provider,report): self.provider,self.report,self.model=provider,report,provider.model

    def json(self,system,user,schema,predict=1500):
        record={'stage':self.report['stage'],'predict':predict,'schema_sha256':hashlib.sha256(
            json.dumps(schema,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
        self.report['llm_calls'].append(record); started=time.perf_counter()
        try:
            value=self.provider.json(system,user,schema,predict=predict)
            record['status']='ok';return value
        except Exception as error:
            record.update(status='error',error_code=getattr(error,'code',type(error).__name__));raise
        finally: record['latency_seconds']=time.perf_counter()-started


def mutation_fingerprint():
    from meetings import store
    # Results/drafts/QA/audit are expected writes. Confirmed business state is not.
    tables=['tasks','calendar_events','calendar_outbox','integration_outbox','mock_crm_objects','users','documents','utterances','decision_controls']
    with store.db() as c:
        values={table:[dict(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in tables}
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def source_check(client,result):
    checks=[];claims=result.get('claims',[])
    for claim in claims:
        valid=bool(claim.get('sources'))
        for source in claim.get('sources',[]):
            fid=source.get('id','')
            if source.get('kind')!='document' or not re.fullmatch('F[0-9]+',fid): valid=False;continue
            response=client.get('/api/meet/fragments/'+fid)
            if response.status_code!=200: valid=False;continue
            fragment=response.json()['fragment']; quote=source.get('quote')
            valid=valid and quote==claim.get('text') and isinstance(quote,str) and base.complete_excerpt(quote,fragment['text'])
            document=client.get('/api/meet/documents/'+str(fragment['document_id']))
            try:
                at=datetime.fromisoformat(source['source_at']);uploaded=datetime.fromisoformat(document.json()['document']['created_at'])
                valid=valid and document.status_code==200 and at.tzinfo is not None and uploaded.tzinfo is not None and at==uploaded
            except (KeyError,TypeError,ValueError): valid=False
        checks.append(bool(valid))
    return {'claims':len(checks),'supported_claims':sum(checks),'all_supported':all(checks)}


def question_result(client,case):
    if case['kind']=='overview':
        response=client.get('/api/meet/overview',params={'as_of':case['as_of']});result=response.json()
        checks=[response.status_code==case['expected_http_status']]
        metrics={m['key']:m for m in result.get('metrics',[])};opened=[]
        for key,value in case['expected_metrics'].items():
            metric=metrics.get(key,{})
            checks += [metric.get('value')==value,metric.get('source',{}).get('kind') in case['expected_source_kinds']]
            source=metric.get('source',{})
            if source.get('id'):
                proof=client.get('/api/meet/sources/metric/'+source['id'])
                checks.append(proof.status_code==200)
                opened.append({'source':source,'http_status':proof.status_code})
            else: checks.append(False)
        checks.append(any(case['expected_warning'] in warning for warning in result.get('warnings',[])))
        return {'passed':all(checks),'http_status':response.status_code,'response':result,'resolved_sources':opened,
                'source_integrity':{'claims':len(opened),'supported_claims':sum(o['http_status']==200 for o in opened)},'rights_violation':False}
    if case['expected_http_status']!=200:
        response=client.post('/api/meet/qa',json={'question':case['question']});result=response.json()
        safe=all(value not in json.dumps(result,ensure_ascii=False) for value in case['forbidden_substrings'])
        return {'passed':response.status_code==case['expected_http_status'] and safe,'http_status':response.status_code,
                'response':result,'resolved_sources':[],'source_integrity':{'claims':0,'supported_claims':0},
                'rights_violation':response.status_code==200 or not safe}
    result=base.qa_result(client,case)
    raw=result['response'];proof=source_check(client,raw)
    if case['expected_status']=='refused': result['passed']=result['passed'] and not raw.get('claims') and not raw.get('sources') and raw.get('model') is None
    result['source_integrity']=proof
    result['rights_violation']='acl_negative' in case['tags'] and (bool(raw.get('claims')) or bool(raw.get('sources'))
        or any(value in json.dumps(raw,ensure_ascii=False) for value in case['forbidden_substrings']))
    return result


def questions_digest(report):
    return hashlib.sha256(json.dumps(report['questions'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def summarize(report):
    gold=json.loads(GOLD.read_text(encoding='utf-8'));issues=[]
    controls={c['key']:c for c in gold['transcripts']};actual={}
    for item in report['transcripts']:
        key=item.get('key')
        if key not in controls or key in actual: issues.append('unknown_or_duplicate_transcript');continue
        actual[key]=item
        if item.get('http_status')!=200 or item.get('transcript_sha256')!=controls[key]['transcript_sha256']:
            issues.append('incomplete_or_inconsistent_transcript')
        if item.get('scores',{}).get('gold_tasks')!=len(controls[key]['tasks']): issues.append('inconsistent_task_denominator')
    if set(actual)!=set(controls): issues.append('missing_transcripts')
    scores=[item['scores'] for item in actual.values() if 'scores' in item]
    gold_count=sum(len(c['tasks']) for c in controls.values());correct=sum(s['correct_tasks'] for s in scores);predicted=sum(s['predicted_tasks'] for s in scores)
    qexpected={q['id']:q for q in gold['questions']};qactual={}
    for item in report['questions']:
        case=item.get('case',{});key=case.get('id')
        if key not in qexpected or key in qactual or case!=qexpected.get(key): issues.append('missing_changed_or_duplicate_qa_cases')
        qactual[key]=item
    if set(qactual)!=set(qexpected): issues.append('missing_changed_or_duplicate_qa_cases')
    if report.get('dataset_sha256')!=frozen_check(): issues.append('dataset_changed')
    if report.get('predictions_sha256')!=base.predictions_digest(report): issues.append('predictions_hash_mismatch')
    if report.get('questions_sha256')!=questions_digest(report): issues.append('qa_observations_hash_mismatch')
    live=report.get('execution_kind')=='live_model'
    if live:
        if (report.get('model_metadata_status')!='observed' or not report.get('model',{}).get('ollama_version')
            or not report.get('model',{}).get('model_digest') or report.get('exclusive_gpu_window_confirmed') is not True):
            issues.append('unverified_model_or_gpu_window')
    elif report.get('execution_kind')!='scripted_double' or report.get('model_metadata_status')!='scripted_double': issues.append('invalid_execution_kind')
    if report.get('blocker') or report.get('status') in ('not_run','interrupted'): issues.append('unfinished_evaluation')
    claims=sum(q.get('source_integrity',{}).get('claims',0) for q in report['questions'])
    supported=sum(q.get('source_integrity',{}).get('supported_claims',0) for q in report['questions'])
    refusals=[q for q in report['questions'] if q.get('case',{}).get('expected_status') in ('refused','insufficient_data') or q.get('case',{}).get('expected_http_status')==403]
    report['overall']={'recall':correct/gold_count,'precision':correct/predicted if predicted else 0.,
        'correct_tasks':correct,'gold_tasks':gold_count,'predicted_tasks':predicted,
        'owner_errors':sum(len(s['owner_errors']) for s in scores),'due_errors':sum(len(s['due_errors']) for s in scores),
        'false_or_unresolved_tasks':sum(len(s['false_or_unresolved_tasks']) for s in scores),
        'source_supported_claims':supported,'claims':claims,'claims_source_fraction':supported/claims if claims else None,
        'honest_refusal_fraction':sum(q['passed'] for q in refusals)/len(refusals) if refusals else None,
        'rights_violations':sum(bool(q.get('rights_violation')) for q in report['questions']),
        'false_actions':sum(bool(q.get('unexpected_mutation')) for q in report['questions'])+bool(report.get('protocol_unexpected_mutation'))}
    report['evaluation_integrity']={'passed':not issues,'issues':sorted(set(issues))}
    passed=(not issues and len(scores)==5 and all(s['recall']>=.8 and not s['manual_review_pending'] for s in scores)
            and report['overall']['recall']>=.8 and len(qactual)==len(qexpected) and all(q['passed'] for q in qactual.values())
            and not report['overall']['rights_violations'] and not report['overall']['false_actions'])
    report['quality_status']=('measured' if 'unverified_model_or_gpu_window' not in issues and scores else 'not_measured; no verified live observations') if live else 'not_measured; scripted fixture responses'
    report['status']=('passed' if live else 'pipeline_passed') if passed else 'failed'
    call=actual.get(gold['call_control']['transcript_key'],{})
    report['call_control']={'kind':'text_task_extraction','recall':call.get('scores',{}).get('recall'),
                            'audio_asr_diarization':'not_run','E7_call_analytics':'not_run'}


def run_evaluation(report,exclusive_window,checkpoint,*,scripted_double=False):
    report.update(dataset='photoprint-v2',schema_version=3,evaluator_version=VERSION,task_scorer_version=base.SCORER_VERSION,
                  execution_kind='scripted_double' if scripted_double else 'live_model',stage='dataset_integrity',
                  quality_status='not_measured',dataset_sha256=frozen_check())
    report['gold_commit']=subprocess.check_output(['git','log','-1','--format=%H','--',str(GOLD.relative_to(ROOT))],cwd=ROOT,text=True).strip()
    report['evaluator_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    gold=json.loads(GOLD.read_text(encoding='utf-8'));report['parameters']=base.load_configuration()
    if scripted_double:
        provider=ScriptedDouble(gold);report['model_metadata_status']='scripted_double'
        report['model']={'model':provider.model,'fixture_sha256':report['dataset_sha256'],'ollama_version':None}
    else:
        if report['dirty']: raise base.EvaluationBlocked('dirty_checkout_commit_changes_first')
        if not exclusive_window: raise base.EvaluationBlocked('exclusive_gpu_window_not_confirmed')
        report['exclusive_gpu_window_confirmed']=True
        from meetings.llm import MeetingLLM
        provider=MeetingLLM();provider._base();report['stage']='model_metadata'
        report['model']=base.model_info(provider.model);report['model_metadata_status']='observed'
    report['status']='running';checkpoint(report)
    report['configured_model']=provider.model
    from meetings import llm,store
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from meetings.api import install
    from scripts.track3.seed_fotoprint import seed
    with tempfile.TemporaryDirectory(prefix='photoprint-v2-eval-') as temporary, environment(
        MEETINGS_SECRET='synthetic-v2-evaluation-only',MEETINGS_DB_PATH=str(Path(temporary)/'evaluation.db'),MOCK_CRM_FAULT=None):
        report['stage']='seed';ids=seed(str(Path(temporary)/'evaluation.db'));app=FastAPI();install(app)
        clients={};llm.set_llm(Observed(provider,report))
        try:
            for login in sorted({'prod_head',*(q['user_login'] for q in gold['questions'])}):
                client=TestClient(app);clients[login]=client
                client.post('/api/meet/login',json={'login':login,'password':login+'-demo'}).raise_for_status()
            before=mutation_fingerprint()
            for control in gold['transcripts']:
                report['stage']='protocol:'+control['key'];mid=ids['meetings'][control['key']];started=time.perf_counter()
                response=clients['prod_head'].post(f'/api/meet/meetings/{mid}/protocol/draft')
                item={'key':control['key'],'latency_seconds':time.perf_counter()-started,'http_status':response.status_code,
                      'response':response.json(),'transcript_sha256':control['transcript_sha256']}
                if response.status_code==200:
                    item['predictions']=response.json()['protocol']['items']
                    with store.db() as c: item['utterances']=store.utterances(c,mid)
                    item['scores']=score_control(control,item['predictions'],item['utterances'])
                report['transcripts'].append(item);checkpoint(report)
            report['protocol_unexpected_mutation']=before!=mutation_fingerprint()
            report['predictions_sha256']=base.predictions_digest(report)
            for case in gold['questions']:
                report['stage']='qa:'+case['id'];started=time.perf_counter();before=mutation_fingerprint()
                with environment(MOCK_CRM_FAULT=case.get('mock_crm_fault')):
                    result=question_result(clients[case['user_login']],case)
                changed=before!=mutation_fingerprint()
                result['passed']=result['passed'] and not changed
                report['questions'].append({'case':case,'latency_seconds':time.perf_counter()-started,
                                            'unexpected_mutation':changed,**result});checkpoint(report)
            report['questions_sha256']=questions_digest(report)
            report['stage']='scoring';summarize(report)
        finally:
            for client in clients.values(): client.close()
            llm.set_llm(None);store.reset_cache()


def rescore(report,review):
    """Independent human decisions cannot bypass quotes, dataset or observation hashes."""
    if report.get('status') not in ('passed','failed','pipeline_passed'):
        raise ValueError('Cannot score incomplete v2 observations')
    if report.get('schema_version')!=3 or report.get('evaluator_version')!=VERSION or report.get('task_scorer_version')!=base.SCORER_VERSION:
        raise ValueError('Different v2 schema/evaluator; preserve original evidence')
    if report.get('dataset_sha256')!=frozen_check(): raise ValueError('V2 dataset differs from observations')
    digest=base.predictions_digest(report)
    if report.get('predictions_sha256')!=digest or review.get('predictions_sha256')!=digest:
        raise ValueError('Predictions hash mismatch')
    if report.get('questions_sha256')!=questions_digest(report): raise ValueError('QA observations hash mismatch')
    controls={c['key']:c for c in json.loads(GOLD.read_text(encoding='utf-8'))['transcripts']}
    if set(review.get('transcripts',{}))-set(controls): raise ValueError('Unknown transcript key in review')
    for item in report['transcripts']:
        if item['http_status']==200:
            item['scores']=score_control(controls[item['key']],item['predictions'],item['utterances'],review.get('transcripts',{}).get(item['key'],[]))
    report['independent_review']=review
    summarize(report)
