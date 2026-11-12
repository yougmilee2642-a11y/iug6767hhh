"""Personal ICS subscriptions and one replaceable busy-only import per user."""


def upgrade(c):
    c.executescript('''
    CREATE TABLE calendar_subscriptions (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
      revoked_at TEXT);
    CREATE INDEX calendar_subscriptions_user ON calendar_subscriptions(user_id);
    CREATE TABLE calendar_import_state (
      user_id INTEGER PRIMARY KEY REFERENCES users(id), sha256 TEXT NOT NULL,
      imported_at TEXT NOT NULL, interval_count INTEGER NOT NULL);
    ''')
