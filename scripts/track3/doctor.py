"""Read-only prerequisites: no inference, model download, seed or DB mutation."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.track3.evaluate import frozen_check, load_configuration, model_info
from scripts.track3.reporting import ReportFile


def diagnose():
    result = dict(status='not_ready', checked_at=datetime.now(timezone.utc).isoformat(),
                  inference_requests=0, database_mutations=0,
                  torch_required=False, torch_installed=importlib.util.find_spec('torch') is not None,
                  gpu_window='Must be agreed separately; metadata availability does not reserve the GPU')
    stage = 'dataset_integrity'
    try:
        result['dataset_sha256'] = frozen_check()
        stage = 'configuration'
        result['parameters'] = load_configuration()
        result['configuration'] = {key + '_present': bool(os.getenv(key)) for key in
                                   ('OLLAMA_BASE_URL', 'OLLAMA_API_KEY', 'MEETINGS_MODEL')}
        result['configured_model'] = os.getenv('MEETINGS_MODEL') or 'qwen2.5:7b'
        stage = 'model_policy'
        from meetings.llm import MeetingLLM
        MeetingLLM()._base()
        stage = 'model_metadata'
        result['model'] = model_info(result['configured_model'])
        result['status'] = 'metadata_ready'
    except Exception as error:
        result.update(blocked_at=stage, error_type=type(error).__name__,
                      next_action='Configure a running allowed Ollama gateway/model; supply credentials through environment, then agree a GPU window')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New absolute .json report path')
    args = parser.parse_args()
    try:
        with ReportFile(args.output) as output:
            result = diagnose()
            output.write(result)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'metadata_ready' else 2


if __name__ == '__main__':
    raise SystemExit(main())
