import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "autofix.db"
_database_scope = ContextVar("callwise_database_scope", default=None)


def database_path():
    scope = _database_scope.get()
    return scope[0] if scope else DB_PATH


def is_isolated_database():
    return _database_scope.get() is not None


@contextmanager
def isolated_database(path):
    """Thread/task-local routing, never mutate the business database globals."""
    path = Path(path)
    if path.resolve() == DB_PATH.resolve():
        raise ValueError("Simulation database must differ from business storage")
    connections = []
    scope_token = _database_scope.set((path, connections))
    try:
        yield
    finally:
        for connection in connections:
            connection.close()
        _database_scope.reset(scope_token)

DEFAULT_CONFIG = {
    "business_name": "AutoFix",
    "industry": "serwis samochodowy",
    "city": "Wrocław",
    "notification_email": "",
    "language": "pl",
    "greeting": "Dzień dobry, AutoFix. Wszyscy pracownicy są teraz zajęci. Mogę przyjąć zgłoszenie. Jak ma Pan lub Pani na imię?",
    "services": "diagnostyka, mechanika, naprawa zawieszenia, serwis olejowy",
    "car_brands": "Audi, BMW, Ford, Mercedes-Benz, Opel, Škoda, Toyota, Volkswagen, Volvo",
    "opening_hours": "Poniedziałek–piątek, 8:00–18:00",
    "callback_message": "Pracownik serwisu oddzwoni najszybciej, jak to możliwe.",
    "knowledge_base": "Nie podawaj ceny bez diagnozy. W razie pilnej awarii zalecamy transport lawetą.",
    "custom_questions": [],
}


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    scope = _database_scope.get()
    if scope:
        scope[1].append(connection)
    return connection


def initialize_db() -> None:
    database_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS business_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                business_name TEXT NOT NULL,
                industry TEXT NOT NULL,
                city TEXT NOT NULL,
                notification_email TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'pl',
                greeting TEXT NOT NULL,
                services TEXT NOT NULL DEFAULT '',
                car_brands TEXT NOT NULL DEFAULT '',
                opening_hours TEXT NOT NULL DEFAULT '',
                callback_message TEXT NOT NULL DEFAULT '',
                knowledge_base TEXT NOT NULL DEFAULT '',
                custom_questions TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            )
            """
        )
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                name TEXT,
                phone TEXT,
                car TEXT,
                problem TEXT,
                additional_answers TEXT NOT NULL DEFAULT '{}',
                transcript TEXT NOT NULL DEFAULT '[]',
                email_sent INTEGER NOT NULL DEFAULT 0,
                email_error TEXT
            )
            """
        )
        database.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_created_at ON applications(created_at DESC)"
        )
        config_columns = {
            row[1] for row in database.execute("PRAGMA table_info(business_config)").fetchall()
        }
        if "knowledge_base" not in config_columns:
            database.execute(
                "ALTER TABLE business_config ADD COLUMN knowledge_base TEXT NOT NULL DEFAULT ''"
            )
        database.execute("PRAGMA optimize")
        if database.execute("SELECT 1 FROM business_config WHERE id = 1").fetchone() is None:
            legacy_save_config(DEFAULT_CONFIG, database)
        database.executescript("""
            CREATE TABLE IF NOT EXISTS callwise_config (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS interactions (
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY, interaction_id TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL, phone TEXT NOT NULL, service TEXT NOT NULL,
                datetime TEXT NOT NULL, employee TEXT NOT NULL, duration_minutes INTEGER NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(datetime, employee)
            );
            CREATE TABLE IF NOT EXISTS escalations (
                interaction_id TEXT PRIMARY KEY, reason TEXT NOT NULL, summary TEXT NOT NULL,
                customer_data TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cloud_bookings (
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, interaction_id TEXT NOT NULL,
                binding_hash TEXT NOT NULL, calendar_id TEXT NOT NULL,
                start TEXT NOT NULL, end TEXT NOT NULL, payload TEXT NOT NULL,
                calendar_status TEXT NOT NULL, crm_status TEXT NOT NULL,
                crm_id TEXT, error_code TEXT, lease_until REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(agent_id, interaction_id)
            );
            CREATE INDEX IF NOT EXISTS idx_cloud_bookings_resource ON cloud_bookings(calendar_id, start);
            CREATE TABLE IF NOT EXISTS review_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, interaction_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(interaction_id, reason)
            );
        """)
        # Add JSON/envelope columns only; preserve existing rows and legacy tables.
        migrations = {"bookings": {"structured_data": "TEXT NOT NULL DEFAULT '{}'"},
                      "escalations": {"reason_type": "TEXT NOT NULL DEFAULT 'legacy'", "agent_id": "TEXT NOT NULL DEFAULT 'legacy'"}}
        for table, additions in migrations.items():
            columns = {row[1] for row in database.execute(f"PRAGMA table_info({table})")}
            for column, declaration in additions.items():
                if column not in columns:
                    database.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        if not database.execute("SELECT 1 FROM callwise_config WHERE id = 1").fetchone():
            demo = json.loads((ROOT / "configs" / "beauty_salon.json").read_text(encoding="utf-8"))
            old = database.execute("SELECT notification_email FROM business_config WHERE id = 1").fetchone()
            config = {
                "business_name": demo["business"]["name"], "industry": demo["business"]["industry"],
                "city": demo["business"]["city"], "description": demo["business"]["description"],
                "language": "ru", "greeting": demo["greeting"], "notification_email": old[0] if old else "",
                "services": json.dumps(demo["business"]["knowledge"]["services"], ensure_ascii=False),
                "opening_hours": demo["business"]["opening_hours"], "timezone": demo["business"]["timezone"], "knowledge_base": "",
                "callback_message": "Запрос на связь сотрудника сохранён. Реального соединения в демо нет.",
                "custom_questions": []
            }
            database.execute("INSERT INTO callwise_config VALUES (1, ?)", (json.dumps(config, ensure_ascii=False),))


def row_to_config(row: sqlite3.Row) -> dict:
    config = dict(row)
    config.pop("id", None)
    config.pop("updated_at", None)
    config["custom_questions"] = json.loads(config.get("custom_questions") or "[]")
    return config


def legacy_get_config() -> dict:
    with connect() as database:
        row = database.execute("SELECT * FROM business_config WHERE id = 1").fetchone()
    return row_to_config(row) if row else DEFAULT_CONFIG.copy()


def legacy_save_config(config: dict, database: sqlite3.Connection | None = None) -> dict:
    owns_connection = database is None
    database = database or connect()
    try:
        database.execute(
            """
            INSERT INTO business_config (
                id, business_name, industry, city, notification_email, language,
                greeting, services, car_brands, opening_hours, callback_message,
                knowledge_base, custom_questions, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                business_name = excluded.business_name,
                industry = excluded.industry,
                city = excluded.city,
                notification_email = excluded.notification_email,
                language = excluded.language,
                greeting = excluded.greeting,
                services = excluded.services,
                car_brands = excluded.car_brands,
                opening_hours = excluded.opening_hours,
                callback_message = excluded.callback_message,
                knowledge_base = excluded.knowledge_base,
                custom_questions = excluded.custom_questions,
                updated_at = excluded.updated_at
            """,
            (
                config["business_name"],
                config["industry"],
                config["city"],
                config.get("notification_email", ""),
                config.get("language", "pl"),
                config["greeting"],
                config.get("services", ""),
                config.get("car_brands", ""),
                config.get("opening_hours", ""),
                config.get("callback_message", ""),
                config.get("knowledge_base", ""),
                json.dumps(config.get("custom_questions", []), ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        database.commit()
    finally:
        if owns_connection:
            database.close()
    return legacy_get_config() if owns_connection else config


def save_application(application: dict, transcript: list[dict]) -> int:
    with connect() as database:
        cursor = database.execute(
            """
            INSERT INTO applications (
                created_at, name, phone, car, problem, additional_answers,
                transcript, email_sent, email_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                application.get("name"),
                application.get("phone"),
                application.get("car"),
                application.get("problem"),
                json.dumps(application.get("additional_answers", {}), ensure_ascii=False),
                json.dumps(transcript, ensure_ascii=False),
                1 if application.get("email_sent") else 0,
                application.get("email_error"),
            ),
        )
        database.commit()
        return int(cursor.lastrowid)


def legacy_list_applications(limit: int = 50) -> list[dict]:
    with connect() as database:
        rows = database.execute(
            "SELECT * FROM applications ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["email_sent"] = bool(item["email_sent"])
        item["additional_answers"] = json.loads(item["additional_answers"] or "{}")
        item["transcript"] = json.loads(item["transcript"] or "[]")
        result.append(item)
    return result


def get_config() -> dict:
    with connect() as database:
        row = database.execute("SELECT payload FROM callwise_config WHERE id = 1").fetchone()
    config = json.loads(row[0])
    if "timezone" not in config:
        demo = json.loads((ROOT / "configs" / "beauty_salon.json").read_text(encoding="utf-8"))
        config["timezone"] = demo["business"]["timezone"]
    return config


def save_config(config: dict) -> dict:
    with connect() as database:
        database.execute("INSERT OR REPLACE INTO callwise_config VALUES (1, ?)", (json.dumps(config, ensure_ascii=False),))
    return config


def save_interaction(interaction: dict) -> dict:
    with connect() as database:
        database.execute("""INSERT INTO interactions VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET status=excluded.status, payload=excluded.payload""",
            (interaction["id"], interaction["agent_id"], interaction["created_at"], interaction["status"], json.dumps(interaction, ensure_ascii=False)))
    return interaction


def get_interaction(identifier: str) -> dict | None:
    with connect() as database:
        row = database.execute("SELECT payload FROM interactions WHERE id = ?", (identifier,)).fetchone()
    return json.loads(row[0]) if row else None


def public_interaction(data: dict) -> dict:
    from services.transcript_digest import transcript_digest
    public = {key: value for key, value in data.items() if key not in {"llm_history", "pending_action", "pending_collection", "agent_config", "last_request_id", "last_response"}}
    public['transcript_digest'] = transcript_digest(data)
    public['agent_name'] = data.get('agent_config',{}).get('name','')
    public['origin']='demo' if str(data.get('agent_id','')).startswith('shell_') else 'other'
    if public['origin']=='other':
        with connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='agents'").fetchone():
                row=db.execute('SELECT source FROM agents WHERE id=?',(data.get('agent_id'),)).fetchone()
                if row and row[0]=='track1': public['origin']='own'
    config = data.get("agent_config", {})
    labels = {"date": "Дата", "callback_id": "Номер обращения", **data.get("action_labels", {}), **{f["id"]: f["label"] for f in config.get("fields", [])}}
    values = data.get("action_result") or data.get("structured_data", {})
    displays = {f["id"]: f.get("display_values", {}) for f in config.get("fields", [])}
    public["display_fields"] = [{"id": key, "label": labels.get(key, key), "value": displays.get(key, {}).get(str(value), value)}
                                for key, value in values.items() if value is not None]
    if config.get('business',{}).get('knowledge',{}).get('track1_quick') is True:
        from services.telegram_store import delivery
        from services.call_summary import intake_summary
        public['telegram_delivery'] = delivery(data['id'])
        public['brief_summary'] = intake_summary(data)
    return public


def list_applications(limit: int = 50, agent_id: str | None = None, status: str | None = None, source: str | None = None) -> list[dict]:
    clauses, parameters = [], []
    for column, value in [('agent_id', agent_id), ('status', status)]:
        if value:
            clauses.append(column + ' = ?')
            parameters.append(value)
    with connect() as database:
        if source is not None:
            if source not in {'own','demo','other'}: raise ValueError('Unknown history source')
            own="agent_id IN (SELECT id FROM agents WHERE source='track1')" if database.execute("SELECT 1 FROM sqlite_master WHERE name='agents'").fetchone() else '0'
            demo="substr(agent_id,1,6)='shell_'"
            clauses.append({'own':own,'demo':demo,'other':f'NOT ({own}) AND NOT ({demo})'}[source])
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        rows = database.execute('SELECT payload FROM interactions' + where + ' ORDER BY created_at DESC LIMIT ?', (*parameters, limit)).fetchall()
    items = [public_interaction(json.loads(row[0])) for row in rows]
    # Keep historical applications visible without requiring their old fields in the new core.
    for old in legacy_list_applications(limit):
        if source not in {None,'other'} or (agent_id and agent_id != 'legacy-autofix') or (status and status != 'legacy'):
            continue
        items.append({"id": f"legacy-{old['id']}", "agent_id": "legacy-autofix", "created_at": old["created_at"],
                      "origin":"other", "status": "legacy", "customer_name": old["name"], "phone": old["phone"],
                      "intent": "Историческая заявка", "summary": old["problem"], "result": "Сохранено до миграции",
                      "structured_data": {"Автомобиль (архив)": old["car"], **old["additional_answers"]},
                      "transcript": old["transcript"], "tool_events": [], "escalation": None,
                      "email_sent": old["email_sent"], "email_error": old["email_error"]})
    return sorted(items, key=lambda item: item["created_at"], reverse=True)[:limit]
