from services.transcript_digest import transcript_digest


def test_quotes_do_not_promote_assistant_claims_or_action_fields():
    state={'status':'stopped','transcript':[{'role':'user','content':'Не хочу доставку за 50 BYN.'},
        {'role':'assistant','content':'Доставка оформлена.'}], 'action_result':{'phone':'invented'}}
    result=transcript_digest(state)
    assert result['quotes']==[{'turn_index':0,'text':'Не хочу доставку за 50 BYN.','truncated':False}]
    assert result['verified_fields'] is False and 'invented' not in str(result)
    assert 'Доставка оформлена' not in str(result)


def test_digest_marks_omitted_and_truncated_utterances():
    state={'status':'active','transcript':[{'role':'user','content':'x'*500} for _ in range(5)]}
    result=transcript_digest(state)
    assert result['omitted_user_turns']==2
    assert [q['turn_index'] for q in result['quotes']]==[2,3,4]
    assert all(q['truncated'] and len(q['text'])==400 for q in result['quotes'])
