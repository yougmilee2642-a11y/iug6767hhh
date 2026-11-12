"""Canonical read-only document/utterance evidence for confirmed manual actions."""
import re
from meetings import store,access
from meetings.auth import MeetError
from meetings.document_versions import cited,freshness,snapshot


def resolve(c,user,kind,key):
    from meetings.api import denied
    pattern='F' if kind=='document' else 'U'
    if kind not in ('document','utterance') or not re.fullmatch(pattern+r'[1-9]\d{0,17}',str(key)):
        raise MeetError(404,'not_found','Источник недоступен.')
    if kind=='document':
        f=c.execute('SELECT * FROM fragments WHERE id=?',(int(key[1:]),)).fetchone()
        if not f or not store.can_read_document(c,user['id'],f['document_id'],model=True):raise denied(user,'document',key,'action.basis')
        d=c.execute('SELECT * FROM documents WHERE id=?',(f['document_id'],)).fetchone()
        return {'source':cited(d,f),'data':{'document_id':d['id'],'version':d['version'],'snapshot':snapshot(c,d),
                'freshness':freshness(c,user['id'],d['id'])}}
    u=c.execute('SELECT * FROM utterances WHERE id=? AND deleted=0',(int(key[1:]),)).fetchone()
    if not u or not store.can_read_meeting(c,user['id'],u['meeting_id'],model=True):raise denied(user,'utterance',key,'action.basis')
    m=c.execute('SELECT * FROM meetings WHERE id=?',(u['meeting_id'],)).fetchone()
    from meetings.connectors.mock import digest
    return {'source':{'kind':'utterance','id':key,'title':m['title'],'quote':u['text'],
        'source_at':m['scheduled_at'] or m['created_at']},'data':{'meeting_id':m['id'],'version':m['version'],
        'snapshot':digest({'meeting':dict(m),'utterance':dict(u)})}}
