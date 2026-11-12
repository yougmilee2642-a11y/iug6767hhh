"""Versioned, append-only migrations for the meetings SQLite database.

`store.SCHEMA` is the frozen baseline (version 0, the MVP schema at cb2614b). Every later change is a numbered
step below; the applied version lives in `PRAGMA user_version`. Steps run once, each in its own
`BEGIN IMMEDIATE` transaction, so two processes opening the same database cannot apply a step twice and a failed
step leaves the database at the previous version. Steps must work on a database that already contains data.

Never edit a released step: add a new one. Other modules that need tables send a request to the owner of
store/migrations (see docs/track3-handoffs/claude.md).
"""
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Documented zone for legacy naive demo timestamps (ТЗ: UI and demo data use Europe/Minsk). Not the OS zone.
LEGACY_ZONE = ZoneInfo('Europe/Minsk')


def _columns(connection, table):
    return {r[1] for r in connection.execute(f'PRAGMA table_info({table})')}


def _add_column(connection, table, definition):
    name = definition.split()[0]
    if name not in _columns(connection, table):
        connection.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')


def legacy_to_utc(value):
    """Old `scheduled_at` was free text, usually naive 'YYYY-MM-DDTHH:MM'. Naive → Europe/Minsk; aware → UTC.
    Returns None when the value is not a datetime at all."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LEGACY_ZONE)
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')


def m001_roles(connection):
    """Explicit server-side role per user (separate from the human job title in `users.role`)."""
    _add_column(connection, 'users', "access_role TEXT NOT NULL DEFAULT 'reader'")
    connection.execute("UPDATE users SET access_role='manager' WHERE login='irina'")


def m002_audit(connection):
    """Structured audit: request/correlation id, object, result, sources, confirmation, model, error code."""
    for definition in ('request_id TEXT', 'object_type TEXT', 'object_id TEXT', "result TEXT NOT NULL DEFAULT 'ok'",
                       "source_ids TEXT NOT NULL DEFAULT '[]'", 'confirmation_id TEXT', 'model TEXT', 'error_code TEXT'):
        _add_column(connection, 'audit', definition)
    connection.execute('CREATE INDEX IF NOT EXISTS audit_user_at ON audit(user_id, at)')
    connection.execute('CREATE INDEX IF NOT EXISTS audit_object ON audit(object_type, object_id)')
    connection.execute('CREATE INDEX IF NOT EXISTS audit_request ON audit(request_id)')


def m003_versions_and_time(connection):
    """Optimistic-lock versions; meeting time stored as aware UTC ISO (legacy naive values read as Europe/Minsk)."""
    _add_column(connection, 'meetings', 'version INTEGER NOT NULL DEFAULT 1')
    _add_column(connection, 'meetings', 'scheduled_at_legacy TEXT')
    _add_column(connection, 'tasks', 'version INTEGER NOT NULL DEFAULT 1')
    _add_column(connection, 'protocols', "summary TEXT NOT NULL DEFAULT '[]'")
    for row in connection.execute('SELECT id, scheduled_at FROM meetings WHERE scheduled_at IS NOT NULL').fetchall():
        converted = legacy_to_utc(row[1])
        if converted is None:  # unparseable free text is kept aside, never guessed
            connection.execute('UPDATE meetings SET scheduled_at=NULL, scheduled_at_legacy=? WHERE id=?', (row[1], row[0]))
        elif converted != row[1]:
            connection.execute('UPDATE meetings SET scheduled_at=? WHERE id=?', (converted, row[0]))


def m004_confirmations(connection):
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS confirmations (
      id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
      object_type TEXT NOT NULL, object_id TEXT NOT NULL, object_version INTEGER, payload TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', idempotency_key TEXT, result TEXT, created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL, finished_at TEXT);
    CREATE INDEX IF NOT EXISTS confirmations_user ON confirmations(user_id, status);
    """)


def m005_calendar(connection):
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS calendar_busy (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), start_at TEXT NOT NULL,
      end_at TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'test');
    CREATE INDEX IF NOT EXISTS calendar_busy_user ON calendar_busy(user_id, start_at);
    CREATE TABLE IF NOT EXISTS calendar_events (
      id INTEGER PRIMARY KEY, meeting_id INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
      organizer_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, start_at TEXT NOT NULL,
      end_at TEXT NOT NULL, timezone TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'mock',
      status TEXT NOT NULL DEFAULT 'confirmed', confirmation_id TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS calendar_event_participants (
      event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY (event_id, user_id));
    CREATE INDEX IF NOT EXISTS calendar_participants_user ON calendar_event_participants(user_id);
    CREATE TABLE IF NOT EXISTS calendar_outbox (
      id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
      recipient_id INTEGER NOT NULL REFERENCES users(id), channel TEXT NOT NULL DEFAULT 'local_outbox',
      subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued_local', created_at TEXT NOT NULL,
      UNIQUE (event_id, recipient_id));
    """)


def m006_feedback(connection):
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS feedback (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), meeting_id INTEGER,
      target_type TEXT NOT NULL, target_id TEXT NOT NULL, rating TEXT NOT NULL, comment TEXT,
      created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS feedback_target ON feedback(target_type, target_id);
    """)


def m007_knowledge_and_management(connection):
    """Tables for Codex 2 (knowledge QA and management overview), proposed in the CONTRACT kick-off.
    Store/migration ownership stays here; the modules read/write them through their own queries."""
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS qa_answers (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), meeting_id INTEGER,
      question_masked TEXT NOT NULL, question_sha256 TEXT NOT NULL, status TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
      claims TEXT NOT NULL DEFAULT '[]', source_ids TEXT NOT NULL DEFAULT '[]', model TEXT, request_id TEXT,
      generated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS qa_answers_user ON qa_answers(user_id, generated_at);
    CREATE TABLE IF NOT EXISTS production_metrics (
      id INTEGER PRIMARY KEY, source_id TEXT UNIQUE NOT NULL, owner_id INTEGER REFERENCES users(id),
      scope TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, as_of TEXT NOT NULL,
      completed_orders INTEGER, on_time_orders INTEGER, produced_units INTEGER, defective_units INTEGER,
      available_capacity REAL, occupied_capacity REAL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS production_metric_access (
      metric_id INTEGER NOT NULL REFERENCES production_metrics(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY (metric_id, user_id));
    CREATE INDEX IF NOT EXISTS production_metrics_asof ON production_metrics(as_of);
    """)


def m008_management_indexes(connection):
    """Indexes requested by Codex 2 for ACL-filtered overview queries."""
    connection.execute('CREATE INDEX IF NOT EXISTS production_metric_access_user ON production_metric_access(user_id, metric_id)')
    connection.execute('CREATE INDEX IF NOT EXISTS production_metrics_scope_asof ON production_metrics(scope, as_of)')


def m009_organization_and_domain(connection):
    """V2 organization, source snapshots and classification, preserving all released rows."""
    from meetings.migrations.v2_domain import upgrade
    upgrade(connection)


def m010_decision_controls(connection):
    from meetings.migrations.decision_controls import upgrade
    upgrade(connection)


def m011_crm_outbox(connection):
    from meetings.migrations.crm_outbox import upgrade
    upgrade(connection)


def m012_calendar_interchange(connection):
    from meetings.migrations.calendar_interchange import upgrade
    upgrade(connection)


MIGRATIONS = [
    (1, 'roles', m001_roles),
    (2, 'audit', m002_audit),
    (3, 'versions_and_time', m003_versions_and_time),
    (4, 'confirmations', m004_confirmations),
    (5, 'calendar', m005_calendar),
    (6, 'feedback', m006_feedback),
    (7, 'knowledge_and_management', m007_knowledge_and_management),
    (8, 'management_indexes', m008_management_indexes),
    (9, 'organization_and_domain', m009_organization_and_domain),
    (10, 'decision_controls', m010_decision_controls),
    (11, 'crm_outbox', m011_crm_outbox),
    (12, 'calendar_interchange', m012_calendar_interchange),
]
LATEST = MIGRATIONS[-1][0]


def version(connection) -> int:
    return connection.execute('PRAGMA user_version').fetchone()[0]


def apply(connection: sqlite3.Connection) -> list[int]:
    """Apply pending steps. Safe to call on every start and from several processes."""
    applied = []
    for number, _name, step in MIGRATIONS:
        if version(connection) >= number:
            continue
        previous = connection.isolation_level
        connection.isolation_level = None  # explicit transaction control (DDL included)
        try:
            connection.execute('BEGIN IMMEDIATE')
            if version(connection) >= number:  # another process got there first
                connection.execute('COMMIT')
                continue
            step(_Recorder(connection))
            connection.execute(f'PRAGMA user_version = {int(number)}')
            connection.execute('COMMIT')
            applied.append(number)
        except BaseException:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        finally:
            connection.isolation_level = previous
    return applied


class _Recorder:
    """executescript() commits implicitly, which would break the per-step transaction. Steps run against this
    recorder: plain execute() runs immediately inside the transaction, executescript() is split into statements."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        return self.connection.execute(sql, params)

    def executescript(self, script):
        for statement in script.split(';'):
            if statement.strip():
                self.connection.execute(statement)


def describe() -> list[dict]:
    return [{'version': number, 'name': name, 'doc': (step.__doc__ or '').strip().split('\n')[0]}
            for number, name, step in MIGRATIONS]
