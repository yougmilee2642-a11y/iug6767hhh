"""Explicit SQL cleanup with reviewable counts; no filesystem deletion or model calls."""
import json
from datetime import timedelta
from pathlib import Path
from meetings import access,confirmations,store
from meetings.auth import MeetError


def exists(c,table):return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())


def policy(c):return dict(c.execute('SELECT * FROM retention_policy WHERE id=1').fetchone())


def clean(c,now=None):
    now=now or store.parse_aware(store.now());p=policy(c);counts={}
    chat=store.iso_utc(now-timedelta(days=p['chat_days']))
    for table,column in [('assistant_messages','created_at'),('assistant_evidence','created_at'),('qa_answers','generated_at')]:
        counts[table]=c.execute(f'DELETE FROM {table} WHERE julianday({column})<julianday(?)',(chat,)).rowcount
    c.execute('DELETE FROM assistant_conversations WHERE NOT EXISTS (SELECT 1 FROM assistant_messages m WHERE m.conversation_id=assistant_conversations.id)')
    cutoff=store.iso_utc(now-timedelta(days=p['transcript_days']))
    mids=[r[0] for r in c.execute('SELECT id FROM meetings WHERE julianday(COALESCE(scheduled_at,created_at))<julianday(?)',(cutoff,))]
    counts['utterances']=0
    for mid in mids:
        counts['utterances']+=c.execute('DELETE FROM utterances WHERE meeting_id=?',(mid,)).rowcount
        if exists(c,'media_segments'):
            c.execute('DELETE FROM media_segments WHERE job_id IN (SELECT id FROM media_jobs WHERE meeting_id=?)',(mid,))
        c.execute("UPDATE protocol_items SET quotes='[]' WHERE meeting_id=?",(mid,))
        c.execute("UPDATE protocols SET summary='[]' WHERE meeting_id=?",(mid,))
        for task in c.execute('SELECT id,source_quote FROM tasks WHERE meeting_id=?',(mid,)).fetchall():
            try:manual=json.loads(task['source_quote']).get('kind')=='manual_request'
            except (TypeError,ValueError):manual=False
            if not manual:c.execute('UPDATE tasks SET source_quote=? WHERE id=?',(json.dumps({'kind':'expired_source','text':'','source_at':store.iso_utc(now)}),task['id']))
        c.execute("UPDATE decision_controls SET source_quote='{}' WHERE protocol_item_id IN (SELECT id FROM protocol_items WHERE meeting_id=?)",(mid,))
    if exists(c,'media_assets'):
        # Confirmed protocol may be partial: keep audio until all items were reviewed.
        ids=[r[0] for r in c.execute('SELECT m.id FROM meetings m WHERE '
            '(julianday(COALESCE(m.scheduled_at,m.created_at))<julianday(?) OR (?=1 AND EXISTS '
            '(SELECT 1 FROM protocol_items p WHERE p.meeting_id=m.id) AND NOT EXISTS '
            '(SELECT 1 FROM protocol_items p WHERE p.meeting_id=m.id AND p.confirmed_at IS NULL)))',(cutoff,p['audio_after_confirm']))]
        counts['audio']=sum(c.execute('DELETE FROM media_assets WHERE meeting_id=?',(mid,)).rowcount for mid in ids)
    counts['tokens']=confirmations.purge(c,now-timedelta(days=1))
    counts['audit']=c.execute('DELETE FROM audit WHERE julianday(at)<julianday(?)',(store.iso_utc(now-timedelta(days=p['audit_days'])),)).rowcount
    c.execute('DELETE FROM notifications WHERE julianday(created_at)<julianday(?)',(chat,))
    c.execute('DELETE FROM weekly_digest_outbox WHERE julianday(created_at)<julianday(?)',(chat,))
    c.execute('DELETE FROM smtp_outbox WHERE julianday(created_at)<julianday(?)',(chat,))
    return counts


def test_marker():
    path=store.db_path().resolve();marker=Path(str(path)+'.track3.json')
    try:raw=json.loads(marker.read_text())
    except (OSError,ValueError):raise MeetError(403,'test_marker_required','Очистка разрешена только для явно помеченной тестовой БД.') from None
    if marker.is_symlink() or raw.get('db')!=str(path):raise MeetError(403,'test_marker_required','Некорректный маркер тестовой БД.')
    return path


BUSINESS_TABLES=('smtp_outbox','weekly_digest_outbox','pickup_storage','seasonality_samples','action_basis','protocol_mail_outbox','notification_outbox','notifications','task_comments','task_history','task_origins','decision_controls',
    'media_segments','media_assets','media_jobs','calls','task_effect_checks','commitments',
    'assistant_messages','assistant_evidence','assistant_conversations','qa_answers','calendar_provider_outbox','calendar_outbox','calendar_event_participants',
    'calendar_events','calendar_import_state','calendar_busy','calendar_subscriptions','integration_outbox','mock_crm_objects',
    'tasks','protocol_items','protocols','utterances','preps','meeting_documents','meeting_access','meetings',
    'document_access','fragments','document_version_drafts','documents','meeting_series','order_events','support_interactions',
    'crm_deals','erp_orders','crm_customers','production_metric_access','production_metrics','production_plan','finance_aggregates',
    'hr_absences','work_shifts','demo_imports')


def cleanup_preview(c):
    test_marker()
    return {t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in BUSINESS_TABLES if exists(c,t)}


def cleanup(c,keep_token):
    counts=cleanup_preview(c)
    for t in BUSINESS_TABLES:
        if exists(c,t):c.execute('DELETE FROM '+t)
    c.execute('DELETE FROM confirmations WHERE id!=?',(keep_token,))
    return counts


def delete_user(c,user_id):
    # Keep a non-personal FK stub so records of other owners remain consistent.
    user=access.load_user(c,user_id)
    if not user:return {}
    c.execute('DELETE FROM smtp_outbox WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM weekly_digest_outbox WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM task_effect_checks WHERE owner_id=?',(user_id,))
    counts={'meetings':c.execute('SELECT count(*) FROM meetings WHERE owner_id=?',(user_id,)).fetchone()[0],
            'documents':c.execute('SELECT count(*) FROM documents WHERE owner_id=?',(user_id,)).fetchone()[0]}
    owned_tasks=[r[0] for r in c.execute('SELECT t.id FROM tasks t JOIN meetings m ON m.id=t.meeting_id WHERE m.owner_id=?',(user_id,))]
    c.execute("DELETE FROM action_basis WHERE confirmed_by=? OR (object_type='meeting' AND object_id IN (SELECT id FROM meetings WHERE owner_id=?)) OR (object_type='task' AND object_id IN (SELECT t.id FROM tasks t JOIN meetings m ON m.id=t.meeting_id WHERE m.owner_id=?))",(user_id,user_id,user_id))
    for tid in owned_tasks:
        c.execute("DELETE FROM mock_crm_objects WHERE kind='task' AND object_id=?",(tid,))
        c.execute("DELETE FROM integration_outbox WHERE object_type='task' AND object_id=?",(tid,))
    c.execute('DELETE FROM integration_outbox WHERE confirmed_by=?',(user_id,))
    if user['personnel_code']:
        for table in ('hr_absences','work_shifts'):
            if table=='hr_absences':c.execute('DELETE FROM hr_absences WHERE personnel_code=?',(user['personnel_code'],))
            else:c.execute('DELETE FROM work_shifts WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM protocol_mail_outbox WHERE recipient_id=?',(user_id,))
    c.execute('DELETE FROM notification_settings WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM calendar_import_state WHERE user_id=?',(user_id,))
    c.execute('UPDATE meetings SET series_id=NULL WHERE series_id IN (SELECT id FROM meeting_series WHERE owner_id=?)',(user_id,))
    c.execute('DELETE FROM meeting_series WHERE owner_id=?',(user_id,))
    c.execute('DELETE FROM tasks WHERE meeting_id IN (SELECT id FROM meetings WHERE owner_id=?)',(user_id,))
    c.execute('DELETE FROM meetings WHERE owner_id=?',(user_id,))
    # Delete all editions of owned documents together; self-reference is checked at statement end.
    c.execute('UPDATE documents SET supersedes_id=NULL WHERE supersedes_id IN (SELECT id FROM documents WHERE owner_id=?)',(user_id,))
    c.execute('DELETE FROM documents WHERE owner_id=?',(user_id,))
    c.execute("UPDATE tasks SET assignee_user_id=NULL,assignee=NULL,assignee_status='unknown',version=version+1 WHERE assignee_user_id=?",(user_id,))
    c.execute('DELETE FROM assistant_conversations WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM assistant_evidence WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM qa_answers WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM notifications WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM feedback WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM task_comments WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM user_external_ids WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM delegations WHERE from_user=? OR to_user=?',(user_id,user_id))
    c.execute('DELETE FROM calendar_event_participants WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM calendar_outbox WHERE recipient_id=?',(user_id,))
    c.execute('DELETE FROM calendar_events WHERE organizer_id=?',(user_id,))
    c.execute('DELETE FROM calendar_busy WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM calendar_subscriptions WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM confirmations WHERE user_id=?',(user_id,))
    c.execute('DELETE FROM task_origins WHERE user_id=?',(user_id,))
    c.execute("UPDATE users SET login=?,name='Удалённый пользователь',active=0,password_hash='',personnel_code=NULL,manager_id=NULL WHERE id=?",('deleted-'+str(user_id),user_id))
    return counts
