"""Local SQLite lifecycle. JSON demo is never rewritten."""
import json
from datetime import datetime, timezone
import storage


def now():
    return datetime.now(timezone.utc).isoformat()


class AgentRepository:
    def initialize(self):
        with storage.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, config_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, source TEXT NOT NULL, candidate_id TEXT UNIQUE)")
            db.execute("CREATE TABLE IF NOT EXISTS builder_candidates (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")

    def save_candidate(self, payload):
        self.initialize()
        with storage.connect() as db:
            db.execute("INSERT INTO builder_candidates VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (payload["candidate_id"], json.dumps(payload, ensure_ascii=False), now()))

    def candidate(self, candidate_id):
        self.initialize()
        with storage.connect() as db:
            row = db.execute("SELECT payload FROM builder_candidates WHERE id=?", (candidate_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, agent_id):
        self.initialize()
        with storage.connect() as db:
            row = db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["config"] = json.loads(result.pop("config_json"))
        candidate=self.candidate(result['candidate_id']) if result.get('candidate_id') else None
        result['requirement_contract']=candidate.get('requirement_contract') if candidate else None
        return result

    def save(self, config, source="builder", status="valid", candidate_id=None, replace_candidate=False):
        self.initialize()
        updates = 'name=excluded.name, config_json=excluded.config_json, updated_at=excluded.updated_at'
        if replace_candidate:
            updates += ', candidate_id=excluded.candidate_id'
        with storage.connect() as db:
            db.execute("INSERT INTO agents VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET " + updates, (config.id, config.name, status, config.model_dump_json(), now(), now(), source, candidate_id))
        return self.get(config.id)

    def set_status(self, agent_id, status):
        with storage.connect() as db:
            db.execute("UPDATE agents SET status=?, updated_at=? WHERE id=?", (status, now(), agent_id))
        return self.get(agent_id)

    def list(self):
        self.initialize()
        with storage.connect() as db:
            rows = db.execute("SELECT id,name,status,source,created_at,updated_at FROM agents ORDER BY source DESC,created_at DESC").fetchall()
        return [dict(row) for row in rows]
