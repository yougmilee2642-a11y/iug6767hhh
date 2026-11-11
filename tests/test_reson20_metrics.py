from scripts.benchmark_reson20 import align,normalized,distance


def test_normalization_keeps_number_and_brand_format_differences():
    assert normalized('Ээ, Эко-Пылесос: «ёлка»! Мм.')=='эко пылесос елка'
    assert align('пятьдесят рублей','50 рублей')['word_errors']==1
    assert align('Теле два','Теле2')['exact'] is False


def test_substitutions_deletions_and_insertions_match_known_alignment():
    score=align('первое второе третье','первое замена третье лишнее')
    assert score['counts']=={'substitute':1,'delete':0,'insert':1}
    assert score['word_errors']==2 and score['wer']==2/3
    assert align('первое второе третье','первое третье')['counts']['delete']==1


def test_refused_transcription_is_scored_as_all_words_missing():
    score=align('Назовите номер телефона','')
    assert score['wer']==1 and score['counts']['delete']==3
    assert distance('abc','adc')==1
