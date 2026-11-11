"""Explicit test paths; no recursive deletions or default database access."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / 'data/meetings.db'


def explicit_db(value):
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise ValueError('Database path must be absolute')
    if any(part == '..' for part in p.parts):
        raise ValueError('Parent traversal is not allowed')
    # Reject symlinks in any existing component (including broken links).
    if any(part.is_symlink() for part in (p, *p.parents)):
        raise ValueError('Symlink database paths are not allowed')
    p = p.resolve()
    if p == DEFAULT_DB.resolve() or ROOT / 'data' == p or ROOT / 'data' in p.parents:
        raise ValueError('Working data/ is protected; use an isolated test directory')
    if p.suffix not in ('.db', '.sqlite', '.sqlite3'):
        raise ValueError('Expected a named .db/.sqlite/.sqlite3 test database')
    return p
