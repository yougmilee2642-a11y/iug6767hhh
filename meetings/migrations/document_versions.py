"""Pending edition uploads are separate from immutable, citable documents."""


def upgrade(c):
    c.executescript('''
    CREATE TABLE document_version_drafts (
      confirmation_id TEXT PRIMARY KEY REFERENCES confirmations(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id), content BLOB NOT NULL);
    CREATE INDEX document_successor ON documents(supersedes_id);
    ''')
