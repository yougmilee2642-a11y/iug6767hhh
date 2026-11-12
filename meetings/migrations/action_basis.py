def upgrade(c):
    c.execute('''CREATE TABLE action_basis (
      object_type TEXT NOT NULL, object_id INTEGER NOT NULL,
      source_kind TEXT NOT NULL, source_id TEXT NOT NULL, source_hash TEXT NOT NULL,
      source_json TEXT NOT NULL, confirmed_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
      PRIMARY KEY(object_type,object_id))''')
