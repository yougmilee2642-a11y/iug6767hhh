"""Single-owner workspace, additive draft persistence; no channel provisioning."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Literal
from pydantic import Field, ConfigDict
from agents.models import StrictModel
import storage
from services.agent_repository import AgentRepository
from providers.local_settings import local_only


# A draft may temporarily exceed the knowledge limits enforced at preview/save time
# (QuickInput), so that over-limit text typed or pasted by the owner survives a reload
# instead of being lost. The caps below only bound abuse; preview still rejects the excess.
DRAFT_FAQ_CAPS = {'question': 1000, 'answer': 5000, 'source': 1000}


class DraftFAQ(StrictModel):
    question: str = Field(default='', max_length=DRAFT_FAQ_CAPS['question'])
    answer: str = Field(default='', max_length=DRAFT_FAQ_CAPS['answer'])
    source: str = Field(default='', max_length=DRAFT_FAQ_CAPS['source'])


class DraftInput(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    business_name: str = Field(default='', max_length=100)
    business_type: str = Field(default='Компания', max_length=100)
    city: str = Field(default='', max_length=100)
    facts: str = Field(default='', max_length=12000)
    greeting: str = Field(default='', max_length=450)
    agent_id: str | None = Field(default=None,max_length=100)
    role: Literal['secretary','support'] = 'secretary'
    tone: Literal['brief','friendly','formal'] = 'brief'
    timezone: str = Field(default='Europe/Minsk',max_length=100)
    routing_preference: Literal['unspecified','voice','chat_requested'] = 'unspecified'
    qa: list[DraftFAQ] = Field(default_factory=list,max_length=10)


@contextmanager
def draft_connection():
    # A companion database preserves existing business records and core schema.
    path=storage.DB_PATH.with_name(storage.DB_PATH.stem + '-workspace.sqlite')
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=10)
    db.row_factory=sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with draft_connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS owner_workspace_draft (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)')


def load_draft():
    initialize()
    with draft_connection() as db:
        row=db.execute('SELECT revision,payload,updated_at FROM owner_workspace_draft WHERE id=1').fetchone()
    return {'revision':row['revision'],'data':json.loads(row['payload']),'updated_at':row['updated_at']} if row else {'revision':0,'data':None,'updated_at':None}


def save_draft(data, expected_revision):
    from services.track1_service import _SAVE_LOCK
    with _SAVE_LOCK:
        return _save_draft(data,expected_revision)


def _save_draft(data, expected_revision):
    initialize()
    with draft_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT revision FROM owner_workspace_draft WHERE id=1').fetchone()
        revision=row['revision'] if row else 0
        if revision != expected_revision:
            raise ValueError('Черновик изменён в другой вкладке. Загрузите свежую версию')
        updated=datetime.now(timezone.utc).isoformat()
        db.execute('INSERT INTO owner_workspace_draft VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,updated_at=excluded.updated_at',
                   (revision+1,data.model_dump_json(),updated))
    return {'revision':revision+1,'data':data.model_dump(),'updated_at':updated}


def _draft_matches_saved_agent(draft, agent_row):
    """True when the stored draft equals the confirmed settings of its agent (nothing waits for confirmation)."""
    from services.track1_service import QuickInput
    try:
        candidate=AgentRepository().candidate(agent_row['candidate_id']) if agent_row['candidate_id'] else None
        if not candidate: return False
        # agent_id is the link itself: a fresh assistant's confirmed input has none, its draft gets it after saving.
        def content(raw): return QuickInput.model_validate(raw).model_dump(exclude={'agent_id'})
        return content(draft['data'])==content(candidate['input'])
    except Exception:  # over-limit or incomplete draft cannot equal confirmed settings
        return False


def next_step(agent_rows, counts, draft):
    """Server-side decision so the overview always reflects real state, not browser memory.
    Codes: create, finish_draft, confirm_changes, activate, test_web, improve_knowledge."""
    data=draft['data']
    if data is not None:
        linked=next((a for a in agent_rows if a['id']==data.get('agent_id')),None) if data.get('agent_id') else None
        if linked is not None:
            if not _draft_matches_saved_agent(draft,linked): return {'code':'confirm_changes','agent_id':linked['id']}
        elif data.get('business_name'):
            return {'code':'finish_draft','agent_id':None}  # typed but never confirmed as an assistant
    if not agent_rows: return {'code':'create','agent_id':None}
    if not any(a['status']=='active' for a in agent_rows): return {'code':'activate','agent_id':agent_rows[0]['id']}
    if not sum(counts.values()): return {'code':'test_web','agent_id':next(a['id'] for a in agent_rows if a['status']=='active')}
    return {'code':'improve_knowledge','agent_id':agent_rows[0]['id']}


def overview():
    repo=AgentRepository();repo.initialize()
    with storage.connect() as db:
        rows=db.execute("SELECT * FROM agents WHERE source='track1' ORDER BY updated_at DESC").fetchall()
        agent_rows=[dict(r) for r in rows]
        agents=[]
        for row in rows:
            config=json.loads(row['config_json'])
            knowledge=config['business'].get('knowledge',{})
            agents.append({'id':row['id'],'name':row['name'],'status':row['status'],
                'company':config['business']['name'],'role':config['role']['name'],
                'profile':knowledge.get('track1_profile','secretary'),
                'faq_count':len(knowledge.get('qa',[])),'updated_at':row['updated_at']})
        counters=db.execute("SELECT status,COUNT(*) AS n FROM interactions WHERE agent_id IN (SELECT id FROM agents WHERE source='track1') GROUP BY status").fetchall()
    counts={r['status']:r['n'] for r in counters}
    draft=load_draft()
    step=next_step(agent_rows,counts,draft)
    return {'agents':agents,'next_step':step,'counts':{'assistants':len(agents),'conversations':sum(counts.values()),
        'confirmed':counts.get('completed',0),'human_requests':counts.get('escalated',0)},
        'local_only':local_only(), 'channels':{'web':'test_available','telephony':'not_connected',
           'telegram':'disabled' if local_only() else 'requires_agent_binding'},
        'draft':{'revision':draft['revision'],'exists':draft['data'] is not None}}
