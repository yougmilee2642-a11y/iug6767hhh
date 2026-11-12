"""PII minimization before EVERY meetings model call, including injected doubles.

Only CRM customer names are pseudonymized; employee names remain available for
attribution of tasks. No model output is automatically trusted or restored: the
existing validators display evidence from authorized stored sources. Tokens are
request-local and never grant access to another source.
"""
import re
from contextlib import closing
import sqlite3
import unicodedata

from meetings import store
from providers.local_settings import LocalAIError

EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+', re.UNICODE)
PHONE = re.compile(r'(?<![\w\d])(?:\+[ \t]*\d{1,3}(?:[ \t().-]*\d){7,12}|8[ \t]*0(?:[ \t().-]*\d){9})(?!\d)')
CARD = re.compile(r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)')
PASSPORT = re.compile(r'(?<!\w)(?:[A-ZА-Я]{2}\s?\d{7}|(?:паспорт|passport)\s*[:№]?\s*[A-ZА-Я0-9 -]{7,18})(?!\w)', re.I)
UNP = re.compile(r'(?i)(?:УНП|UNP|идентификационный номер)\s*[:№]?\s*\d{9,14}')
ADDRESS = re.compile(r'(?i)(?:\bул\.|\bулица|\bпроспект|\bпр-т|\bпер\.|\bпереулок)\s+[А-ЯA-Zа-яa-zЁё0-9 .-]{2,60},?\s+(?:д\.?\s*)?\d+[А-Яа-яA-Za-z]?(?:\s*[,;]?\s*(?:кв\.?|квартира)\s*\d+)?')


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', str(text)) if unicodedata.category(c) != 'Cf')


def mask_normalized(value):
    output = []
    for char in unicodedata.normalize('NFC', str(value)):
        if unicodedata.category(char) == 'Cf':
            continue
        compatible = unicodedata.normalize('NFKC', char)
        if len(compatible) == 1 and compatible.isascii() and (compatible.isalnum() or compatible in '+@.-()/:'):
            char = compatible
        output.append(char)
    return ''.join(output)


def customer_names():
    path = store.db_path()
    if not path.is_file():
        return []
    # A privacy guard must not create/migrate a DB as a side effect of a pure extraction call.
    try:
        # sqlite3's own context manager only commits; closing() releases the file (Windows locks it otherwise).
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='crm_customers'").fetchone():
                return []
            return [r[0] for r in c.execute('SELECT display_name FROM crm_customers') if len(r[0].strip()) >= 3]
    except sqlite3.Error:
        raise LocalAIError('privacy_unavailable') from None


class Masker:
    def __init__(self, names=()):
        self.names = sorted({mask_normalized(name) for name in names}, key=len, reverse=True)
        self.replacements = {}
        self.counts = {}
        self.prefix = ''

    def _token(self, kind, original):
        pair = (kind, original)
        if pair not in self.replacements:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.replacements[pair] = f'[{self.prefix}{kind}-{self.counts[kind]}]'
        return self.replacements[pair]

    def text(self, value):
        text = mask_normalized(value)
        # A user-supplied placeholder cannot impersonate a replacement token.
        if not self.replacements and not self.prefix:
            self.prefix = 'ПДН-' if re.search(r'\[(?:КЛИЕНТ|ТЕЛЕФОН|EMAIL|КАРТА|ПАСПОРТ|УНП|АДРЕС)-\d+\]', text) else ''
        for name in self.names:
            pattern = r'(?<!\w)' + r'\s+'.join(re.escape(part) for part in name.split()) + r'(?!\w)'
            text = re.sub(pattern, lambda match: self._token('КЛИЕНТ', name), text, flags=re.I)
        for kind, pattern in [('EMAIL', EMAIL), ('ТЕЛЕФОН', PHONE), ('ПАСПОРТ', PASSPORT),
                              ('УНП', UNP), ('АДРЕС', ADDRESS), ('КАРТА', CARD)]:
            text = pattern.sub(lambda match: self._token(kind, match.group()), text)
        return text

    def value(self, value):
        if isinstance(value, str): return self.text(value)
        if isinstance(value, list): return [self.value(item) for item in value]
        if isinstance(value, dict): return {key: self.value(item) for key, item in value.items()}
        return value


def private_json(provider, system, user, schema, predict=1500):
    masker = Masker(customer_names())
    return provider.json(masker.text(system), masker.text(user), masker.value(schema), predict=predict)


def prohibited_intent(question):
    """Deterministic restriction of dangerous USER intentions; source text is never an instruction.

    This is a bounded intent guard, not a general semantic classifier. Future adapters must also
    restrict operations independently of this bounded wording detector.
    """
    text = normalized(question).casefold().replace('ё', 'е')
    rules = [
        ('hr_decision', r'\b(?:уволить|уволь|увол[ьи]|премиру|премировать|депремиру|оштрафуй|оштрафовать|понизь\s+(?:сотрудник|его|ее|иван)|понизить\s+(?:сотрудник|должност)|повысить\s+зарплат)'),
        ('payment_action', r'\b(?:выплати|выплатить|начисли\s+(?:преми|зарплат)|начислить\s+(?:преми|зарплат)|оплати|оплатить|заплати|заплатить|перечисли|перечислить|спиши|списать|выстави\s+счет|переведи\s+(?:деньги|средства|\d)|перевести\s+(?:деньги|средства))'),
        ('contract_signing', r'\b(?:подпиши|подписать|подписывай|заключи|заключить)\b.{0,90}\b(?:договор|контракт|соглашени)'),
        ('salary_disclosure', r'\b(?:покажи|показать|раскрой|раскрыть|выведи|выгрузи|список|сколько|какая|какие)\b.{0,90}\b(?:зарплат|оклад|зарабатыва)|\b(?:зарплат|оклад)\w*\s+(?:иван|сотрудник|петров|директор)'),
        ('personal_data_disclosure', r'\b(?:покажи|раскрой|выгрузи|экспортируй|пришли|отправь|список)\b.{0,90}\b(?:персональн|телефон\w*\s+клиент|e-?mail\w*\s+клиент|паспорт|номер\w*\s+карт|фио\s+клиент)'),
    ]
    for code, pattern in rules:
        if re.search(pattern, text): return code
    return None


def refusal(code):
    responsible = 'HR' if code in ('hr_decision','salary_disclosure') else 'финансовому ответственному' if code == 'payment_action' else 'ответственному за договоры' if code == 'contract_signing' else 'ответственному за защиту данных'
    return ('Ассистент не выполняет кадровые, платёжные и договорные действия и не раскрывает зарплаты или персональные данные. '
            f'Обратитесь к {responsible}; решение принимает уполномоченный человек.')


def source_is_injection(text):
    value = normalized(text).casefold().replace('_', ' ').replace('ё', 'е')
    return bool(re.search(
        r'игнорир\w*(?:\s+\w+){0,4}\s+(?:инструк|правил)|ignore\s+(?:all\s+)?(?:previous|prior|system|the)'
        r'|системн\w*\s+(?:промпт|инструк)|system\s*prompt|<\|(?:im_start|system)\|>|role\s*[:=]\s*system'
        r'|ты\s+теперь\s+(?:админ|administrator)|you\s+are\s+now\s+(?:admin|system)'
        r'|отметь(?:\s+все)?\s+задач\w*\s+выполненн|выполни\w*\s+команд'
        r'|отправь\s+(?:письмо\s+)?на\s+\S+@|(?:раскрой|выведи|reveal)\s+(?:секрет|парол|secret|password)'
        r'|покажи\s+(?:все\s+)?бюджет|rm\s+-rf|(?:curl|powershell|cmd\.exe)\s', value))
