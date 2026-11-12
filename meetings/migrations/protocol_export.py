def upgrade(c):
    c.executescript('''
    CREATE TABLE protocol_mail_outbox(id INTEGER PRIMARY KEY,meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
      recipient_id INTEGER NOT NULL REFERENCES users(id),confirmation_id TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued_local',UNIQUE(confirmation_id,recipient_id));
    ''')
