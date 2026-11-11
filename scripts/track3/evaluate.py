"""Explicit real Ollama evaluation. No fixture provider; no LLM-as-judge.

Exit 0: all gates pass. 1: observed failure/review pending. 2: not run or unavailable.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
GOLD = ROOT/'evaluation/track3/gold.json'


def norm(text):
    return ' '.join(re.findall(r'[\w]+', (text or '').casefold().replace('ё','е')))


def frozen_check():
    hashes = json.loads((ROOT/'evaluation/track3/frozen.json').read_text())
    for name, digest in hashes.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen dataset changed: '+name)
    return hashlib.sha256(GOLD.read_bytes()).hexdigest()


def score_tasks(gold, predictions, utterances, reviews=()):
    """Conservative one-to-one exact evidence/alternative matching, with independent review.

    Extraction recall requires the correct action, owner and date. action_recall is
    also reported. A substring in an unrelated source or a model's verified flag is
    insufficient: quote must be in storage and overlap the gold action's citation.
    """
    actual = [p for p in predictions if p.get('kind')=='task']
    source = {u['id']:u for u in utterances}
    index = {u['idx']:u['id'] for u in utterances}
    review_map = {r['prediction_index']:r for r in reviews}
    edges, grounded, uncertain = {}, {}, []
    for i,p in enumerate(actual):
        quotes = [q for q in p.get('quotes',[]) if q.get('text') and q.get('utterance_id') in source
                  and q['text'] in source[q['utterance_id']]['text']]
        grounded[i] = bool(quotes)
        evidence = [g for g in gold if any(q['utterance_id']==index.get(g['utterance_index'])
                    and (q['text'] in g['quote'] or g['quote'] in q['text']) for q in quotes)]
        candidates = [g for g in evidence if any(norm(a) in norm(p.get('text')) for a in g['alternatives'])]
        r = review_map.get(i)
        if r:
            if not r.get('reviewer') or not r.get('reason') or r.get('reviewer_kind')!='independent_human':
                raise ValueError('Manual review requires independent_human, reviewer and reason')
            if r.get('verdict')=='match':
                candidates = [g for g in evidence if g['id']==r.get('gold_id')]
                if not candidates:
                    raise ValueError('Review cannot bypass source evidence')
            elif r.get('verdict')=='false_positive':
                candidates = []
            else:
                raise ValueError('Review verdict must be match or false_positive')
        elif evidence and not candidates:
            uncertain.append({'prediction_index':i,'gold_candidates':[g['id'] for g in evidence],
                              'reason':'Wording outside frozen alternatives; independent human review required'})
        edges[i] = [g['id'] for g in candidates]
    # Maximum bipartite matching: an alternative collision must not greedily lower recall.
    matched = {}
    def augment(i,seen):
        for gid in edges[i]:
            if gid in seen: continue
            seen.add(gid)
            if gid not in matched or augment(matched[gid],seen):
                matched[gid]=i
                return True
        return False
    for i in edges: augment(i,set())
    by_id={g['id']:g for g in gold}
    owner_errors, due_errors, pairs = [], [], []
    correct=0
    for gid,i in matched.items():
        g,p=by_id[gid],actual[i]
        owner_ok=norm(p.get('assignee'))==norm(g.get('assignee'))
        due_ok=(p.get('due') or None)==g.get('due')
        if g.get('due') is None:
            due_ok=due_ok and not p.get('due_text') and p.get('due_status','unknown')=='unknown'
        if g.get('assignee') is None:
            owner_ok=owner_ok and p.get('assignee_status','unknown')=='unknown'
        if not owner_ok: owner_errors.append({'gold_id':gid,'prediction_index':i,'expected':g.get('assignee'),'actual':p.get('assignee')})
        if not due_ok: due_errors.append({'gold_id':gid,'prediction_index':i,'expected':g.get('due'),'actual':p.get('due'),'due_text':p.get('due_text')})
        correct += owner_ok and due_ok
        pairs.append({'gold_id':gid,'prediction_index':i,'owner_ok':owner_ok,'due_ok':due_ok})
    unmatched=[{'prediction_index':i,'prediction':p} for i,p in enumerate(actual) if i not in matched.values()]
    return dict(gold_tasks=len(gold), predicted_tasks=len(actual), correct_tasks=correct,
                recall=correct/len(gold) if gold else None,
                precision=correct/len(actual) if actual else 0.0,
                action_recall=len(matched)/len(gold) if gold else None,
                action_precision=len(matched)/len(actual) if actual else 0.0,
                source_support=sum(grounded.values())/len(actual) if actual else 0.0,
                matched=pairs, false_or_unresolved_tasks=unmatched, owner_errors=owner_errors,due_errors=due_errors,
                manual_review_pending=uncertain, missing_gold_ids=[g['id'] for g in gold if g['id'] not in matched])


def model_info(model):
    import httpx
    from providers.ollama import endpoint, LOOPBACK
    from urllib.parse import urlsplit
    target=endpoint()
    if not target: raise ValueError('No allowed Ollama endpoint')
    base,headers=target
    with httpx.Client(trust_env=False,follow_redirects=False,timeout=5) as c:
        v=c.get(base+'/api/version',headers=headers);v.raise_for_status()
        tags=c.get(base+'/api/tags',headers=headers);tags.raise_for_status()
    selected=next((t for t in tags.json().get('models',[]) if t.get('name')==model or t.get('model')==model),None)
    if not selected: raise ValueError('Requested exact model not installed on host')
    return dict(model=model,ollama_version=v.json().get('version'),model_digest=selected.get('digest'),
                model_size_bytes=selected.get('size'),remote_gateway=urlsplit(base).hostname not in LOOPBACK)


def qa_result(client,case):
    r=client.post('/api/meet/qa',json={'question':case['question']})
    result=r.json()
    checks=[r.status_code==200,result.get('status')==case['expected_status']]
    opened=[]
    for claim in result.get('claims',[]):
        for s in claim.get('sources',[]):
            f=client.get('/api/meet/fragments/'+s['id'])
            if f.status_code!=200:
                checks.append(False);continue
            fragment=f.json()['fragment']
            d=client.get('/api/meet/documents/'+str(fragment['document_id']))
            filename=d.json().get('document',{}).get('filename') if d.status_code==200 else None
            checks += [s['quote'] in fragment['text'],bool(s.get('source_at'))]
            opened.append({'filename':filename,'quote':s['quote']})
    answer=' '.join(c.get('text','') for c in result.get('claims',[]))
    # Every grounded claim must have a live resolvable source, no bare model assertions.
    if result.get('status')=='grounded':
        checks += [bool(opened),bool(result.get('claims')),all(c.get('sources') for c in result.get('claims',[]))]
    for name in case['expected_document_filenames']: checks.append(any(s['filename']==name for s in opened))
    for q in case['expected_quote_substrings']: checks.append(any(q in s['quote'] for s in opened))
    for forbidden in case['forbidden_substrings']: checks.append(forbidden not in json.dumps(result,ensure_ascii=False))
    return dict(passed=all(checks),http_status=r.status_code,response=result,resolved_sources=opened)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,help='Absolute report path')
    p.add_argument('--exclusive-gpu-window',action='store_true',help='Operator confirms agreed window without competing inference')
    p.add_argument('--review-file',help='Independent human review bound to predictions_sha256')
    a=p.parse_args()
    out=Path(a.output)
    if not out.is_absolute(): p.error('--output must be absolute')
    report=dict(status='not_run',started_at=datetime.now(timezone.utc).isoformat(),run_id=uuid.uuid4().hex,
                commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
                dataset_sha256=frozen_check(),dataset='photoprint-v1',judge='frozen deterministic rules + independent human review',
                configured_model=os.getenv('MEETINGS_MODEL','qwen2.5:7b'), model_metadata_status='not_run',
                parameters=dict(context=int(os.getenv('MEETINGS_CONTEXT','8192')),timeout=float(os.getenv('MEETINGS_TIMEOUT','300')),
                                temperature=0.1,think=False,stream=False,num_predict_protocol=1800),transcripts=[],questions=[])
    try:
        from meetings import llm
        provider=llm.MeetingLLM()
        # Validate cloud refusal before any network request.
        provider._base()
        report['stage']='model_metadata'
        report['model']=model_info(provider.model)
        report['model_metadata_status']='observed'
        if not a.exclusive_gpu_window:
            raise ValueError('An agreed exclusive GPU window is required; no extraction was run')
        report['exclusive_gpu_window_confirmed']=True
        report['stage']='extraction_and_qa'
        gold=json.loads(GOLD.read_text())
        with tempfile.TemporaryDirectory(prefix='track3-live-') as temp:
            os.environ['MEETINGS_SECRET']='synthetic-live-evaluation-secret'
            from scripts.track3.seed import seed
            ids=seed(str(Path(temp)/'live.db'))
            # Exercise product meetings handlers without importing main cabinet or voice services.
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from meetings.api import install
            from meetings import store
            app=FastAPI();install(app);llm.set_llm(provider)
            clients={}
            for who in ('irina','petr'):
                c=TestClient(app);r=c.post('/api/meet/login',json={'login':who,'password':who+'-demo'})
                r.raise_for_status();clients[who]=c
            for control in gold['transcripts']:
                mid=ids['meetings'][control['key']]
                before=time.perf_counter()
                r=clients['irina'].post(f'/api/meet/meetings/{mid}/protocol/draft')
                latency=time.perf_counter()-before
                item=dict(key=control['key'],latency_seconds=latency,http_status=r.status_code,response=r.json())
                if r.status_code==200:
                    predictions=r.json()['protocol']['items']
                    with store.db() as c: utterances=store.utterances(c,mid)
                    item.update(predictions=predictions,utterances=utterances)
                report['transcripts'].append(item)
            report['predictions_sha256']=hashlib.sha256(json.dumps(report['transcripts'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            reviews={}
            if a.review_file:
                review=json.loads(Path(a.review_file).read_text())
                if review['predictions_sha256']!=report['predictions_sha256']:
                    raise ValueError('Review belongs to different predictions; use score_report.py for an existing report')
                reviews=review.get('transcripts',{})
            for item,control in zip(report['transcripts'],gold['transcripts']):
                if item['http_status']==200:
                    item['scores']=score_tasks(control['tasks'],item['predictions'],item['utterances'],reviews.get(item['key'],[]))
            for case in gold['questions']:
                before=time.perf_counter()
                report['questions'].append(dict(case=case,latency_seconds=None,**qa_result(clients[case['user_login']],case)))
                report['questions'][-1]['latency_seconds']=time.perf_counter()-before
            summarize(report)
    except Exception as e:
        # Do not persist raw exception strings: HTTP errors may contain credential-bearing URLs.
        report.update(status='not_run' if not report['transcripts'] else 'failed',
                      blocker_type=type(e).__name__,blocker='Model, exclusive window or evaluation prerequisite unavailable; inspect local configuration. No success claimed.')
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'report':str(out),'model':report.get('model'),'overall':report.get('overall')},ensure_ascii=False))
    return 0 if report['status']=='passed' else 2 if report['status']=='not_run' else 1


def summarize(report):
    scores=[t['scores'] for t in report['transcripts'] if 'scores' in t]
    expected=len(json.loads(GOLD.read_text())['transcripts'])
    gold=sum(len(t['tasks']) for t in json.loads(GOLD.read_text())['transcripts'])
    predicted=sum(s['predicted_tasks'] for s in scores)
    correct=sum(s['correct_tasks'] for s in scores)
    recall=correct/gold if gold else 0.0
    report['overall']=dict(recall=recall,precision=correct/predicted if predicted else 0.0,
                           correct_tasks=correct,gold_tasks=gold,predicted_tasks=predicted,
                           owner_errors=sum(len(s['owner_errors']) for s in scores),
                           due_errors=sum(len(s['due_errors']) for s in scores),
                           false_or_unresolved_tasks=sum(len(s['false_or_unresolved_tasks']) for s in scores))
    complete=len(scores)==expected
    passed=complete and recall>=0.8 and all(s['recall']>=0.8 and not s['manual_review_pending'] for s in scores)
    passed=passed and len(report['questions'])==len(json.loads(GOLD.read_text())['questions']) and all(q['passed'] for q in report['questions'])
    report['status']='passed' if passed else 'failed'


if __name__=='__main__':
    raise SystemExit(main())
