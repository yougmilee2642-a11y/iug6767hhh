"""Real FTS5/BM25 with pre-index SQL rights, no model weights/extensions."""
import sqlite3

import pytest

from meetings import store
from meetings.knowledge import index
from test_track3_knowledge_support import env, document, meeting


def search(client, query='поставка картона'):
    return client.get('/api/meet/search',params={'q':query})


def make_private(doc_id):
    with store.db() as c:
        c.execute('UPDATE documents SET owner_id=2 WHERE id=?',(doc_id,))
        c.execute('DELETE FROM document_access WHERE document_id=?',(doc_id,))


def test_bm25_prefers_concentrated_evidence_and_normalizes_russian(env):
    fact='Поставка картона состоится 20 ноября. Переплётный участок готов.'
    _,short=document(env['irina'],fact)
    _,long=document(env['irina'],fact+' '+'Служебная информация. '*200)
    result=search(env['irina'])
    assert result.status_code==200,result.text
    assert [row['id'] for row in result.json()['results']]==[short,long]
    assert search(env['irina'],'переплетный участок').json()['results'][0]['id']==short


def test_private_corpus_does_not_change_public_rank_or_enter_temp_index(env,monkeypatch):
    _,first=document(env['irina'],'Поставка картона состоится 20 ноября.')
    _,second=document(env['irina'],'Поставка картона состоится после проверки партии 25 ноября.')
    before=search(env['irina']).json()['results']
    for _ in range(15):
        did,_=document(env['irina'],'Поставка картона: СЕКРЕТНЫЙ МАРКЕР. '+'картона '*100)
        make_private(did)
    original=index.ranked;observed=[]
    def checked(c,rows,question,**kwargs):
        observed.extend(row['text'] for row in rows)
        assert all('СЕКРЕТНЫЙ МАРКЕР' not in row['text'] for row in rows)
        return original(c,rows,question,**kwargs)
    monkeypatch.setattr(index,'ranked',checked)
    after=search(env['irina']).json()['results']
    assert [row['id'] for row in after]==[row['id'] for row in before]
    assert {row['id'] for row in after}=={first,second} and observed


def test_secret_never_enters_snippet_or_qa_index(env,monkeypatch):
    did,_=document(env['irina'],'Поставка картона состоится 20 ноября.')
    with store.db() as c:c.execute("UPDATE documents SET confidentiality='secret' WHERE id=?",(did,))
    assert search(env['irina']).json()['results']==[]
    assert env['irina'].post('/api/meet/qa',json={'question':'Когда состоится поставка картона?'}).json()['status']=='insufficient_data'
    assert not env['model'].calls
    assert env['irina'].get(f'/api/meet/documents/{did}/download').status_code==200


def test_repeated_search_rebuilds_after_acl_edit_delete_and_leaves_no_index(env):
    did,fid=document(env['irina'],'Поставка картона состоится 20 ноября.',shared='2')
    assert search(env['petr']).json()['results'][0]['id']==fid
    assert search(env['petr']).json()['results'][0]['id']==fid
    with store.db() as c:c.execute('DELETE FROM document_access WHERE document_id=?',(did,))
    assert search(env['petr']).json()['results']==[]
    with store.db() as c:c.execute('UPDATE fragments SET text=? WHERE document_id=?',('Новый график обслуживания оборудования.',did))
    assert search(env['irina']).json()['results']==[]
    assert search(env['irina'],'график обслуживания').json()['results'][0]['id']==fid
    with store.db() as c:
        c.execute('DELETE FROM fragments WHERE document_id=?',(did,))
        assert not c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'focus_search%'").fetchall()
        assert not c.execute("SELECT name FROM sqlite_temp_master WHERE name LIKE 'focus_search%'").fetchall()
    assert search(env['irina'],'график обслуживания').json()['results']==[]


def test_meeting_context_filters_before_fts_and_qa_preserves_sources(env,monkeypatch):
    did,fid=document(env['irina'],'Поставка картона состоится 20 ноября.')
    document(env['irina'],'Поставка картона по другому проекту состоится 25 ноября.')
    mid=meeting(env['irina'],[did]);seen=[];original=index.ranked
    def checked(c,rows,question,**kwargs):
        seen.extend(row['id'] for row in rows)
        return original(c,rows,question,**kwargs)
    monkeypatch.setattr(index,'ranked',checked)
    result=env['irina'].post('/api/meet/qa',json={'question':'Когда поставка картона?','meeting_id':mid})
    assert result.status_code==200,result.text
    assert result.json()['status']=='grounded'
    assert [source['id'] for source in result.json()['sources']]==[fid]
    assert seen==[int(fid[1:])]


@pytest.mark.parametrize('query',['" OR title:секрет NEAR(*) --','*','OR NOT AND','; DROP TABLE documents;','\u200b',''])
def test_query_syntax_is_data_never_fts_or_sql_operators(env,query):
    document(env['irina'],'Поставка картона состоится 20 ноября.')
    r=search(env['irina'],query)
    assert r.status_code==200 and r.json()['results']==[]
    assert len(env['irina'].get('/api/meet/documents').json()['documents'])==1


def test_no_data_no_model_and_invalid_query_bound(env):
    assert search(env['irina']).json()['results']==[]
    assert env['irina'].post('/api/meet/qa',json={'question':'Какие сроки поставки картона?'}).json()['status']=='insufficient_data'
    assert not env['model'].calls
    assert search(env['irina'],'x'*2001).status_code==422


def test_auditor_cannot_use_content_search_and_denial_is_audited(env):
    document(env['irina'],'Поставка картона состоится 20 ноября.')
    with store.db() as c:c.execute("UPDATE users SET level='auditor' WHERE login='irina'")
    assert search(env['irina']).status_code==403
    with store.db() as c:
        row=c.execute("SELECT result FROM audit WHERE action='access_denied' ORDER BY id DESC LIMIT 1").fetchone()
        assert row and row[0]=='denied'


def test_search_backend_failure_is_safe_audited_and_recovers(env,monkeypatch):
    document(env['irina'],'Поставка картона состоится 20 ноября.')
    original=index.ranked
    def down(*args,**kwargs):raise sqlite3.OperationalError('backend secret/path')
    monkeypatch.setattr(index,'ranked',down)
    r=search(env['irina'])
    assert r.status_code==503 and r.json()['code']=='search_unavailable' and 'backend secret' not in r.text
    r=env['irina'].post('/api/meet/qa',json={'question':'Когда поставка картона?'})
    assert r.status_code==503 and r.json()['code']=='search_unavailable'
    assert not env['model'].calls
    with store.db() as c:
        assert c.execute("SELECT COUNT(*) FROM audit WHERE error_code='search_unavailable'").fetchone()[0]>=2
    monkeypatch.setattr(index,'ranked',original)
    assert search(env['irina']).json()['results']
