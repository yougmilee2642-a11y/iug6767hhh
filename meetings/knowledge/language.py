"""Small lexical normalizer for Russian questions; no model or new dependencies.

Quoted names and numeric anchors are checked separately and never stemmed.
This is conservative word matching, not a claim of semantic understanding.
"""
import re

from meetings import textutil as tu

QUESTION_STOP = frozenset(('какой какая какие какое каков какова каково каковы какими каким какую какому '
    'когда где кто сколько чем почему зачем расскажи расскажите рассказать покажи покажите '
    'подскажи подскажите скажи скажите сказать уточни уточните напомни напомните '
    'пожалуйста можешь можете можно узнать известно есть существуют имеются '
    'документ документа документы вопрос').split())
ENDINGS = tuple(sorted(('иями ями ами ого ему ому ыми ими ий ый ой ая яя ое ее ые ие '
    'ом ем ам ям ах ях ов ев ей ую юю ым им а я ы и у ю е о ь').split(), key=len, reverse=True))
ALIASES = {'релиз': 'запуск'}
RUSSIAN = re.compile(r'^[а-я]+$')
ABBREVIATIONS = frozenset('тыс млн млрд руб коп г гг стр рис табл п пп т д е им ул пр обл мин сек ч др Mr Dr Ms Mrs etc'.lower().split())


def lexeme(word):
    if word.isdigit() or not RUSSIAN.fullmatch(word):
        return word
    for ending in ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            word = word[:-len(ending)]
            break
    word = ALIASES.get(word, word)
    # One stable length avoids шлюз/шлюза/шлюзом becoming three different keys.
    return word[:6]


def terms(question):
    return {lexeme(word) for word in tu.words(question)
            if word not in QUESTION_STOP and (len(word) > 2 or word.isdigit())}


def relevance(text, query):
    if not query:
        return 0
    tokens = {lexeme(word) for word in tu.words(text)}
    if not {word for word in query if word.isdigit()} <= tokens:
        return 0
    return len(tokens & query) / len(query)


def sentences(text):
    """Conservative boundaries: do not detach units or newline qualifications."""
    output, start = [], 0
    for boundary in re.finditer(r'(?<=[.!?])\s+', text):
        if text[boundary.start() - 1] == '.':
            word = re.search(r'([A-Za-zА-Яа-яЁё]+)\.$', text[:boundary.start()])
            if word and (word[1].lower() in ABBREVIATIONS or (len(word[1]) == 1 and word[1].isupper())):
                continue
        part = text[start:boundary.start()].strip()
        if part:
            output.append(part)
        start = boundary.end()
    final = text[start:].strip()
    if final:
        output.append(final)
    return output
