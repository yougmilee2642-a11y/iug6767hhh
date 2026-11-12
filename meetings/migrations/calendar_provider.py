"""Durable reservation before a potentially uncertain external calendar write."""


def upgrade(c):
    c.execute('''CREATE TABLE calendar_provider_outbox (
      id INTEGER PRIMARY KEY, event_id INTEGER UNIQUE NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id), provider TEXT NOT NULL,
      payload TEXT NOT NULL, payload_hash TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', external_ref TEXT, last_error TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
