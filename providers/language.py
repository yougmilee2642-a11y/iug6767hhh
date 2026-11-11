"""Language-specific speech/consent rules, independent of agent runtime."""
import re


_DIGITS = dict(zip(["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"], "0123456789"))
# Other number words (teens, tens, hundreds). A run containing any of them is NOT rewritten:
# turning only part of "двадцать девять один один" into digits would produce a wrong, plausible-looking phone.
_OTHER_NUMBERS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
                  "семнадцать", "восемнадцать", "девятнадцать", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
                  "семьдесят", "восемьдесят", "девяносто", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот",
                  "семьсот", "восемьсот", "девятьсот"]


def normalize_transcript(text: str, context: str = "", language: str = "ru") -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if language == "ru" and "телефон" in context.lower():
        words = "|".join(sorted([*_DIGITS, *_OTHER_NUMBERS], key=len, reverse=True))
        run = rf"\b(?:{words})(?:[\s,;.-]+(?:{words}))*\b"

        def convert(match):
            tokens = re.findall(rf"{words}", match[0].lower())
            if len(tokens) < 3 or any(token not in _DIGITS for token in tokens):
                return match[0]  # too short or ambiguous: leave the words for the customer to review
            return "".join(_DIGITS[token] for token in tokens)

        text = re.sub(run, convert, text, flags=re.I)
    return text


def is_confirmation(text: str, language: str) -> bool:
    # Full-string allowlist: 'да, но на другое время' is NOT consent to the old proposal.
    if "?" in text:
        return False
    normalized = re.sub(r"[.!?,]+", " ", text.casefold())
    normalized = " ".join(normalized.split())
    positive = {"да", "подтверждаю", "да подтверждаю", "да всё верно", "всё верно", "да все верно", "все верно", "согласен", "согласна", "да записывайте", "записывайте", "подтверждаю запись", "да спасибо"}
    return language == "ru" and normalized in positive


def is_explicit_handoff(text: str, patterns: list[str]) -> bool:
    clauses = re.split(r"[,;.!]|\bно\b", text, flags=re.I)
    for clause in clauses:
        if re.search(r"\bне\s+(?:нужен|нужна|нужно|надо|соединяйте|переводите)\s+(?:меня\s+(?:с|на)\s+)?(?:оператор|человек|сотрудник)", clause, re.I):
            continue
        if re.search(r"\bне\s+хочу\s+(?:(?:говорить|разговаривать|общаться)\s+с\s+)?(?:оператор|человек|сотрудник)", clause, re.I):
            continue
        if any(re.search(pattern, clause, re.I) for pattern in patterns):
            return True
    return False
