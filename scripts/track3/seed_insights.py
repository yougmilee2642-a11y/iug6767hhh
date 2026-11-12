"""Independent versioned extension; frozen v1/v2 extraction/QA fixtures stay intact."""
import hashlib,json
from datetime import timedelta
from pathlib import Path
from meetings import store


def seed(c):
    raw=(Path(__file__).resolve().parents[2]/'demo/track3/seasonality.json').read_bytes()
    data=json.loads(raw);digest=hashlib.sha256(raw).hexdigest()
    old=c.execute('SELECT manifest_sha256 FROM demo_imports WHERE dataset=?',(data['dataset'],)).fetchone()
    if old:
        if old[0]!=digest:raise ValueError('Расширение истории изменилось: используйте новую тестовую БД.')
        return
    dep=c.execute("SELECT id FROM departments WHERE code='PROD'").fetchone()
    if not dep:return
    for i,row in enumerate(data['history']):
        start=store.parse_aware(row['start'])
        c.execute('INSERT INTO seasonality_samples VALUES (?,?,?,?,?,?,?,?,?)',
            (data['dataset']+':history:'+str(i),dep[0],'department',data['as_of'],data['section'],row['start'],
             store.iso_utc(start+timedelta(days=7)),row['occupied'],row['available']))
    # Explicit synthetic deadlines, not an assumed carrier storage policy.
    snapshot=json.loads((Path(__file__).resolve().parents[2]/'demo/track3/v2/snapshots.json').read_text(encoding='utf-8'))
    orders=[o for o in snapshot['orders'] if o['status']=='pickup']
    logistics=c.execute("SELECT id FROM departments WHERE code='LOG'").fetchone()
    for order,offset in zip(orders,data['pickup_offsets_days']):
        expires=store.iso_utc(store.parse_aware(data['as_of'])+timedelta(days=offset))
        c.execute("UPDATE erp_orders SET storage_expires_at=? WHERE order_no=? AND source_id=? AND storage_expires_at IS NULL AND status='pickup'",
                  (expires,order['order_no'],order['source_id']))
        if logistics:
            c.execute('INSERT INTO pickup_storage VALUES (?,?,?,?,?,?,?)',(order['order_no'],expires,order['carrier_code'],
                data['dataset']+':pickup:'+order['order_no'],data['as_of'],logistics[0],'department'))
    c.execute('INSERT INTO demo_imports VALUES (?,?,?,?)',(data['dataset'],digest,store.now(),'{}'))
