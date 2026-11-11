"""Isolated browser API fixtures; never imported by the application."""
from copy import deepcopy
from urllib.parse import urlparse

NOW = '2026-11-11T09:00:00+00:00'
READ = ['meetings.read', 'prep.generate', 'calendar.view', 'qa.ask', 'overview.read', 'feedback.create']
WRITE = READ + ['meetings.create', 'meetings.edit', 'meetings.share', 'documents.upload', 'transcript.edit', 'protocol.edit', 'protocol.confirm', 'tasks.change', 'calendar.invite']
MEETING = dict(id=1, title='Запуск Орбиты', topic='План запуска', scheduled_at='2026-11-18T06:00:00+00:00', participants=['Ирина', 'Пётр'], owner_id=1, access_user_ids=[], version=1)
SOURCE = dict(kind='document', id='F1', title='План запуска', source_at=NOW, quote='Запуск проекта назначен на 1 декабря 2026 года.')
QUOTE = dict(utterance_id='U1', text='Я подготовлю план.', speaker='Ирина', verified=True)
ITEM = dict(id=10, kind='task', text='Подготовить план', assignee=None, assignee_status='unknown', due=None, due_status='unknown', quotes=[QUOTE], confirmed=False)
TASK = dict(id=1, text='Подготовить план', assignee=None, assignee_status='unknown', due='2026-11-01', due_status='stated', status='open', meeting_id=1, meeting_title=MEETING['title'], source_quote=QUOTE)

class FixtureAPI:
    def __init__(self):
        self.user = 'irina'
        self.meeting = deepcopy(MEETING)
        self.calls = []
        self.errors = {}
        self.task = deepcopy(TASK)
        self.items = [deepcopy(ITEM), dict(deepcopy(ITEM), id=11, text='Проверить релиз')]
        self.qa_empty = False
        self.qa_html = False
        self.conflict = False
        self.confirmed = False
        self.due_changed = None

    def handle(self, route):
        req = route.request
        path = urlparse(req.url).path.removeprefix('/api/meet')
        body = req.post_data_json if req.post_data else None
        self.calls.append((req.method, path, body))
        status, result = self.respond(req.method, path, body)
        route.fulfill(status=status, json=result)

    def count(self, path):
        return sum(p == path for _, p, _ in self.calls)

    def respond(self, method, path, body):
        if path in self.errors:
            status = self.errors[path]
            return status, dict(code={401:'not_authenticated',403:'forbidden_role',404:'not_found',503:'model_unavailable'}.get(status, 'slot_taken'), detail=f'Тестовая ошибка {status}')
        if path == '/login': self.user = body['login']; return 200, {'user': self.me()['user']}
        if path == '/logout': self.user = None; return 200, {}
        if not self.user: return 401, dict(code='not_authenticated', detail='Войдите снова')
        if path == '/me': return 200, self.me()
        if path == '/users': return 200, {'users': [{'id':1,'name':'Ирина'}, {'id':2,'name':'Пётр'}]}
        if path == '/documents': return 200, {'documents': [dict(id=1, title='План запуска', created_at=NOW, filename='plan.txt')]}
        if path == '/meetings' and method == 'GET': return 200, {'meetings': [dict(self.meeting, title=self.meeting['title'] if self.user == 'irina' else 'Синк Петра')]}
        if path == '/meetings' and method == 'POST': return 200, {'meeting': dict(self.meeting, **body)}
        if path == '/meetings/1' and method == 'PATCH': self.meeting.update(body); return 200, {'meeting': self.meeting}
        if path == '/meetings/1': return 200, dict(meeting=self.meeting, documents=[], utterances=[dict(id='U1',idx=1,speaker='Ирина',speaker_label='Говорящий 1',text=QUOTE['text'],meeting_id=1)], tasks=[self.task] if self.confirmed else [], prep=dict(status='ok',brief=[],agenda=[],questions=[],open_tasks=[self.task],task_questions=[]), protocol=dict(items=self.items, summary=[dict(text='Подготовка плана', status='verified', quotes=[QUOTE])],warnings=[]))
        if path == '/tasks': return 200, {'tasks': [self.task]}
        if path == '/tasks/1/preview':
            changes = body['changes']
            self.due_changed = changes
            before = {k:self.task.get(k) for k in ['status','assignee','due']}
            return 200, dict(confirmation_id='cf_task', preview=dict(text=self.task['text'], before=before, after={**before, **changes},changes={}))
        if path == '/tasks/1/confirm':
            self.task.update(self.due_changed)
            if 'due' in self.due_changed: self.task['due_text'] = None
            return 200, {'task':self.task}
        if path.startswith('/confirmations/'): return 200, {}
        if path == '/meetings/1/protocol' and method == 'PUT':
            self.items = [{**old, **next(i for i in body['items'] if i['id']==old['id'])} for old in self.items]
            return 200, {'protocol': dict(items=self.items, summary=[])}
        if path == '/meetings/1/protocol/confirm':
            self.confirmed = True
            for item in self.items:
                if item['id'] in body['item_ids']: item['confirmed'] = True
            return 200, dict(protocol=dict(items=self.items),created=[self.task],already_confirmed=[self.task])
        if path == '/overview': return 200, dict(as_of=NOW,generated_at=NOW,metrics=[dict(key='on_time_orders',label='Заказы в срок',value=None,unit='%',formula='sum(on_time_orders) / sum(completed_orders) × 100',source=dict(kind='metric',id='aggregate',title='Витрина',source_at=NOW))],overdue_tasks=[self.task],warnings=['Производственная витрина устарела.'],summary=[])
        if path == '/qa':
            claim = '<img src=x onerror="window.injected=1">' if self.qa_html else SOURCE['quote']
            return 200, dict(answer_id=1,status='insufficient_data' if self.qa_empty else 'grounded',claims=[] if self.qa_empty else [dict(text=claim,sources=[SOURCE])],sources=[] if self.qa_empty else [SOURCE],answer='UNVERIFIED ANSWER MUST NOT APPEAR',generated_at=NOW)
        if path == '/feedback': return 200, {'feedback_id': 1}
        if path == '/fragments/F1': return 200, {'fragment': dict(id='F1',text=SOURCE['quote'],document_title=SOURCE['title'],document_id=1,location='Абзац 1')}
        if path == '/utterances/U1': return 200, dict(utterance=dict(id='U1',idx=1,speaker='Ирина',speaker_label='Говорящий 1',text=QUOTE['text'],meeting_id=1),meeting_title=self.meeting['title'])
        if path == '/calendar/participants': return 200, dict(participants=[dict(id=1,name='Ирина'),dict(id=2,name='Пётр')])
        if path == '/calendar/slots': return 200, dict(slots=[dict(start_at='2026-11-18T06:00:00+00:00',end_at='2026-11-18T07:00:00+00:00')],timezone=body['timezone'],participants=[dict(id=1,name='Ирина')],provider='mock')
        if path == '/calendar/preview': return 200, dict(confirmation_id='cf_calendar',expires_at=NOW,preview=dict(title=self.meeting['title'],start_at='2026-11-18T06:00:00+00:00',end_at='2026-11-18T07:00:00+00:00',timezone='Europe/Minsk',participants=[dict(id=1,name='Ирина')],invitations=[dict(recipient_name='Ирина',subject='Тестовое приглашение',body='Локальная очередь')],warnings=[],provider='mock'))
        if path == '/calendar/confirm':
            if self.conflict: return 409, dict(code='slot_taken',detail='Слот уже занят')
            return 200, {}
        return 404, dict(code='not_found',detail=f'Fixture route missing: {method} {path}')

    def me(self):
        return dict(user=dict(id=1 if self.user=='irina' else 2, login=self.user, name='Ирина' if self.user=='irina' else 'Пётр'),capabilities=WRITE if self.user=='irina' else READ,timezone='Europe/Minsk')
