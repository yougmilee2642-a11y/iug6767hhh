"""Retention requests, notification outbox, rate limits, append-only comments."""
def upgrade(c):
    c.executescript('''
    CREATE TABLE retention_policy(id INTEGER PRIMARY KEY CHECK(id=1),audio_after_confirm INTEGER NOT NULL DEFAULT 1,
      transcript_days INTEGER NOT NULL DEFAULT 180,chat_days INTEGER NOT NULL DEFAULT 30,audit_days INTEGER NOT NULL DEFAULT 365,version INTEGER NOT NULL DEFAULT 1);
    INSERT INTO retention_policy(id) VALUES (1);
    CREATE TABLE deletion_requests(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),status TEXT NOT NULL DEFAULT 'pending',
      requested_at TEXT NOT NULL,confirmed_by INTEGER,confirmed_at TEXT);
    CREATE TABLE notifications(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL,
      object_type TEXT,object_id TEXT,message TEXT NOT NULL,created_at TEXT NOT NULL,read_at TEXT,dedupe_key TEXT UNIQUE);
    CREATE TABLE notification_settings(user_id INTEGER PRIMARY KEY REFERENCES users(id),email_enabled INTEGER NOT NULL DEFAULT 0,
      telegram_enabled INTEGER NOT NULL DEFAULT 0,bitrix_enabled INTEGER NOT NULL DEFAULT 0,version INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE notification_outbox(id INTEGER PRIMARY KEY,notification_id INTEGER NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
      channel TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL,
      UNIQUE(notification_id,channel));
    CREATE TABLE task_comments(id INTEGER PRIMARY KEY,task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id),text TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE task_history(id INTEGER PRIMARY KEY,task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
      user_id INTEGER REFERENCES users(id),before_json TEXT NOT NULL,after_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE security_limits(key TEXT NOT NULL,bucket INTEGER NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(key,bucket));
    CREATE TABLE meeting_series(id INTEGER PRIMARY KEY,owner_id INTEGER NOT NULL REFERENCES users(id),title TEXT NOT NULL,
      weekday INTEGER,hour TEXT NOT NULL,timezone TEXT NOT NULL DEFAULT 'Europe/Minsk',created_at TEXT NOT NULL);
    ALTER TABLE meetings ADD COLUMN series_id INTEGER REFERENCES meeting_series(id);
    ''')
