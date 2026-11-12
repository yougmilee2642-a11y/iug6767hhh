"""Canonical installer marker paths, exercised without models or server startup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_start_configure_canonicalizes_the_path_recorded_by_seed(tmp_path):
    database = tmp_path / 'demo.db'; database.touch()
    marker = Path(str(database) + '.track3.json')
    marker.write_text(json.dumps({'db':str(database.resolve())}), encoding='utf-8')
    script = ("import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
              "from scripts.track3.start import configure;configure(Path('demo.db'));"
              "import os;assert os.environ['MEETINGS_DB_PATH']==str(Path('demo.db').resolve())")
    result = subprocess.run([sys.executable,'-c',script,str(ROOT)],cwd=tmp_path,
                            env={k:v for k,v in os.environ.items() if k!='MEETINGS_SECRET'},
                            capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    after=json.loads(marker.read_text(encoding='utf-8'))
    assert after['db']==str(database.resolve()) and after['start_files']


@pytest.mark.parametrize('code',['model_unavailable','model_timeout'])
def test_closed_loopback_smoke_accepts_explicit_provider_failures(code):
    from scripts.track3.v2_http_smoke import model_failure_code
    assert model_failure_code({'code':code,'detail':'Локальная модель недоступна.'})==code


@pytest.mark.parametrize('body',[{}, {'status':'ok'}, {'code':'model_unavailable'},
                                 {'code':'forbidden_role','detail':'Нет прав'},
                                 {'code':'model_timeout','detail':' '}])
def test_closed_loopback_smoke_rejects_missing_or_unrelated_results(body):
    from scripts.track3.v2_http_smoke import model_failure_code
    with pytest.raises(AssertionError): model_failure_code(body)
