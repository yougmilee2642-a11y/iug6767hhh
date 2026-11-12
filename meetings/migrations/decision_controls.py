"""Append-only human-confirmed control of protocol decisions."""


def upgrade(connection):
    connection.executescript('''
    CREATE TABLE decision_controls (
      id INTEGER PRIMARY KEY,
      protocol_item_id INTEGER UNIQUE NOT NULL REFERENCES protocol_items(id) ON DELETE CASCADE,
      owner_user_id INTEGER REFERENCES users(id), due TEXT,
      status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done','cancelled')),
      source_quote TEXT NOT NULL, confirmed_by INTEGER NOT NULL REFERENCES users(id),
      confirmation_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX decision_controls_due ON decision_controls(status,due);
    ''')
