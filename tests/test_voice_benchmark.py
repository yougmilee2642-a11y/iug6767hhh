"""STT benchmark metrics are deterministic and work without downloaded models."""
from scripts.benchmark_voice import normalize, edit_distance, error_rate


def test_runner_separates_warmup_and_writes_corpus_metrics_without_text(tmp_path):
    import json
    from scripts.benchmark_voice import run
    (tmp_path/'a.wav').write_bytes(b'audio')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps([{'id':'a','audio':'a.wav','reference':'добрый день'}]),encoding='utf-8')
    calls=[]
    def transcribe(data): calls.append(data);return 'добрый вечер'
    result=run(manifest,tmp_path/'report.json',transcriber=transcribe)
    assert calls==[b'audio',b'audio']
    assert result['warmup_excluded'] and result['warmup_seconds'] is not None
    assert result['wer_corpus']==.5 and result['samples'][0]['word_errors']==1
    assert 'reference' not in result['samples'][0] and 'hypothesis' not in result['samples'][0]
    assert result['dataset_sha256'] and result['environment']['python']


def test_cli_bootstraps_root_from_an_unrelated_directory(tmp_path):
    import json,subprocess,sys
    from pathlib import Path
    script=Path(__file__).resolve().parents[1]/'scripts/benchmark_voice.py'
    (tmp_path/'a.wav').write_bytes(b'audio')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps([{'id':'a','audio':'a.wav','reference':'тест'}]),encoding='utf-8')
    # Inject only the model dependency, preserving the actual CLI and its path bootstrap.
    code="""
import sys,runpy,types
script,manifest,output=sys.argv[1:]
root=str(__import__('pathlib').Path(script).resolve().parents[1])
sys.path=[p for p in sys.path if p!=root]
def transcribe(data):
 assert root in sys.path
 return 'тест'
stub=types.ModuleType('services.local_speech');stub.transcribe_local=transcribe
sys.modules['services.local_speech']=stub
sys.argv=[script,'--manifest',manifest,'--output',output]
runpy.run_path(script,run_name='__main__')
"""
    response=subprocess.run([sys.executable,'-c',code,str(script),str(manifest),str(tmp_path/'out.json')],cwd=tmp_path,capture_output=True,text=True)
    assert response.returncode==0,response.stderr
    assert json.loads((tmp_path/'out.json').read_text(encoding='utf-8'))['wer_corpus']==0


def test_normalization_handles_russian_punctuation_and_yo():
    assert normalize('Ёлка, ПРИВЕТ! 123') == 'елка привет 123'


def test_edit_distance_and_error_rates():
    assert edit_distance(list('кот'), list('кит')) == 1
    assert error_rate('добрый день', 'добрый вечер', 'word') == 0.5
    assert error_rate('ёлка', 'елка', 'char') == 0.0
    assert error_rate('', '', 'word') == 0.0
    assert error_rate('', 'лишнее', 'word') == 1.0
