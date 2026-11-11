"""Deterministic checks that keep model output honest: quotes, names and dates must exist in stored text."""
import re
from datetime import date

_WORD = re.compile(r'[0-9a-zа-яё]+', re.I)
STOP = set('и в во не на с со по к ко о об от до за из у же ли бы то что как а но да нет это мы вы он она они я ты '
           'его ее её их там тут так все всё ещё еще уже для при над под или'.split())

MONTHS = {'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'ма': 5, 'июн': 6, 'июл': 7, 'август': 8,
          'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12}


def norm(text: str) -> str:
    return ' '.join(_WORD.findall((text or '').lower().replace('ё', 'е')))


def words(text: str) -> list[str]:
    return [w for w in norm(text).split() if w not in STOP]


def stem(word: str) -> str:
    """Crude Russian stem: fixed prefix so that подготовить/подготовлю, перенос/перенести, Анна/Анне match."""
    word = word.lower().replace('ё', 'е')
    if len(word) <= 3:
        return word
    return word[:3] if len(word) == 4 else word[:4] if len(word) == 5 else word[:5]


def overlap(quote: str, source: str) -> float:
    q = {stem(w) for w in words(quote)}
    if not q:
        return 0.0
    s = {stem(w) for w in words(source)}
    return len(q & s) / len(q)


def find_exact(quote: str, source: str) -> str | None:
    """Return the exact substring of `source` that matches `quote` up to case/punctuation, else None."""
    quote_norm = norm(quote)
    if len(quote_norm) < 6:
        return None
    if quote_norm not in norm(source):
        return None
    tokens = quote_norm.split()
    # Map back to original text: locate first and last token occurrences in order.
    lowered = source.lower().replace('ё', 'е')
    positions = [(m.start(), m.end()) for m in _WORD.finditer(lowered)]
    source_tokens = [lowered[a:b] for a, b in positions]
    for i in range(len(source_tokens) - len(tokens) + 1):
        if source_tokens[i:i + len(tokens)] == tokens:
            return source[positions[i][0]:positions[i + len(tokens) - 1][1]]
    return None


def verify_quote(quote: str, source: str, threshold: float = 0.6) -> str | None:
    """Verified quote is ALWAYS text taken from storage, never the model's wording."""
    exact = find_exact(quote, source)
    if exact:
        return exact
    if quote and overlap(quote, source) >= threshold:
        return source.strip()
    return None


def name_mentioned(name: str, text: str) -> bool:
    if not name:
        return False
    name_stems = {stem(w) for w in words(name) if len(w) > 2}
    text_stems = {stem(w) for w in words(text)}
    return bool(name_stems & text_stems)


def resolve_participant(name: str, participants: list[str]) -> str:
    for participant in participants:
        first = words(participant)[:1]
        if first and name_mentioned(first[0], name):
            return participant
        if norm(participant) == norm(name):
            return participant
    return name.strip()


_ORD_UNITS = {'перв': 1, 'втор': 2, 'трет': 3, 'четверт': 4, 'пят': 5, 'шест': 6, 'седьм': 7, 'восьм': 8, 'девят': 9}
_ORD_TEENS = {'десят': 10, 'одиннадцат': 11, 'двенадцат': 12, 'тринадцат': 13, 'четырнадцат': 14, 'пятнадцат': 15,
              'шестнадцат': 16, 'семнадцат': 17, 'восемнадцат': 18, 'девятнадцат': 19, 'двадцат': 20, 'тридцат': 30}


def _ordinal_day(text: str) -> str:
    """ASR writes dates in words: «до двадцать пятого ноября» -> «до 25 ноября»."""
    def number(match):
        tens, unit = match[1], match[2]
        value = 0
        if tens:
            value = 20 if tens.startswith('двадцать') else 30
        if unit:
            word = unit.lower()
            value += next((v for k, v in sorted(_ORD_TEENS.items(), key=lambda kv: -len(kv[0])) if word.startswith(k)),
                          0) or next((v for k, v in _ORD_UNITS.items() if word.startswith(k)), 0)
        return f' {value} ' if 1 <= value <= 31 else match[0]
    pattern = (r'(?:\b(двадцать|тридцать)\s+)?\b((?:перв|втор|трет|четверт|пят|шест|седьм|восьм|девят|десят|одиннадцат|'
               r'двенадцат|тринадцат|четырнадцат|пятнадцат|шестнадцат|семнадцат|восемнадцат|девятнадцат|двадцат|'
               r'тридцат)\w*)(?=\s+[а-я]+)')
    return re.sub(pattern, number, text)


def parse_due(text: str, reference: date) -> str | None:
    """Explicit dates only. Relative phrases ('на следующей неделе') stay unparsed -> shown as text."""
    if not text:
        return None
    lowered = _ordinal_day(text.lower().replace('ё', 'е'))
    m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', lowered)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r'\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b', lowered)
    if m:
        year = int(m[3]) if m[3] else reference.year
        year = year + 2000 if year < 100 else year
        return _roll(_safe(year, int(m[2]), int(m[1])), reference, bool(m[3]))
    m = re.search(r'\b(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?', lowered)
    if m:
        for prefix, month in MONTHS.items():
            if m[2].startswith(prefix) and (prefix != 'ма' or m[2] in ('мая', 'май')):
                year = int(m[3]) if m[3] else reference.year
                return _roll(_safe(year, month, int(m[1])), reference, bool(m[3]))
    return None


def _safe(year, month, day):
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _roll(value, reference, explicit_year):
    if value and not explicit_year and date.fromisoformat(value) < reference.replace(day=1):
        parsed = date.fromisoformat(value)
        return _safe(parsed.year + 1, parsed.month, parsed.day)
    return value


_COMMIT = re.compile(r'\b(я|беру|возьму|сделаю|подготовлю|займусь|берусь)\b', re.I)


def self_commitment(text: str) -> bool:
    """Speaker takes the task on themselves («Я подготовлю…») — the speaker is then the stated assignee."""
    return bool(_COMMIT.search(text or ''))


def date_mentioned(due_text: str, text: str) -> bool:
    if not due_text:
        return False
    if find_exact(due_text, text):
        return True
    digits = re.findall(r'\d+', due_text)
    return bool(digits) and all(d in re.findall(r'\d+', text) for d in digits)


# Text a local model writes for the user must be plain Russian/Latin prose. Small models sometimes switch language
# mid-sentence or leak JSON/markdown into a field; such text is never shown as a result.
_ALLOWED_TEXT = re.compile(r"[0-9A-Za-zА-Яа-яЁё\s.,:;!?()\[\]«»\"'„“”‘’\-–—%№/+×*=<>&#@$€₽°…]*")
_MARKUP = re.compile(r'```|^\s*[{\[]|[{}]|\n|</?\w+>')


def clean_model_text(text) -> str | None:
    """Return the stripped text if it is plain prose, else None (foreign script, control chars, markup)."""
    value = ' '.join(str(text or '').split())
    if not value or not _ALLOWED_TEXT.fullmatch(value) or _MARKUP.search(value):
        return None
    if len(re.findall(r'[A-Za-zА-Яа-яЁё]', value)) < 2:
        return None
    return value
