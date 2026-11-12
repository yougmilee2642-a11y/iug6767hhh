"""AI-07: feedback «полезно / ошибка» on a result the user can actually see.

Only the minimum is stored: who, which target, rating, optional comment (≤1000 chars), time. A target the user
cannot read is answered with the same audited 404 as any foreign object.
"""
import importlib
import importlib.util

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from meetings import store
from meetings.api import _sid, denied
from meetings.auth import MeetError, MeetRoute, current_user, require

TARGETS = ('meeting', 'prep', 'protocol_summary', 'protocol_item', 'task', 'qa_answer', 'utterance', 'assistant_message')


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    meeting_id: int | None = None
    answer_id: str | int | None = None
    target_type: str = Field(pattern='^(' + '|'.join(TARGETS) + ')$')
    target_id: str | int
    rating: str = Field(pattern='^(useful|incorrect)$')
    comment: str | None = Field(default=None, max_length=1000)


def _answer_loader():
    """meetings.knowledge.service.load_answer(connection, user_id, answer_id) when the QA module is delivered."""
    if importlib.util.find_spec('meetings.knowledge') is None or importlib.util.find_spec('meetings.knowledge.service') is None:
        return None
    return importlib.import_module('meetings.knowledge.service').load_answer


def _number(value, prefix=''):
    try:
        return _sid(str(value), prefix) if prefix else int(str(value).strip())
    except (MeetError, ValueError):
        return None


def resolve(connection, user, target_type: str, target_id) -> tuple[str, int | None]:
    """Returns (normalised target id, meeting id) or raises an audited 404."""
    def gone():
        return denied(user, target_type, str(target_id)[:40], 'feedback.create')

    if target_type == 'assistant_message':
        row = connection.execute('SELECT conversation_id FROM assistant_messages WHERE id=? AND user_id=?',(_number(target_id),user['id'])).fetchone()
        if not row: raise gone()
        from meetings.assistant.service import history
        history(connection,user,row['conversation_id'])
        return str(_number(target_id)),None
    if target_type in ('meeting', 'prep', 'protocol_summary'):
        meeting_id = _number(target_id)
        if meeting_id is None or not store.can_read_meeting(connection, user['id'], meeting_id):
            raise gone()
        if target_type == 'prep' and not connection.execute('SELECT 1 FROM preps WHERE meeting_id=?', (meeting_id,)).fetchone():
            raise gone()
        if target_type == 'protocol_summary' and not connection.execute(
                'SELECT 1 FROM protocols WHERE meeting_id=?', (meeting_id,)).fetchone():
            raise gone()
        return str(meeting_id), meeting_id
    if target_type == 'protocol_item':
        number = _number(target_id)
        row = connection.execute('SELECT meeting_id FROM protocol_items WHERE id=?', (number,)).fetchone() if number else None
    elif target_type == 'task':
        number = _number(target_id, 'T')
        row = connection.execute('SELECT meeting_id FROM tasks WHERE id=?', (number,)).fetchone() if number else None
    elif target_type == 'utterance':
        number = _number(target_id, 'U')
        row = connection.execute('SELECT meeting_id FROM utterances WHERE id=? AND deleted=0', (number,)).fetchone() \
            if number else None
    else:  # qa_answer: personal answers of Codex 2's QA module; only the asker may rate them
        number = _number(target_id)
        answer = connection.execute('SELECT user_id, meeting_id FROM qa_answers WHERE id=?', (number,)).fetchone() \
            if number else None
        if answer is None or answer['user_id'] != user['id'] or (
                answer['meeting_id'] is not None and not store.can_read_meeting(connection, user['id'], answer['meeting_id'])):
            raise gone()
        loader = _answer_loader()
        if loader is not None:  # also re-checks every source document ACL (revocation after answering)
            try:
                loader(connection, user['id'], number)
            except MeetError as error:
                if error.status == 404:
                    raise gone() from None
                # 409 stale_sources: the answer is still the user's own; rating a stale answer is allowed
        return str(number), answer['meeting_id']
    if row is None or not store.can_read_meeting(connection, user['id'], row['meeting_id']):
        raise gone()
    return str(number), row['meeting_id']


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.post('/api/meet/feedback')
    def create(payload: FeedbackIn, request: Request):
        user = current_user(request)
        require(user, 'feedback.create', action='feedback.create')
        if payload.answer_id is not None and (payload.target_type != 'qa_answer'
                                              or str(payload.answer_id) != str(payload.target_id)):
            raise MeetError(422, 'answer_mismatch', 'answer_id допускается только для target_type="qa_answer" и '
                                                   'должен совпадать с target_id.')
        comment = (payload.comment or '').strip() or None
        with store.db() as connection:
            target_id, meeting_id = resolve(connection, user, payload.target_type, payload.target_id)
            if payload.meeting_id is not None and payload.meeting_id != meeting_id:
                raise denied(user, 'meeting', payload.meeting_id, 'feedback.create')
            feedback_id = connection.execute(
                'INSERT INTO feedback(user_id,meeting_id,target_type,target_id,rating,comment,created_at) '
                'VALUES (?,?,?,?,?,?,?)',
                (user['id'], meeting_id, payload.target_type, target_id, payload.rating, comment, store.now())).lastrowid
            store.audit(connection, user['id'], 'feedback', object_type=payload.target_type, object_id=target_id,
                        rating=payload.rating, has_comment=bool(comment), feedback_id=feedback_id)
            return {'feedback_id': feedback_id}

    @api.get('/api/meet/feedback')
    def mine(request: Request, target_type: str = '', target_id: str = ''):
        """The user's own feedback (optionally for one target). Nobody reads other users' comments here."""
        user = current_user(request)
        query, args = 'SELECT * FROM feedback WHERE user_id=?', [user['id']]
        if target_type:
            query += ' AND target_type=?'
            args.append(target_type)
        if target_id:
            query += ' AND target_id=?'
            args.append(target_id)
        with store.db() as connection:
            rows = connection.execute(query + ' ORDER BY id DESC LIMIT 200', args).fetchall()
            return {'feedback': [{'id': r['id'], 'meeting_id': r['meeting_id'], 'target_type': r['target_type'],
                                  'target_id': r['target_id'], 'rating': r['rating'], 'comment': r['comment'],
                                  'created_at': r['created_at']} for r in rows]}

    return api
