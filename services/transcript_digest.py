"""Extractive overview of user utterances; never a verified fact or AI summary."""


def transcript_digest(state):
    transcript = state.get('transcript') or []
    user_turns = [(index, item.get('content', '')) for index, item in enumerate(transcript)
                  if item.get('role') == 'user' and isinstance(item.get('content'), str) and item['content'].strip()]
    selected = user_turns[-3:]
    quotes = [{'turn_index': index, 'text': text[:400], 'truncated': len(text)>400} for index, text in selected]
    return {'kind': 'transcript_quotes', 'source': 'user_transcript', 'quotes': quotes,
            'omitted_user_turns': len(user_turns)-len(selected),
            'conversation_status': state.get('status'), 'verified_fields': False}
