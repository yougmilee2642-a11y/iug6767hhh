"""Explicit real Ollama evaluation. No fixture provider; no LLM-as-judge.

Exit 0: all gates pass. 1: observed failure/review pending. 2: not run or unavailable.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
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
from scripts.track3.reporting import ReportFile

GOLD = ROOT/'evaluation/track3/gold.json'
SCORER_VERSION = 2


def norm(text):
    return ' '.join(re.findall(r'[\w]+', (text or '').casefold().replace('ё','е')))


def frozen_check():
    hashes = json.loads((ROOT/'evaluation/track3/frozen.json').read_text(encoding='utf-8'))
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
    review_map = {}
    for review in reviews:
        i = review.get('prediction_index')
        if type(i) is not int or not 0 <= i < len(actual) or i in review_map:
            raise ValueError('Review prediction index is invalid or duplicated')
        review_map[i] = review
    edges, grounded, uncertain = {}, {}, []
    for i,p in enumerate(actual):
        quotes = [q for q in p.get('quotes',[]) if q.get('text') and q.get('utterance_id') in source
                  and q['text'] in source[q['utterance_id']]['text']]
        grounded[i] = bool(quotes)
        evidence = [g for g in gold if any(q['utterance_id']==index.get(g['utterance_index'])
                    and source[q['utterance_id']]['text'].strip() == g['quote'].strip()
                    and (q['text'] in g['quote'] or g['quote'] in q['text'])
                    and any(norm(a) in norm(q['text']) for a in g['alternatives']) for q in quotes)]
        wording = lambda text: ' '.join((text or '').casefold().replace('ё', 'е').split()).removesuffix('.')
        candidates = [g for g in evidence if wording(p.get('text')) in
                      {wording(g['text']), *(wording(a) for a in g['alternatives'])}]
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
    # Prefer strictly correct predictions before counting action-only matches. A wrong
    # duplicate encountered first must not hide a later correct prediction.
    by_id={g['id']:g for g in gold}
    def fields_ok(g,p):
        owner_ok=norm(p.get('assignee'))==norm(g.get('assignee'))
        due_ok=(p.get('due') or None)==g.get('due')
        if g.get('due') is not None:
            due_ok = due_ok and p.get('due_status') == 'stated'
        if g.get('assignee') is not None:
            owner_ok = owner_ok and p.get('assignee_status') == 'stated'
        if g.get('due') is None:
            due_ok=due_ok and not p.get('due_text') and p.get('due_status','unknown')=='unknown'
        if g.get('assignee') is None:
            owner_ok=owner_ok and p.get('assignee_status','unknown')=='unknown'
        return owner_ok,due_ok
    def matching(candidates):
        assigned={}
        def augment(i,seen):
            for gid in candidates[i]:
                if gid in seen: continue
                seen.add(gid)
                if gid not in assigned or augment(assigned[gid],seen):
                    assigned[gid]=i
                    return True
            return False
        for i in candidates: augment(i,set())
        return assigned
    strict={i:[gid for gid in gids if all(fields_ok(by_id[gid],actual[i]))] for i,gids in edges.items()}
    matched=matching(strict)
    remaining={i:[gid for gid in gids if gid not in matched] for i,gids in edges.items() if i not in matched.values()}
    matched.update(matching(remaining))
    owner_errors, due_errors, pairs = [], [], []
    correct=0
    for gid,i in matched.items():
        g,p=by_id[gid],actual[i]
        owner_ok,due_ok=fields_ok(g,p)
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


def model_info(model, transport=None):
    import httpx
    from providers.ollama import endpoint, LOOPBACK
    from urllib.parse import urlsplit
    target=endpoint()
    if not target: raise ValueError('No allowed Ollama endpoint')
    base,headers=target
    with httpx.Client(trust_env=False,follow_redirects=False,timeout=5,transport=transport) as c:
        v=c.get(base+'/api/version',headers=headers);v.raise_for_status()
        tags=c.get(base+'/api/tags',headers=headers);tags.raise_for_status()
    version = v.json().get('version')
    if not isinstance(version, str) or not version.strip():
        raise ValueError('Missing Ollama version')
    selected=next((t for t in tags.json().get('models',[]) if t.get('name')==model or t.get('model')==model),None)
    if not selected: raise ValueError('Requested exact model not installed on host')
    if not isinstance(selected.get('digest'), str) or not selected['digest'].strip():
        raise ValueError('Missing installed model digest')
    return dict(model=model,ollama_version=version,model_digest=selected['digest'],
                model_size_bytes=selected.get('size'),remote_gateway=urlsplit(base).hostname not in LOOPBACK)


def complete_excerpt(quote, text):
    """Independent sentence-boundary check: a quote cannot clip a negation."""
    if not isinstance(quote, str) or not quote:
        return False
    start = text.find(quote)
    while start >= 0:
        left, right = text[:start], text[start + len(quote):]
        left_ok = not left.strip() or re.search(r'(?:[.!?]\s+|\n\s*)$', left)
        right_ok = not right.strip() or right.startswith('\n') or (quote[-1] in '.!?' and right[0].isspace())
        if left_ok and right_ok:
            return True
        start = text.find(quote, start + 1)
    return False


def qa_result(client, case):
    payload = {'question': case['question']}
    if case.get('meeting_id') is not None:
        payload['meeting_id'] = case['meeting_id']
    response = client.post('/api/meet/qa', json=payload)
    result = response.json()
    checks = [response.status_code == 200, result.get('status') == case['expected_status']]
    claims = result.get('claims', [])
    opened, flattened = [], []
    for claim in claims:
        sources = claim.get('sources', [])
        checks.append(bool(sources))
        for source in sources:
            flattened.append(source)
            fid = source.get('id', '')
            if source.get('kind') != 'document' or not re.fullmatch(r'F[0-9]+', fid):
                checks.append(False)
                continue
            fragment_response = client.get('/api/meet/fragments/' + fid)
            if fragment_response.status_code != 200:
                checks.append(False)
                continue
            fragment = fragment_response.json()['fragment']
            document_response = client.get('/api/meet/documents/' + str(fragment['document_id']))
            if document_response.status_code != 200:
                checks.append(False)
                continue
            document = document_response.json()['document']
            quote = source.get('quote')
            checks += [quote == claim.get('text'), complete_excerpt(quote, fragment['text'])]
            try:
                at = datetime.fromisoformat(source['source_at'])
                uploaded = datetime.fromisoformat(document['created_at'])
                checks.append(at.tzinfo is not None and uploaded.tzinfo is not None and at == uploaded)
            except (KeyError, ValueError, TypeError):
                checks.append(False)
            opened.append({'filename': document['filename'], 'quote': quote})
    checks.append(result.get('sources', []) == flattened)
    if result.get('status') == 'grounded':
        checks += [bool(opened), bool(claims), result.get('answer') == '\n'.join(c['text'] for c in claims)]
    elif result.get('status') == 'insufficient_data':
        checks += [not claims, not opened]
    for name in case['expected_document_filenames']:
        checks.append(any(source['filename'] == name for source in opened))
    for quote in case['expected_quote_substrings']:
        checks.append(any(isinstance(source['quote'], str) and quote in source['quote'] for source in opened))
    for forbidden in case['forbidden_substrings']:
        checks.append(forbidden not in json.dumps(result, ensure_ascii=False))
    return dict(passed=all(checks), http_status=response.status_code, response=result, resolved_sources=opened)


class EvaluationBlocked(ValueError):
    """Stable safe code only; never include raw HTTP exceptions or credentials."""


def load_configuration():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    context = int(os.getenv('MEETINGS_CONTEXT', '8192'))
    timeout = float(os.getenv('MEETINGS_TIMEOUT', '300'))
    if context <= 0 or not math.isfinite(timeout) or timeout <= 0:
        raise EvaluationBlocked('invalid_model_configuration')
    return dict(context=context, timeout=timeout, temperature=0.1, think=False,
                stream=False, num_predict_protocol=1800)


def initial_report():
    return dict(schema_version=2, scorer_version=SCORER_VERSION, status='not_run',
                started_at=datetime.now(timezone.utc).isoformat(), run_id=uuid.uuid4().hex,
                commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
                dataset='photoprint-v1', judge='frozen deterministic rules; independent human review only if supplied',
                model_metadata_status='not_run', stage='dataset_integrity',
                transcripts=[], questions=[], llm_calls=[])


def run_evaluation(report, exclusive_window, checkpoint):
    report['dataset_sha256'] = frozen_check()
    report['stage'] = 'configuration'
    report['parameters'] = load_configuration()
    report['configured_model'] = os.getenv('MEETINGS_MODEL') or 'qwen2.5:7b'
    if report['dirty']:
        raise EvaluationBlocked('dirty_checkout_commit_changes_first')
    report['stage'] = 'gpu_window'
    if not exclusive_window:
        raise EvaluationBlocked('exclusive_gpu_window_not_confirmed')
    report['exclusive_gpu_window_confirmed'] = True
    from meetings import llm

    class ObservedLLM(llm.MeetingLLM):
        def json(self, system, user, schema, predict=1500):
            call = dict(predict=predict, schema_sha256=hashlib.sha256(
                json.dumps(schema, sort_keys=True).encode()).hexdigest())
            report['llm_calls'].append(call)
            before = time.perf_counter()
            try:
                result = super().json(system, user, schema, predict)
                call['status'] = 'ok'
                return result
            except Exception as error:
                call.update(status='error', error_code=getattr(error, 'code', type(error).__name__))
                raise
            finally:
                call['latency_seconds'] = time.perf_counter() - before

    report['stage'] = 'model_policy'
    provider = ObservedLLM()
    provider._base()
    report['stage'] = 'model_metadata'
    report['model'] = model_info(provider.model)
    report['model_metadata_status'] = 'observed'
    report['status'] = 'running'
    checkpoint(report)
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='track3-live-') as temporary:
        os.environ['MEETINGS_SECRET'] = 'synthetic-live-evaluation-secret'
        from scripts.track3.seed import seed
        report['stage'] = 'seed'
        ids = seed(str(Path(temporary) / 'live.db'))
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from meetings.api import install
        from meetings import store
        app = FastAPI()
        install(app)
        llm.set_llm(provider)
        clients = {}
        try:
            report['stage'] = 'authentication'
            for who in ('irina', 'petr'):
                client = TestClient(app)
                clients[who] = client
                client.post('/api/meet/login', json={'login': who, 'password': who + '-demo'}).raise_for_status()
            for control in gold['transcripts']:
                report['stage'] = 'protocol:' + control['key']
                mid = ids['meetings'][control['key']]
                before = time.perf_counter()
                response = clients['irina'].post(f'/api/meet/meetings/{mid}/protocol/draft')
                item = dict(key=control['key'], latency_seconds=time.perf_counter() - before,
                            http_status=response.status_code, response=response.json(),
                            transcript_sha256=control['transcript_sha256'])
                if response.status_code == 200:
                    item['predictions'] = response.json()['protocol']['items']
                    with store.db() as connection:
                        item['utterances'] = store.utterances(connection, mid)
                    item['scores'] = score_tasks(control['tasks'], item['predictions'], item['utterances'])
                report['transcripts'].append(item)
                # Persist each completed control before the next expensive call.
                checkpoint(report)
            report['predictions_sha256'] = predictions_digest(report)
            for number, case in enumerate(gold['questions'], 1):
                report['stage'] = f'qa:{number}'
                before = time.perf_counter()
                result = qa_result(clients[case['user_login']], case)
                report['questions'].append(dict(case=case, latency_seconds=time.perf_counter() - before, **result))
                checkpoint(report)
            report['stage'] = 'scoring'
            summarize(report)
        finally:
            for client in clients.values():
                client.close()
            llm.set_llm(None)
            store.reset_cache()


def predictions_digest(report):
    raw = [{key: value for key, value in item.items() if key != 'scores'}
           for item in report['transcripts']]
    return hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def summarize(report):
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    controls = {control['key']: control for control in gold['transcripts']}
    observed, issues = {}, []
    for item in report['transcripts']:
        key = item.get('key')
        if key not in controls or key in observed:
            issues.append('unknown_or_duplicate_transcript')
            continue
        observed[key] = item
    scores = [item['scores'] for item in observed.values() if 'scores' in item]
    denominator = sum(len(control['tasks']) for control in controls.values())
    predicted = sum(score['predicted_tasks'] for score in scores)
    correct = sum(score['correct_tasks'] for score in scores)
    report['overall'] = dict(recall=correct / denominator, precision=correct / predicted if predicted else 0.0,
                             correct_tasks=correct, gold_tasks=denominator, predicted_tasks=predicted,
                             owner_errors=sum(len(score['owner_errors']) for score in scores),
                             due_errors=sum(len(score['due_errors']) for score in scores),
                             false_or_unresolved_tasks=sum(len(score['false_or_unresolved_tasks']) for score in scores))
    if set(observed) != set(controls):
        issues.append('missing_transcripts')
    for key, item in observed.items():
        score = item.get('scores', {})
        if (item.get('http_status') != 200 or score.get('gold_tasks') != len(controls[key]['tasks'])
                or item.get('transcript_sha256') != controls[key]['transcript_sha256']):
            issues.append('incomplete_or_inconsistent_transcript')
    identity = lambda case: json.dumps(case, ensure_ascii=False, sort_keys=True)
    expected_cases = {identity(case) for case in gold['questions']}
    actual_cases = [identity(item.get('case')) for item in report['questions']]
    if len(actual_cases) != len(expected_cases) or set(actual_cases) != expected_cases:
        issues.append('missing_changed_or_duplicate_qa_cases')
    if (report.get('model_metadata_status') != 'observed'
            or not report.get('model', {}).get('ollama_version')
            or not report.get('model', {}).get('model_digest')
            or report.get('exclusive_gpu_window_confirmed') is not True):
        issues.append('unverified_model_or_gpu_window')
    if report.get('blocker') or report.get('status') in ('not_run', 'interrupted'):
        issues.append('unfinished_evaluation')
    report['evaluation_integrity'] = dict(passed=not issues, issues=sorted(set(issues)))
    passed = (not issues and len(scores) == len(controls) and report['overall']['recall'] >= 0.8
              and all(score['recall'] >= 0.8 and not score['manual_review_pending'] for score in scores)
              and all(item.get('passed') is True and item.get('http_status') == 200 for item in report['questions']))
    report['status'] = 'passed' if passed else 'failed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New absolute .json report path; never overwritten')
    parser.add_argument('--exclusive-gpu-window', action='store_true',
                        help='Operator confirms agreed window without competing inference')
    args = parser.parse_args()
    try:
        output = ReportFile(args.output)
    except ValueError as error:
        parser.error(str(error))
    report = initial_report()
    with output:
        output.write(report)
        try:
            run_evaluation(report, args.exclusive_gpu_window, output.write)
        except KeyboardInterrupt:
            report.update(status='interrupted', blocker='operator_interrupted')
        except Exception as error:
            report.update(status='not_run' if not report['transcripts'] else 'failed',
                          blocker_type=type(error).__name__,
                          blocker=str(error) if isinstance(error, EvaluationBlocked) else 'evaluation_prerequisite_or_request_failed')
        finally:
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            output.write(report)
    print(json.dumps({'status': report['status'], 'stage': report['stage'], 'report': str(output.path),
                      'model': report.get('model'), 'overall': report.get('overall')}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 130 if report['status'] == 'interrupted' else 2 if report['status'] == 'not_run' else 1


if __name__ == '__main__':
    raise SystemExit(main())
