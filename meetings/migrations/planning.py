"""Finite recurring plans and individual reminder preferences."""
def upgrade(c):
    from meetings.migrations import _add_column
    _add_column(c, 'meeting_series', "spec TEXT NOT NULL DEFAULT '{}'")
    _add_column(c, 'meeting_series', 'department_id INTEGER REFERENCES departments(id)')
    _add_column(c, 'meeting_series', 'version INTEGER NOT NULL DEFAULT 1')
    _add_column(c, 'notification_settings', 'reminder_minutes INTEGER NOT NULL DEFAULT 15')
