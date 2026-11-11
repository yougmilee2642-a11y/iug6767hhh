"""Review existing observations without inference or overwriting any evidence file."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.track3.evaluate import GOLD, SCORER_VERSION, frozen_check, predictions_digest, score_tasks, summarize
from scripts.track3.reporting import ReportFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--review', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        output = ReportFile(args.output)
        report = json.loads(Path(args.report).read_text())
        review = json.loads(Path(args.review).read_text())
        if report['status'] not in ('passed', 'failed'):
            raise ValueError('Cannot score a missing, running or interrupted evaluation')
        if report.get('schema_version') != 2 or report.get('scorer_version') != SCORER_VERSION:
            raise ValueError('Report belongs to a different schema/scorer; preserve its original evaluation')
        if report['dataset_sha256'] != frozen_check():
            raise ValueError('Dataset differs from evaluated version')
        digest = predictions_digest(report)
        if digest != report.get('predictions_sha256') or review.get('predictions_sha256') != digest:
            raise ValueError('Predictions hash mismatch')
        controls = {control['key']: control['tasks'] for control in json.loads(GOLD.read_text())['transcripts']}
        if set(review.get('transcripts', {})) - set(controls):
            raise ValueError('Review contains an unknown transcript key')
        for transcript in report['transcripts']:
            if transcript['http_status'] == 200:
                transcript['scores'] = score_tasks(controls[transcript['key']], transcript['predictions'],
                                                   transcript['utterances'], review.get('transcripts', {}).get(transcript['key'], []))
        report.update(independent_review=review, scorer_version=SCORER_VERSION)
        summarize(report)
    except (ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    with output:
        output.write(report)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
