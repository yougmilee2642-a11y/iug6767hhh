"""Review employee external-ID mappings; never infer permission from the CRM role."""
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,Field
from meetings import access,confirmations,store
from meetings.api import ConfirmTokenIn
from meetings.auth import MeetError,MeetRoute,current_user,require
from meetings.connectors.factory import connector,name
from meetings.connectors.mock import MockCRM,digest
from meetings.connectors.contracts import IntegrationError


class Mapping(BaseModel):
    model_config=ConfigDict(extra='forbid')
    user_id: int=Field(gt=0)
    external_id: str=Field(min_length=1,max_length=100)


class Mappings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mappings: list[Mapping]=Field(min_length=1,max_length=500)


def directory(c,user):
    require(user,'integrations.manage',action='integrations.employees')
    if name()==MockCRM.name:
        return [{'external_id':r['external_id'],'name':r['name']} for r in c.execute(
            "SELECT u.name,x.external_id FROM users u JOIN user_external_ids x ON x.user_id=u.id WHERE u.active=1 AND u.level NOT IN ('admin','auditor') AND x.connector=?",(name(),))]
    return connector(c,user['id']).list_external_users()


def checked(c,user,rows):
    external={r['external_id']:r for r in directory(c,user)};uids=[r['user_id'] for r in rows];ids=[r['external_id'] for r in rows]
    if len(set(uids))!=len(uids) or len(set(ids))!=len(ids):raise MeetError(422,'duplicate_mapping','Каждый сотрудник и внешний ID выбираются один раз.')
    snapshots=[]
    for row in rows:
        local=access.load_user(c,row['user_id'])
        if not local or not local['active'] or local['level'] in ('admin','auditor') or row['external_id'] not in external:
            raise MeetError(422,'invalid_mapping','Сотрудник или внешний ID недоступен.')
        old=c.execute('SELECT user_id FROM user_external_ids WHERE connector=? AND external_id=?',(name(),row['external_id'])).fetchone()
        if old and old[0] not in uids:raise MeetError(409,'mapping_conflict','Внешний ID уже связан с другим сотрудником.')
        snapshots.append({'id':local['id'],'active':local['active'],'level':local['level'],'department_id':local['department_id'],
                          'external':external[row['external_id']]})
    before=[dict(r) for r in c.execute('SELECT * FROM user_external_ids WHERE connector=? ORDER BY user_id',(name(),))]
    return digest({'connector':name(),'snapshots':snapshots,'before':before})


def router():
    api=APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/integrations/employees')
    def employees(request: Request):
        user=current_user(request)
        with store.db() as c:
            try:rows=directory(c,user)
            except IntegrationError as e:raise MeetError(503,e.code,str(e)) from None
            store.audit(c,user['id'],'integration_directory_read',object_type='integration')
            mappings = c.execute("SELECT x.user_id,x.external_id FROM user_external_ids x JOIN users u ON u.id=x.user_id "
                                 "WHERE u.active=1 AND u.level NOT IN ('admin','auditor') AND x.connector=?", (name(),))
            return {'employees': rows, 'connector': name(), 'mappings': [dict(r) for r in mappings]}

    @api.post('/api/meet/integrations/employees/preview')
    def preview(payload: Mappings,request: Request):
        user=current_user(request);require(user,'integrations.manage',action='integrations.sync')
        rows=[r.model_dump() for r in payload.mappings]
        with store.write_tx() as c:
            try:proof=checked(c,user,rows)
            except IntegrationError as e:raise MeetError(503,e.code,str(e)) from None
            token=confirmations.create(c,user,'integration.mappings','integration',name(),None,{'rows':rows,'proof':proof,'connector':name()})
            store.audit(c,user['id'],'integration_sync_preview',object_type='integration',stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':{'mappings':rows,'notice':'Меняются только внешние ID. Локальные роли и доступ не изменяются.'}}

    @api.post('/api/meet/integrations/employees/confirm')
    def confirm(payload: ConfirmTokenIn,request: Request):
        user=current_user(request);require(user,'integrations.manage',action='integrations.sync')
        with store.write_tx() as c:
            p=confirmations.load(c,user,payload.confirmation_id,'integration.mappings',idempotency_key=payload.idempotency_key)
            if p['payload']['connector']!=name():raise MeetError(409,'connector_changed','Подключение изменилось.')
            if p['already']:return {**p['result'],'already_confirmed':True}
            try:proof=checked(c,user,p['payload']['rows'])
            except IntegrationError as e:raise MeetError(503,e.code,str(e)) from None
            if proof!=p['payload']['proof']:raise MeetError(409,'stale','Справочник или сопоставления изменились.')
            for row in p['payload']['rows']:c.execute('DELETE FROM user_external_ids WHERE user_id=? AND connector=?',(row['user_id'],name()))
            for row in p['payload']['rows']:c.execute('INSERT INTO user_external_ids VALUES (?,?,?)',(row['user_id'],name(),row['external_id']))
            result={'updated':len(p['payload']['rows']),'connector':name()}
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'integration_sync_confirmed',object_type='integration',stage='confirm',confirmation_id=payload.confirmation_id)
            return result

    return api
