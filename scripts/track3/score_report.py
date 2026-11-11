"""Apply independent human review to an existing observed report, never rerun the model."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.track3.evaluate import GOLD, frozen_check, score_tasks, summarize


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',required=True);p.add_argument('--review',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    if Path(a.output).resolve()==Path(a.report).resolve(): p.error('Preserve original report; choose a new output')
    report=json.loads(Path(a.report).read_text(encoding='utf-8'));review=json.loads(Path(a.review).read_text(encoding='utf-8'))
    if report['status']=='not_run': p.error('Cannot score a run that never happened')
    if report['dataset_sha256']!=frozen_check(): p.error('Dataset differs from evaluated version')
    raw=[{k:v for k,v in item.items() if k!='scores'} for item in report['transcripts']]
    digest=hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if digest!=report['predictions_sha256'] or review['predictions_sha256']!=digest: p.error('Predictions hash mismatch')
    gold={t['key']:t['tasks'] for t in json.loads(GOLD.read_text(encoding='utf-8'))['transcripts']}
    for t in report['transcripts']:
        if t['http_status']==200:
            t['scores']=score_tasks(gold[t['key']],t['predictions'],t['utterances'],review.get('transcripts',{}).get(t['key'],[]))
    report['independent_review']=review
    summarize(report)
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    return 0 if report['status']=='passed' else 1


if __name__=='__main__': raise SystemExit(main())
