import json
import pytest
from meetings import llm,store
from providers.local_settings import LocalAIError
from tests.test_track3_briefing import env


def document(env):
    r=env['prod_head'].post('/api/meet/documents',files={'file':('summary.txt','Материал для выбора ключевых положений.'.encode())})
    assert r.status_code==200,r.text
    did=r.json()['document']['id']
    with store.db() as c:
        c.execute('DELETE FROM fragments WHERE document_id=?',(did,))
        for i in range(7):
            c.execute('INSERT INTO fragments(document_id,idx,location,text) VALUES (?,?,?,?)',
                      (did,i+1,f'раздел{i+1}',f'Положение {i+1}: проверка сроков производства. Контакт demo@example.invalid.'))
    return did


def provider(callback):
    class Double:
        model='scripted-summary-selector'
        def json(self,system,user,schema,predict=1500):
            assert 'demo@example.invalid' not in user and '<<<' in user
            return callback(json.loads(user),schema)
    llm.set_llm(Double())


def test_selector_chooses_salient_ids_but_every_claim_remains_verbatim(env):
    did=document(env)
    def choose(data,schema):
        ids=[p['id'] for p in data['fragments']]
        return {'fragment_ids':[ids[-1],ids[0],ids[3]]}
    provider(choose)
    r=env['prod_head'].get(f'/api/meet/documents/{did}/summary?semantic=true');assert r.status_code==200,r.text
    result=r.json();assert result['mode']=='selected_excerpts' and len(result['claims'])==3
    assert result['claims'][0]['text'].startswith('Положение 7')
    for claim in result['claims']:
        source=claim['sources'][0]
        assert claim['text']==source['quote']
        actual=env['prod_head'].get('/api/meet/fragments/'+source['id'])
        assert actual.status_code==200 and claim['text']==actual.json()['fragment']['text']
    with store.db() as c:
        audit=c.execute("SELECT * FROM audit WHERE action='document_summary' ORDER BY id DESC LIMIT 1").fetchone()
        assert audit['model']=='scripted-summary-selector' and len(json.loads(audit['source_ids']))==3


@pytest.mark.parametrize('mode',['unknown','duplicate','extra','empty','oversized'])
def test_model_cannot_forge_claim_or_source(env,mode):
    did=document(env)
    def invalid(data,schema):
        ids=[p['id'] for p in data['fragments']]
        return {'unknown':{'fragment_ids':['F999999',*ids[:2]]},
                'duplicate':{'fragment_ids':[ids[0],ids[0],ids[1]]},
                'extra':{'fragment_ids':ids[:3],'claim':'Выдуманное поручение'},
                'empty':{'fragment_ids':[]},'oversized':{'fragment_ids':ids}}[mode]
    provider(invalid)
    r=env['prod_head'].get(f'/api/meet/documents/{did}/summary?semantic=true')
    assert r.status_code==503 and r.json()['code']=='model_invalid_reply'
    assert 'claims' not in r.json()


@pytest.mark.parametrize('change',['text','revoke','supersede'])
def test_mutation_during_model_call_rechecks_snapshot_and_access(env,change):
    did=document(env)
    def mutate(data,schema):
        with store.db() as c:
            if change=='text':c.execute('UPDATE fragments SET text=text || ? WHERE document_id=?',(' Изменено.',did))
            elif change=='revoke':c.execute("UPDATE documents SET confidentiality='secret' WHERE id=?",(did,))
            else:
                row=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
                c.execute('INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at,version,supersedes_id) VALUES (?,?,?,?,?,?,?,?,?)',
                          (row['owner_id'],'Замена','next.txt','txt',b'next','next-hash',store.now(),2,did))
        return {'fragment_ids':[p['id'] for p in data['fragments'][:3]]}
    provider(mutate)
    r=env['prod_head'].get(f'/api/meet/documents/{did}/summary?semantic=true')
    assert r.status_code==(404 if change=='revoke' else 409),r.text
    assert 'claims' not in r.json()


def test_secret_or_foreign_never_reaches_selector_and_down_is_safe(env):
    did=document(env);calls=[]
    provider(lambda *_:calls.append(1))
    assert env['designer'].get(f'/api/meet/documents/{did}/summary?semantic=true').status_code==404
    with store.db() as c:c.execute("UPDATE documents SET confidentiality='secret' WHERE id=?",(did,))
    assert env['prod_head'].get(f'/api/meet/documents/{did}/summary?semantic=true').status_code==404 and not calls
    with store.db() as c:c.execute("UPDATE documents SET confidentiality='internal' WHERE id=?",(did,))
    def down(*_):raise LocalAIError('unavailable')
    provider(down)
    assert env['prod_head'].get(f'/api/meet/documents/{did}/summary?semantic=true').status_code==503
