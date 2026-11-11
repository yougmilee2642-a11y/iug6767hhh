"""Stop unsent notifications; never erase or reverse already confirmed external actions."""
import storage


def cancel_pending(interaction_id):
    with storage.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='tg_outbox'").fetchone():
            db.execute("UPDATE tg_outbox SET status='cancelled',error='privacy_withdrawn' WHERE interaction_id=? AND status IN ('pending','retry')", (interaction_id,))
