"""Durable human-confirmed mock exports; no network transport."""


def upgrade(c):
    c.executescript('''
    CREATE TABLE integration_outbox (
      id INTEGER PRIMARY KEY, connector TEXT NOT NULL, action TEXT NOT NULL,
      object_type TEXT NOT NULL, object_id INTEGER NOT NULL, payload_hash TEXT NOT NULL,
      preview_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','sent','failed','uncertain','cancelled')),
      idempotency_key TEXT UNIQUE NOT NULL, confirmation_id TEXT UNIQUE NOT NULL,
      confirmed_by INTEGER NOT NULL REFERENCES users(id), confirmed_at TEXT NOT NULL,
      external_ref TEXT, last_error TEXT,
      UNIQUE(connector,action,object_type,object_id));
    CREATE TABLE mock_crm_objects (
      ref TEXT PRIMARY KEY, kind TEXT NOT NULL, object_id INTEGER NOT NULL,
      entity_ref TEXT, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
      idempotency_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'open',
      source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      UNIQUE(kind,object_id,entity_ref));
    CREATE INDEX integration_outbox_actor ON integration_outbox(confirmed_by,confirmed_at);
    ''')
