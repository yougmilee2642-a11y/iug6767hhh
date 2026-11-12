"""Scoped historical seasonality, explicit pickup deadlines and reviewed controls."""
def upgrade(c):
    from meetings.migrations import _add_column
    _add_column(c,'erp_orders','storage_expires_at TEXT')
    c.executescript('''
    CREATE TABLE seasonality_samples(source_id TEXT PRIMARY KEY,department_id INTEGER REFERENCES departments(id),
      confidentiality TEXT NOT NULL DEFAULT 'department',as_of TEXT NOT NULL,section TEXT NOT NULL,
      period_start TEXT NOT NULL,period_end TEXT NOT NULL,occupied_hours REAL NOT NULL,available_hours REAL NOT NULL);
    CREATE TABLE pickup_storage(order_no TEXT PRIMARY KEY REFERENCES erp_orders(order_no) ON DELETE CASCADE,
      expires_at TEXT NOT NULL,carrier_code TEXT NOT NULL,source_id TEXT UNIQUE NOT NULL,as_of TEXT NOT NULL,
      department_id INTEGER REFERENCES departments(id),confidentiality TEXT NOT NULL DEFAULT 'department');
    CREATE TABLE weekly_digest_outbox(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
      period_end TEXT NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL,confirmation_id TEXT UNIQUE NOT NULL,
      created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued_local');
    CREATE TABLE task_effect_checks(id INTEGER PRIMARY KEY,protocol_item_id INTEGER NOT NULL REFERENCES protocol_items(id) ON DELETE CASCADE,
      owner_id INTEGER NOT NULL REFERENCES users(id),metric_key TEXT NOT NULL,baseline REAL,baseline_json TEXT NOT NULL,target_value REAL NOT NULL,
      direction TEXT NOT NULL,check_at TEXT NOT NULL,created_at TEXT NOT NULL,department_id INTEGER REFERENCES departments(id),
      status TEXT NOT NULL DEFAULT 'scheduled',result_json TEXT,confirmation_id TEXT UNIQUE NOT NULL,version INTEGER NOT NULL DEFAULT 1);
    ''')
