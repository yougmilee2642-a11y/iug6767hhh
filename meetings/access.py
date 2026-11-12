"""One policy for object decisions and pre-ranking SQL selection.

Capabilities permit an operation; ACL/classification permits an object. Technical
administrators and auditors never acquire content access through ownership.
"""
from dataclasses import dataclass

CONTENT_LEVELS = {'director', 'head', 'lead', 'employee', 'contractor'}
CLASSIFICATIONS = {'public', 'internal', 'department', 'confidential', 'secret'}
READ_ACTIONS = {'meetings.read', 'documents.read', 'document.read', 'meeting.read', 'metric.read', 'model.read'}
TABLES = {'document': ('documents', 'document_access', 'document_id'),
          'meeting': ('meetings', 'meeting_access', 'meeting_id'),
          'metric': ('production_metrics', 'production_metric_access', 'metric_id')}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason_code: str


def load_user(connection, user_id):
    row = connection.execute('SELECT u.*,d.code AS department_code,d.name AS department_name FROM users u '
                             'LEFT JOIN departments d ON d.id=u.department_id WHERE u.id=?', (user_id,)).fetchone()
    if not row:
        return None
    user = dict(row)
    user.pop('password_hash', None)
    from meetings import store
    user['_delegations'] = []
    if user['active'] and user['level'] in ('head', 'lead', 'employee'):
        user['_delegations'] = [dict(r) for r in connection.execute(
            'SELECT g.id,g.from_user,g.department_id,g.starts_at,g.ends_at FROM delegations g '
            'JOIN users grantor ON grantor.id=g.from_user WHERE g.to_user=? AND g.revoked_at IS NULL '
            'AND julianday(g.starts_at)<=julianday(?) AND julianday(g.ends_at)>julianday(?) '
            "AND grantor.active=1 AND (grantor.level='director' OR (grantor.level='head' AND grantor.department_id=g.department_id))",
            (user_id, store.now(), store.now()))]
    user['_delegated_departments'] = [g['department_id'] for g in user['_delegations']]
    return user


def decide(user, action, obj):
    from meetings.auth import has_capability
    user, obj = user or {}, dict(obj or {})
    if not user.get('id') or not user.get('active', 1):
        return Decision(False, 'inactive_user')
    level = user.get('level')
    classification = obj.get('confidentiality', 'confidential')
    if classification not in CLASSIFICATIONS:
        return Decision(False, 'invalid_classification')
    if level and level not in CONTENT_LEVELS:
        return Decision(False, 'content_role_denied')
    if action == 'model.read' and classification == 'secret':
        return Decision(False, 'secret_model_denied')
    owner = obj.get('owner_id') == user['id']
    explicit = owner or bool(obj.get('_shared'))
    same_department = obj.get('department_id') is not None and obj.get('department_id') == user.get('department_id')
    delegated = obj.get('department_id') in user.get('_delegated_departments', [])
    # Legacy rows/users preserve released ACL behaviour; a role is not an ACL.
    attribute = level and classification != 'secret' and (
        level == 'director' or classification == 'public' or
        (classification == 'internal' and level != 'contractor') or
        (classification == 'department' and ((same_department and level in ('head', 'lead')) or delegated)))
    if not (explicit or attribute):
        return Decision(False, 'object_scope_denied')
    capability = 'meetings.read' if action in READ_ACTIONS else action
    if not has_capability(user, capability):
        return Decision(False, 'capability_denied')
    if action in READ_ACTIONS:
        return Decision(True, 'explicit_acl' if explicit else 'classification_scope')
    from meetings.auth import CAPABILITIES
    if user.get('_delegated_departments') and action not in CAPABILITIES.get(level, ()) and not delegated:
        return Decision(False, 'delegated_scope_only')
    if not level:
        return Decision(True, 'legacy_capability_and_acl')
    if level == 'employee' and action in ('transcript.edit', 'protocol.edit') and not delegated and not owner:
        return Decision(False, 'own_meeting_only')
    if level == 'employee' and action == 'tasks.change' and not delegated:
        return Decision(obj.get('assignee_user_id') == user['id'], 'own_task_status_only')
    if level == 'contractor' and not owner:
        return Decision(False, 'own_document_only')
    if level == 'lead' and not (same_department or delegated):
        return Decision(False, 'own_department_only')
    if user.get('_delegated_departments') and not (level in ('director', 'head', 'lead') or owner or delegated):
        return Decision(False, 'delegated_scope_only')
    return Decision(True, 'capability_and_scope')


def predicate(connection, actor, kind, alias, *, model=False):
    """SQL and bound params, evaluated before ranking, LIMIT and aggregation.

    `kind`/`alias` are internal identifiers, never request data. Mirrors decide's
    read policy; tests compare both policies for every role/classification/ACL.
    """
    if kind not in TABLES or not alias.isidentifier():
        raise ValueError('Unsupported content selector')
    user = load_user(connection, actor)
    if not user or not user.get('active') or (user.get('level') and user['level'] not in CONTENT_LEVELS):
        return '0', []
    from meetings.auth import has_capability
    if not has_capability(user, 'meetings.read'):
        return '0', []
    _, acl, fk = TABLES[kind]
    scope = f'({alias}.owner_id=? OR EXISTS (SELECT 1 FROM {acl} acl WHERE acl.{fk}={alias}.id AND acl.user_id=?)'
    params = [actor, actor]
    level = user.get('level')
    if level:
        if level == 'director':
            scope += f" OR {alias}.confidentiality IN ('public','internal','department','confidential')"
        else:
            scope += f" OR {alias}.confidentiality='public'"
            if level != 'contractor':
                scope += f" OR {alias}.confidentiality='internal'"
            if level in ('head', 'lead') and user.get('department_id') is not None:
                scope += f" OR ({alias}.confidentiality='department' AND {alias}.department_id=?)"
                params.append(user['department_id'])
            deps = user.get('_delegated_departments', [])
            if deps:
                scope += f" OR ({alias}.confidentiality='department' AND {alias}.department_id IN ({','.join('?' for _ in deps)}))"
                params.extend(deps)
    scope += ')'
    scope += f" AND {alias}.confidentiality IN ('public','internal','department','confidential','secret')"
    if model:
        scope += f" AND {alias}.confidentiality!='secret'"
    return '(' + scope + ')', params


def object_decision(connection, user_id, kind, object_id, action=None):
    table, acl, fk = TABLES[kind]
    row = connection.execute(f'SELECT o.*,EXISTS (SELECT 1 FROM {acl} a WHERE a.{fk}=o.id AND a.user_id=?) AS _shared '
                             f'FROM {table} o WHERE o.id=?', (user_id, object_id)).fetchone()
    return decide(load_user(connection, user_id), action or kind + '.read', row) if row else Decision(False, 'not_found')


def snapshot_predicate(connection, actor, alias='s', *, own_column=None):
    """Department scope for source-system snapshots, before grouping/limiting.

    Source snapshots have no object ACL yet. Employee own-row projections are
    available only when the caller supplies a known server-side column.
    """
    if not alias.isidentifier() or own_column not in (None, 'user_id', 'agent_user_id', 'responsible_user_id'):
        raise ValueError('Unsupported snapshot selector')
    user = load_user(connection, actor)
    if not user or not user['active'] or user.get('level') not in CONTENT_LEVELS:
        return '0', []
    level = user['level']
    clauses, params = [f"{alias}.confidentiality='public'"], []
    if level == 'director':
        clauses = [f"{alias}.confidentiality IN ('public','internal','department','confidential')"]
    else:
        if level != 'contractor': clauses.append(f"{alias}.confidentiality='internal'")
        departments = list(user.get('_delegated_departments', []))
        if level in ('head','lead') and user['department_id'] is not None: departments.append(user['department_id'])
        if departments:
            clauses.append(f"({alias}.confidentiality='department' AND {alias}.department_id IN ({','.join('?' for _ in departments)}))")
            params.extend(departments)
        if level == 'employee' and own_column:
            clauses.append(f"({alias}.confidentiality='department' AND {alias}.{own_column}=?)")
            params.append(actor)
    return '(' + ' OR '.join(clauses) + ')', params
