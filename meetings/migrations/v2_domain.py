"""Append-only v2 organization, source snapshots and classification metadata."""


def upgrade(connection):
    from meetings.migrations import _add_column
    connection.executescript('''
    CREATE TABLE departments (
      id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
      parent_id INTEGER REFERENCES departments(id), head_user_id INTEGER REFERENCES users(id));
    CREATE TABLE products (
      id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, format TEXT NOT NULL,
      price_minor INTEGER NOT NULL CHECK(price_minor>=0), currency TEXT NOT NULL DEFAULT 'BYN',
      lead_workdays INTEGER NOT NULL DEFAULT 3, source_ref TEXT NOT NULL);
    CREATE TABLE delivery_carriers (code TEXT PRIMARY KEY, name TEXT NOT NULL, source_ref TEXT NOT NULL);
    CREATE TABLE support_topics (code TEXT PRIMARY KEY, name TEXT NOT NULL, sla_minutes INTEGER NOT NULL);
    CREATE TABLE order_statuses (code TEXT PRIMARY KEY, name TEXT NOT NULL, ordinal INTEGER NOT NULL);
    CREATE TABLE crm_customers (
      id TEXT PRIMARY KEY, display_name TEXT NOT NULL, kind TEXT NOT NULL,
      source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id), confidentiality TEXT NOT NULL DEFAULT 'department');
    CREATE TABLE erp_orders (
      order_no TEXT PRIMARY KEY, client_ref TEXT REFERENCES crm_customers(id), product_code TEXT NOT NULL,
      pages INTEGER NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'BYN',
      channel TEXT NOT NULL, carrier_code TEXT NOT NULL, status TEXT NOT NULL,
      accepted_at TEXT NOT NULL, promised_at TEXT NOT NULL, completed_at TEXT,
      defective INTEGER NOT NULL DEFAULT 0, delay_reason TEXT, discount_percent INTEGER NOT NULL DEFAULT 0, campaign TEXT,
      source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id), confidentiality TEXT NOT NULL DEFAULT 'department');
    CREATE TABLE order_events (
      id INTEGER PRIMARY KEY, order_no TEXT NOT NULL REFERENCES erp_orders(order_no) ON DELETE CASCADE,
      status TEXT NOT NULL, at TEXT NOT NULL, UNIQUE(order_no,status));
    CREATE TABLE crm_deals (
      id TEXT PRIMARY KEY, client_ref TEXT REFERENCES crm_customers(id), title TEXT NOT NULL,
      amount_minor INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'BYN', responsible_user_id INTEGER REFERENCES users(id),
      stage TEXT NOT NULL, source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id), confidentiality TEXT NOT NULL DEFAULT 'department');
    CREATE TABLE support_interactions (
      id TEXT PRIMARY KEY, client_ref TEXT REFERENCES crm_customers(id), order_no TEXT REFERENCES erp_orders(order_no),
      channel TEXT NOT NULL, topic_code TEXT NOT NULL, body TEXT NOT NULL, closed_by TEXT NOT NULL,
      first_response_seconds INTEGER NOT NULL, sla_seconds INTEGER NOT NULL, opened_at TEXT NOT NULL,
      agent_user_id INTEGER REFERENCES users(id), source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id), confidentiality TEXT NOT NULL DEFAULT 'department');
    CREATE TABLE production_plan (
      id INTEGER PRIMARY KEY, source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id), confidentiality TEXT NOT NULL DEFAULT 'department',
      section TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
      planned_units INTEGER NOT NULL, produced_units INTEGER NOT NULL, defective_units INTEGER NOT NULL,
      available_hours REAL NOT NULL, occupied_hours REAL NOT NULL, forecast INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE work_shifts (
      id INTEGER PRIMARY KEY, source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id), confidentiality TEXT NOT NULL DEFAULT 'department',
      user_id INTEGER REFERENCES users(id), start_at TEXT NOT NULL, end_at TEXT NOT NULL,
      break_start TEXT, break_end TEXT);
    CREATE TABLE hr_absences (
      id INTEGER PRIMARY KEY, source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id), confidentiality TEXT NOT NULL DEFAULT 'department',
      personnel_code TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL, reason TEXT NOT NULL);
    CREATE TABLE finance_aggregates (
      id INTEGER PRIMARY KEY, source_id TEXT UNIQUE NOT NULL, as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id), confidentiality TEXT NOT NULL DEFAULT 'department',
      period_start TEXT NOT NULL, period_end TEXT NOT NULL,
      revenue_minor INTEGER NOT NULL, cost_minor INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'BYN');
    CREATE TABLE demo_imports (dataset TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL,
      seeded_at TEXT NOT NULL, object_ids TEXT NOT NULL);
    CREATE TABLE user_external_ids (user_id INTEGER REFERENCES users(id), connector TEXT NOT NULL,
      external_id TEXT NOT NULL, PRIMARY KEY(user_id,connector), UNIQUE(connector,external_id));
    CREATE TABLE delegations (
      id INTEGER PRIMARY KEY, from_user INTEGER NOT NULL REFERENCES users(id),
      to_user INTEGER NOT NULL REFERENCES users(id), department_id INTEGER NOT NULL REFERENCES departments(id),
      starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, reason TEXT NOT NULL,
      confirmation_id TEXT UNIQUE, revoked_at TEXT, created_at TEXT NOT NULL);
    CREATE INDEX delegations_active ON delegations(to_user,starts_at,ends_at);
    CREATE INDEX orders_scope_date ON erp_orders(department_id,accepted_at);
    CREATE INDEX interactions_scope_date ON support_interactions(department_id,opened_at);
    ''')
    for definition in ('department_id INTEGER REFERENCES departments(id)', 'level TEXT',
                       'manager_id INTEGER REFERENCES users(id)', "timezone TEXT NOT NULL DEFAULT 'Europe/Minsk'",
                       'active INTEGER NOT NULL DEFAULT 1', 'personnel_code TEXT'):
        _add_column(connection, 'users', definition)
    for table in ('documents', 'meetings', 'production_metrics'):
        for definition in ('department_id INTEGER REFERENCES departments(id)',
                           "confidentiality TEXT NOT NULL DEFAULT 'confidential'"):
            _add_column(connection, table, definition)
    for definition in ("doc_type TEXT NOT NULL DEFAULT 'документ'", 'version INTEGER NOT NULL DEFAULT 1',
                       'supersedes_id INTEGER REFERENCES documents(id)', 'valid_until TEXT', 'authored_at TEXT', 'source_ref TEXT'):
        _add_column(connection, 'documents', definition)
    _add_column(connection, 'meetings', 'source_ref TEXT')
    connection.execute('CREATE UNIQUE INDEX documents_source_ref ON documents(source_ref) WHERE source_ref IS NOT NULL')
    connection.execute('CREATE UNIQUE INDEX meetings_source_ref ON meetings(source_ref) WHERE source_ref IS NOT NULL')
    for definition in ('department_id INTEGER REFERENCES departments(id)', 'assignee_user_id INTEGER REFERENCES users(id)',
                       "priority TEXT NOT NULL DEFAULT 'normal'", "linked_entities TEXT NOT NULL DEFAULT '[]'", 'external_ref TEXT'):
        _add_column(connection, 'tasks', definition)
    _add_column(connection, 'audit', 'department_id INTEGER REFERENCES departments(id)')
