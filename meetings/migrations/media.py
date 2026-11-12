"""Consent-bound audio assets, reviewable transcript jobs and call records."""


def upgrade(c):
    c.executescript('''
    CREATE TABLE media_assets (
      id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
      created_by INTEGER NOT NULL REFERENCES users(id), content BLOB NOT NULL,
      media_type TEXT NOT NULL, sha256 TEXT NOT NULL, consent_at TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE media_jobs (
      id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
      asset_id INTEGER REFERENCES media_assets(id) ON DELETE SET NULL,
      status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, error_code TEXT,
      created_by INTEGER NOT NULL REFERENCES users(id), duration_ms INTEGER,
      meeting_version INTEGER NOT NULL, transcript_hash TEXT NOT NULL,
      imported_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX media_jobs_meeting ON media_jobs(meeting_id,id);
    CREATE TABLE media_segments (
      id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES media_jobs(id) ON DELETE CASCADE,
      position INTEGER NOT NULL, speaker_label TEXT NOT NULL, text TEXT NOT NULL,
      start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, UNIQUE(job_id,position));
    CREATE TABLE calls (
      id INTEGER PRIMARY KEY, direction TEXT NOT NULL, channel TEXT NOT NULL,
      department_id INTEGER NOT NULL REFERENCES departments(id), agent_user_id INTEGER NOT NULL REFERENCES users(id),
      client_ref TEXT REFERENCES crm_customers(id), order_no TEXT REFERENCES erp_orders(order_no),
      started_at TEXT NOT NULL, duration_ms INTEGER, consent_at TEXT NOT NULL,
      meeting_id INTEGER UNIQUE NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
      created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
    CREATE INDEX calls_department_time ON calls(department_id,started_at);
    ''')
    c.execute('ALTER TABLE utterances ADD COLUMN end_ms INTEGER')
    c.execute('ALTER TABLE utterances ADD COLUMN media_job_id INTEGER REFERENCES media_jobs(id) ON DELETE SET NULL')
