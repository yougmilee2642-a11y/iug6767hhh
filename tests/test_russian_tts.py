import pytest
from services.russian_tts import prepare_russian_speech


def test_letters_not_a_word():
    assert prepare_russian_speech('Помощник МТС. Мой MTS.')=='Помощник +эм т+э +эс. Мой +эм т+э +эс.'


def test_does_not_touch_parts_of_words():
    assert prepare_russian_speech('МТСбанк тестовый контекст')=='МТСбанк тестовый контекст'


def test_explicit_stress_and_yo_are_preserved():
    assert prepare_russian_speech('Тест. звонит. Всё ещё счёт.')=='т+ест. звон+ит. Всё ещё счёт.'
    assert prepare_russian_speech('пл+ачу')=='пл+ачу'


def test_no_ssml_injection_or_markdown_pronounced():
    assert prepare_russian_speech('**Тест** <break time="99s"/> [МТС](https://www.mts.by/)')=='т+ест +эм т+э +эс'


def test_identifiers_preserve_all_digits():
    text=prepare_russian_speech('Наберите *100#. Телефон +375 29 123 45 67.')
    assert 'звёздочка один ноль ноль решётка' in text
    assert 'плюс три семь пять два девять один два три четыре пять шесть семь' in text


def test_mixed_alphabet_does_not_mangle_normal_latin_names():
    assert prepare_russian_speech('Это тeст. CallWise и Wi-Fi.')=='Это т+ест. кол вайз и вай фай.'


def test_plain_mode_for_other_tts_engines():
    assert prepare_russian_speech('МТС: тест.',silero_stress=False)=='эм тэ эс: тест.'


@pytest.mark.parametrize('phrase',['Договор звонит в МТС.','Это тест.','Проверьте Wi-Fi.'])
def test_preparation_is_idempotent(phrase):
    once=prepare_russian_speech(phrase)
    assert prepare_russian_speech(once)==once


@pytest.mark.parametrize('text,expected', [
    ('Цена 50 BYN.', 'пятьдесят белорусских рублей'),
    ('Цена 21 BYN.', 'двадцать один белорусский рубль'),
    ('Цена 50.75 BYN.', 'пятьдесят белорусских рублей семьдесят пять копеек'),
    ('В 15:00 и 18:30.', 'пятнадцать часов ровно'),
    ('Скидка 10%.', 'десять процентов'),
    ('Длительность 60 минут.', 'шестьдесят минут'),
    ('Телефон 375291234567.', 'три семь пять два девять один два три четыре пять шесть семь'),
])
def test_numeric_values_are_spoken_as_words(text, expected):
    import re
    spoken = prepare_russian_speech(text)
    assert expected in spoken
    assert not re.search(r'\d', spoken)
    assert prepare_russian_speech(spoken) == spoken
