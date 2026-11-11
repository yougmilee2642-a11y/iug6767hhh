import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
import storage


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def now(): return datetime.now(timezone.utc).isoformat()


class EvaluationRepository:
    def __init__(self,path=None): self.path=Path(path or storage.database_path())
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def initialize(self):
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS evaluation_runs (id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT);
                CREATE TABLE IF NOT EXISTS evaluation_scenarios (run_id TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS evaluation_results (run_id TEXT NOT NULL,scenario_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(run_id,scenario_id));
            ''')
    def save_run(self,run):
        self.initialize()
        with self.connect() as db:
            db.execute('INSERT INTO evaluation_runs VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload,completed_at=excluded.completed_at',
                (run['id'],run['agent_id'],run['status'],json.dumps(run,ensure_ascii=False),run['started_at'],run.get('completed_at')))
    def save_scenarios(self,rid,scenarios):
        with self.connect() as db:
            db.executemany('INSERT INTO evaluation_scenarios VALUES (?,?,?) ON CONFLICT(run_id,id) DO UPDATE SET payload=excluded.payload',[(rid,s.id,s.model_dump_json()) for s in scenarios])
    def save_result(self,rid,result):
        with self.connect() as db:
            db.execute('INSERT INTO evaluation_results VALUES (?,?,?)',(rid,result['scenario_id'],json.dumps(result,ensure_ascii=False)))
    def get(self,rid,details=False):
        self.initialize()
        with self.connect() as db:
            row=db.execute('SELECT payload FROM evaluation_runs WHERE id=?',(rid,)).fetchone()
            if not row: return None
            run=json.loads(row[0])
            from evaluation.service import PROCESS_TOKEN
            if run['status'] in {'pending','running'} and run.get('process_token')!=PROCESS_TOKEN:
                run.update(status='failed',completed_at=now(),readiness=None,
                           errors=[{'type':'WorkerInterrupted','status_code':None,'message':'Сервер перезапущен во время проверки. Запустите новый прогон.'}])
                db.execute('UPDATE evaluation_runs SET status=?,payload=?,completed_at=? WHERE id=?',
                    (run['status'],json.dumps(run,ensure_ascii=False),run['completed_at'],rid))
            agent=db.execute('SELECT config_json,candidate_id FROM agents WHERE id=?',(run['agent_id'],)).fetchone()
            current=bool(agent and digest(json.loads(agent[0]))==run['config_hash'])
            if agent and agent[1]:
                candidate=db.execute('SELECT payload FROM builder_candidates WHERE id=?',(agent[1],)).fetchone()
                candidate_payload=json.loads(candidate[0]) if candidate else {}
                if run.get('evaluation_profile')=='quick_role':
                    current=current and bool(candidate and digest(candidate_payload.get('input'))==run.get('quick_input_hash'))
                else:
                    current=current and bool(candidate and digest(candidate_payload['business_input'])==run['business_hash'])
                    if run.get('contract_hash'):
                        current=current and bool(candidate and digest(candidate_payload.get('requirement_contract'))==run['contract_hash'])
            else: current=False
            run.update(current=current,outdated=not current)
            scenarios=[json.loads(r[0]) for r in db.execute('SELECT payload FROM evaluation_scenarios WHERE run_id=? ORDER BY rowid',(rid,))]
            results={r['scenario_id']:r for r in (json.loads(row[0]) for row in db.execute('SELECT payload FROM evaluation_results WHERE run_id=?',(rid,)))}
            run['scenarios']=[{**s,'result':results.get(s['id']) if details else ({k:v for k,v in results[s['id']].items() if k!='trace'} if s['id'] in results else None)} for s in scenarios]
        return run
    def result(self,rid,sid):
        with self.connect() as db:
            row=db.execute('SELECT payload FROM evaluation_results WHERE run_id=? AND scenario_id=?',(rid,sid)).fetchone()
        return json.loads(row[0]) if row else None
    def list(self,agent_id):
        self.initialize()
        with self.connect() as db:
            ids=[row[0] for row in db.execute('SELECT id FROM evaluation_runs WHERE agent_id=? ORDER BY started_at DESC LIMIT 20',(agent_id,))]
        return [{k:r[k] for k in ('id','status','started_at','completed_at','readiness','current','outdated')} for r in [self.get(i) for i in ids]]
