"""Explicit channel destination proofs and durable, never blindly retried sends."""
def upgrade(c):
    from meetings.migrations import _add_column
    _add_column(c,'notification_settings',"delivery_proof TEXT NOT NULL DEFAULT '{}'")
    _add_column(c,'notification_outbox','finished_at TEXT')
    _add_column(c,'notification_outbox','error_code TEXT')
    c.executescript('''
    CREATE TABLE smtp_outbox(id INTEGER PRIMARY KEY,invitation_id INTEGER NOT NULL UNIQUE REFERENCES calendar_outbox(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id),proof TEXT NOT NULL,confirmation_id TEXT UNIQUE NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL,finished_at TEXT,error_code TEXT);
    ''')
