"""Conservative spoken form only; never alters stored dialogue or its meaning.

Not a Russian grammar corrector. Ambiguous stress and ё remain model-owned.
Silero-specific stress marks are generated only from a small explicit lexicon.
"""
import re
import unicodedata

ALIASES = {
    'мтс': 'эм тэ эс', 'mts': 'эм тэ эс',
    'смс': 'эс эм эс', 'sms': 'эс эм эс',
    'ussd': 'ю эс эс ди', 'юссд': 'ю эс эс ди',
    'api': 'эй пи ай', 'ai': 'эй ай', 'ии': 'и и',
    'ip': 'ай пи', 'wi-fi': 'вай фай', 'wifi': 'вай фай',
    'callwise': 'кол вайз', 'sim': 'сим', 'sip': 'сип',
}
STRESS = {'тест': 'т+ест', 'эм': '+эм', 'тэ': 'т+э', 'эс': '+эс',
          'звонит': 'звон+ит', 'позвоните': 'позвон+ите',
          'договор': 'догов+ор', 'каталог': 'катал+ог', 'тариф': 'тар+иф'}
CONFUSABLES = str.maketrans({'A':'А','a':'а','B':'В','C':'С','c':'с','E':'Е','e':'е',
    'H':'Н','K':'К','k':'к','M':'М','O':'О','o':'о','P':'Р','p':'р','T':'Т','X':'Х','x':'х','y':'у'})
DIGITS = dict(zip('0123456789', ['ноль','один','два','три','четыре','пять','шесть','семь','восемь','девять']))


def counted(number, forms):
    return forms[2] if 11 <= number % 100 <= 14 else forms[0] if number % 10 == 1 else forms[1] if 2 <= number % 10 <= 4 else forms[2]


def number_words(number, feminine=False):
    number = int(number)
    if number == 0:
        return 'ноль'
    if number < 0:
        return 'минус ' + number_words(-number, feminine)
    if number >= 10**9:
        return ' '.join(DIGITS[d] for d in str(number))
    words = []
    for scale, forms, gender in [(10**6, ('миллион', 'миллиона', 'миллионов'), False),
                                  (1000, ('тысяча', 'тысячи', 'тысяч'), True)]:
        amount, number = divmod(number, scale)
        if amount:
            words.extend([number_words(amount, gender), counted(amount, forms)])
    hundreds, number = divmod(number, 100)
    if hundreds:
        words.append(['', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот', 'шестьсот', 'семьсот', 'восемьсот', 'девятьсот'][hundreds])
    if 10 <= number < 20:
        words.append(['десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать', 'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать'][number - 10])
    else:
        tens, units = divmod(number, 10)
        if tens:
            words.append(['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто'][tens])
        if units:
            words.append(('одна' if units == 1 else 'две') if feminine and units in (1, 2) else DIGITS[str(units)])
    return ' '.join(words)


def spoken_numbers(text):
    def money(match):
        whole, fraction = match[1], match[2]
        amount = int(whole)
        result = number_words(amount) + ' ' + counted(amount, ('белорусский рубль', 'белорусских рубля', 'белорусских рублей'))
        if fraction:
            cents = int(fraction.ljust(2, '0'))
            result += ' ' + number_words(cents, True) + ' ' + counted(cents, ('копейка', 'копейки', 'копеек'))
        return result
    text = re.sub(r'(?<!\w)(\d+)(?:[.,](\d{1,2}))?\s*BYN\b', money, text, flags=re.I)
    def clock(match):
        hours, minutes = int(match[1]), int(match[2])
        return (number_words(hours) + ' ' + counted(hours, ('час', 'часа', 'часов'))
                + (' ровно' if minutes == 0 else ' ' + number_words(minutes, True) + ' ' + counted(minutes, ('минута', 'минуты', 'минут'))))
    text = re.sub(r'(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)', clock, text)
    def calendar(match):
        months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        return number_words(match[3]) + ' ' + months[int(match[2]) - 1] + ' ' + number_words(match[1]) + ' года'
    text = re.sub(r'\b(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b', calendar, text)
    text = re.sub(r'\b(\d+)\s*%', lambda m: number_words(m[1]) + ' ' + counted(int(m[1]), ('процент', 'процента', 'процентов')), text)
    # Remaining numeric identifiers/decimals retain every digit, including leading zeroes.
    text = re.sub(r'(?<!\w)\d+[.,]\d+(?!\w)', lambda m: number_words(m[0].replace(',', '.').split('.')[0]) + ' точка ' + ' '.join(DIGITS[d] for d in re.split(r'[.,]', m[0])[1]), text)
    return re.sub(r'\d+', lambda m: ' '.join(DIGITS[d] for d in m[0]) if len(m[0]) >= 7 or m[0].startswith('0') and len(m[0]) > 1 else number_words(m[0]), text)


def prepare_russian_speech(text: str, *, silero_stress=True) -> str:
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]', '', text)
    text = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', text)
    text = re.sub(r'https?://[^\s<>]+', 'ссылка', text)
    # Literal model output must not become executable SSML.
    text = re.sub(r'<[^>]*>', ' ', text)
    text = re.sub(r'\*\*([^*]+)\*\*|__([^_]+)__', lambda m: m.group(1) or m.group(2), text)
    # An identifier is spoken digit-by-digit, not as a financial amount.
    text = re.sub(r'\*([0-9]{1,6})#', lambda m: 'звёздочка ' + ' '.join(DIGITS[d] for d in m.group(1)) + ' решётка', text)
    text = re.sub(r'(?<![\w+])\+([0-9][0-9 ()-]{5,27}[0-9])(?!\d)',
        lambda m: 'плюс ' + ' '.join(DIGITS[d] for d in m.group(1) if d.isdigit()), text)
    text = spoken_numbers(text)
    def homogenize(match):
        word=match.group(0)
        return word.translate(CONFUSABLES) if re.search('[А-Яа-яЁё]', word) else word
    text=re.sub(r'[А-Яа-яЁёA-Za-z]+', homogenize, text)
    names='|'.join(re.escape(word) for word in sorted(ALIASES,key=len,reverse=True))
    text=re.sub(r'(?<!\w)(?:'+names+r')(?!\w)',lambda m:ALIASES[m.group(0).casefold()],text,flags=re.I)
    if silero_stress:
        words='|'.join(re.escape(word) for word in STRESS)
        text=re.sub(r'(?<![\w+])(?:'+words+r')(?![\w+])',lambda m:STRESS[m.group(0).casefold()],text,flags=re.I)
    text=re.sub(r'[*_`#|]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()
