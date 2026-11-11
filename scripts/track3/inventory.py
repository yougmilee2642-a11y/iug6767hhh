"""Record installed package metadata and license file hashes, without inferring terms."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform


def inventory():
    packages=[]
    for d in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        m=d.metadata
        files=[]
        for f in d.files or []:
            if any(word in str(f).lower() for word in ('license','copying','notice')) and '.dist-info' in str(f):
                path=Path(d.locate_file(f))
                if path.is_file():
                    files.append({'path':str(f),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        declared=(m.get('License') or '').strip()
        packages.append(dict(name=m['Name'],version=d.version,license_expression=m.get('License-Expression'),
                             license_declared=declared[:240],license_classifiers=[v for v in m.get_all('Classifier',[]) if v.startswith('License')],
                             project_urls=m.get_all('Project-URL',[]),homepage=m.get('Home-page'),
                             package_source=f"https://pypi.org/project/{m['Name']}/{d.version}/",license_files=files,
                             status='metadata recorded; consult upstream license text'))
    return {'observed_at':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
            'platform':platform.platform(),'packages':packages,'weights':'not installed by text environment; see LICENSES.md'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    Path(a.output).write_text(json.dumps(inventory(),ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
