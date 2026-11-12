"""Only explicit identifiers are recognized; no inferred client/order binding."""
import re


def mentions(text):
    result = []
    for match in re.finditer(r'(?<![\w-])(?:PP-[0-9]{4}-[0-9]{5}|client-[0-9]{4})(?![\w-])',text or ''):
        value = match.group()
        link = {'kind':'order' if value.startswith('PP-') else 'customer','id':value}
        if link not in result: result.append(link)
        if len(result)==20: break
    return result


def visible_mentions(connection,user,text):
    from meetings import access
    result = []
    sql,args = access.snapshot_predicate(connection,user,'s')
    for link in mentions(text):
        table,key = ('erp_orders','order_no') if link['kind']=='order' else ('crm_customers','id')
        if connection.execute(f'SELECT 1 FROM {table} s WHERE s.{key}=? AND '+sql,[link['id'],*args]).fetchone():
            result.append(link)
    return result
