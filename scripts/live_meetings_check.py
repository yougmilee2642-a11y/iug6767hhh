"""Run the demo meeting through the REAL local model (Ollama) in a throwaway DB and print the result."""
import json, os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
os.environ['MEETINGS_DB_PATH'] = str(Path(tempfile.mkdtemp()) / 'live.db')
from fastapi.testclient import TestClient
from scripts.seed_meetings_demo import seed
ids = seed(with_transcript=True)
import app
c = TestClient(app.app); c.post('/api/meet/login', json={'login': 'irina', 'password': 'irina-demo'})
m = ids['launch_meeting']
t = time.time(); r = c.post(f'/api/meet/meetings/{m}/protocol/draft'); print('DRAFT', r.status_code, round(time.time()-t), 's')
print(json.dumps(r.json(), ensure_ascii=False, indent=1))
t = time.time(); r = c.post(f'/api/meet/meetings/{m}/prepare'); print('PREP', r.status_code, round(time.time()-t), 's')
print(json.dumps(r.json(), ensure_ascii=False, indent=1))
