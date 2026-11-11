"""Manual follow-up queue, not automatic calling, identity verification or CRM editing."""
from datetime import datetime, timezone
import storage

REASONS = {'refused_ai', 'change_or_late', 'unsupported', 'callback', 'audio_quality', 'privacy_withdrawn'}


def enqueue(state, reason):
    if reason not in REASONS: raise ValueError('Unknown review reason')
    with storage.connect() as db:
        db.execute('INSERT OR IGNORE INTO review_requests (interaction_id,agent_id,reason,status,created_at) VALUES (?,?,?,?,?)',
                   (state['id'], state['agent_id'], reason, 'pending', datetime.now(timezone.utc).isoformat()))
    return {'reason': reason, 'status': 'pending', 'automatic_call': False}
