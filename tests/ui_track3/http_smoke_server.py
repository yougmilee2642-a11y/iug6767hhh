"""Isolated real-HTTP integration server (explicit deterministic model double).
TRACK3_SERVER_ROOT=/path/to/combined/server python tests/ui_track3/http_smoke_server.py
No external mail, model calls or live databases. UI always comes from this checkout.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

UI_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = Path(os.environ.get('TRACK3_SERVER_ROOT', UI_ROOT)).resolve()
sys.path.insert(0, str(SERVER_ROOT))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
import uvicorn

FACT = 'Запуск проекта назначен на 1 декабря 2026 года.'

class ExplicitModelDouble:
    model = 'ui-track3-http-smoke-double'

    def json(self, system, user, schema, predict=1500):
        from meetings import extract
        if system == extract.PROTOCOL_SYSTEM:
            uid = re.search(r'(U\d+) \|', user)[1]
            return {'items': [dict(kind='task',text='Подготовить план',outcome='none',assignee='',due_text='',utterance_ids=[uid],quote='Я подготовлю план')],}
        if system == extract.CANDIDATE_SYSTEM:
            return dict(kind='none',text='',outcome='none',assignee='',due_text='')
        if system == extract.SUMMARY_SYSTEM:
            return {'claims': []}
        if system == extract.PREP_FACTS_SYSTEM:
            return {'facts': []}
        if system == extract.PREP_PLAN_SYSTEM:
            return dict(agenda=[],questions=[],gaps=[])
        payload = json.loads(user)
        fragment = payload['untrusted_documents'][0]
        return {'claims': [dict(text=fragment['text'],quote=fragment['text'],fragment_id=fragment['fragment_id'])]}


def create_app():
    from meetings import llm
    from meetings.api import install
    app = FastAPI()
    app.mount('/static', StaticFiles(directory=UI_ROOT / 'static'), name='static')

    @app.get('/meetings')
    def page():
        return FileResponse(UI_ROOT / 'static/meetings.html')

    install(app)
    llm.set_llm(ExplicitModelDouble())
    client = TestClient(app)
    def checked(response):
        assert response.status_code == 200, (response.status_code, response.text)
        return response.json()
    checked(client.post('/api/meet/login', json=dict(login='irina',password='irina-demo')))
    meeting = checked(client.post('/api/meet/meetings', json=dict(title='HTTP: Запуск проекта',topic='План запуска',participants=['Ирина'],scheduled_at='2026-11-18T09:00',timezone='Europe/Minsk')))['meeting']
    document = checked(client.post('/api/meet/documents', files={'file':('plan.txt',FACT.encode(),'text/plain')}, data={'meeting_id':str(meeting['id'])}))['document']
    checked(client.put(f"/api/meet/meetings/{meeting['id']}/transcript",json={'text':'Ирина: Я подготовлю план.'}))
    protocol = checked(client.post(f"/api/meet/meetings/{meeting['id']}/protocol/draft"))['protocol']
    assert any(i['kind']=='task' for i in protocol['items']), protocol
    print('UI_TRACK3_HTTP_SEEDED', json.dumps(dict(meeting_id=meeting['id'],document_id=document['id'])), flush=True)
    return app

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='track3-ui-http-') as temporary:
        os.environ['MEETINGS_DB_PATH'] = str(Path(temporary) / 'isolated.sqlite')
        os.environ['MEETINGS_SECRET'] = 'isolated-ui-smoke-only'
        os.environ['MEETINGS_DEMO_USERS'] = 'true'
        uvicorn.run(create_app(),host='127.0.0.1',port=int(os.environ.get('TRACK3_SMOKE_PORT','8766')),log_level='warning')
