"""Personal assistant conversations, read proofs and confirmed manual task origin."""
def upgrade(c):
    c.executescript('''
    CREATE TABLE assistant_conversations(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL);
    CREATE TABLE assistant_messages(id INTEGER PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id),question_masked TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE INDEX assistant_messages_user ON assistant_messages(user_id,created_at);
    CREATE TABLE assistant_evidence(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),tool TEXT NOT NULL,
      args_json TEXT NOT NULL,result_hash TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE INDEX assistant_evidence_user ON assistant_evidence(user_id,created_at);
    CREATE TABLE task_origins(task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id),origin TEXT NOT NULL,created_at TEXT NOT NULL);
    ''')
