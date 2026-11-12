"""Explicit synthetic source adapters; no undocumented remote APIs are invented."""
from meetings import access,store
from meetings.connectors.mock import MockCRM


class MaryConnector(MockCRM):
    name='mary-mock'
    def events(self,order_no=None,customer_id=None):
        if order_no or customer_id:rows=self.find_interactions(order_no=order_no,customer_id=customer_id)
        else:
            self.check();scope,args=access.snapshot_predicate(self.c,self.actor['id'],'s',own_column='agent_user_id')
            rows=[dict(r) for r in self.c.execute('SELECT s.* FROM support_interactions s WHERE '+scope,args)]
        return [{'event_id':r['id'],'client_id':r['client_ref'],'order_id':r['order_no'],'actor':r['closed_by'],
                 'outcome':'closed_ai' if r['closed_by']=='ai' else 'handled_human','topic':r['topic_code'],
                 'first_response_seconds':r['first_response_seconds'],'sla_seconds':r['sla_seconds'],
                 **self.stamp(r['source_id'],r['as_of'])} for r in rows]


class OneCConnector(MockCRM):
    name='1c-mock'
    def aggregates(self):
        self.check();scope,args=access.snapshot_predicate(self.c,self.actor['id'],'s')
        return [{k:r[k] for k in ('source_id','as_of','revenue_minor','cost_minor','currency')} for r in self.c.execute('SELECT s.* FROM finance_aggregates s WHERE '+scope,args)]


class HRConnector(MockCRM):
    name='hr-mock'
    def aggregates(self):
        self.check();scope,args=access.snapshot_predicate(self.c,self.actor['id'],'s')
        return [{'source_id':r['source_id'],'as_of':r['as_of'],'start_at':r['start_at'],'end_at':r['end_at']}
                for r in self.c.execute('SELECT s.* FROM work_shifts s WHERE '+scope,args)]


class AmoCRMConnector:
    name='amocrm-stub'
    def connect(self):raise NotImplementedError('AmoCRM не используется в пилоте; требуется отдельный контракт.')


class ZohoConnector:
    name='zoho-stub'
    def connect(self):raise NotImplementedError('Zoho — историческая система; адаптер не реализован.')
