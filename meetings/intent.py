"""Conservative Russian action fields. Unknown/ambiguous values stay unknown.

This parser only prepares editable fields; it never executes an action.
"""
from datetime import date,datetime,time,timedelta,timezone
import re
from meetings import store

MONTHS=['январ','феврал','март','апрел','ма','июн','июл','август','сентябр','октябр','ноябр','декабр']
WEEKDAYS=['понедельник','вторник','сред','четверг','пятниц','суббот','воскресень']
ORDINALS=['перв','втор','трет','четверт','пят','шест','седьм','восьм','девят','десят','одиннадцат',
          'двенадцат','тринадцат','четырнадцат','пятнадцат','шестнадцат','семнадцат','восемнадцат','девятнадцат']
CARDINALS={'один':1,'одну':1,'одна':1,'два':2,'две':2,'три':3,'четыре':4,'пять':5,'шесть':6,'семь':7,'восемь':8,'девять':9,
           'десять':10,'пятнадцать':15,'двадцать':20,'тридцать':30,'сорок':40,'шестьдесят':60}


def norm(text):return ' '.join(text.casefold().replace('ё','е').split())


def number_words(text):
    # Date ordinals support case endings, including «двадцать шестое».
    text=norm(text)
    for base,word in [(30,'тридцать'),(20,'двадцать')]:
        for i,stem in enumerate(ORDINALS[:9],1):
            text=re.sub(r'\b'+word+r'\s+'+stem+r'(?:ое|ого|ому|ым|ом|ая|ой|ый|ий|ье|ья|ью)\b',str(base+i),text)
        for word2,value in CARDINALS.items():
            if value<10:text=re.sub(r'\b'+word+r'\s+'+word2+r'\b',str(base+value),text)
    for i,stem in reversed(list(enumerate(ORDINALS,1))):
        text=re.sub(r'\b'+stem+r'(?:ое|ого|ому|ым|ом|ая|ой|ый|ий|ье|ья|ью)\b',str(i),text)
    text=re.sub(r'\bдвадцат(?:ое|ого|ому|ый)\b','20',text)
    text=re.sub(r'\bтридцат(?:ое|ого|ому|ый)\b','30',text)
    for word,value in sorted(CARDINALS.items(),key=lambda p:-len(p[0])):
        text=re.sub(r'\b'+word+r'\b',str(value),text)
    return text


def aliases(word):
    word=norm(word);result={word}
    if word[-1:] in 'вгджзклмнпрстфхцчшщ':result.update(word+s for s in ('а','у','ом','е'))
    if word.endswith(('ов','ев','ин')):result.update(word+s for s in ('а','у','ым','е'))
    if word.endswith('а'):result.update(word[:-1]+s for s in ('у','е','ой','ы'))
    if word.endswith('я'):result.update(word[:-1]+s for s in ('ю','е','и'))
    if word.endswith('ий'):result.update(word[:-2]+s for s in ('ия','ию','ием','ии'))
    if word.endswith('ей'):result.update(word[:-1]+s for s in ('я','ю','ем','е'))
    if word.endswith(('ая','ой','ый')):result.update(word[:-2]+s for s in ('ой','ую','ого','ому','ым','ом'))
    return result


def people(c,user,text,kind,meeting_id=None):
    from meetings.calendar.service import directory
    allowed={p['id'] for p in directory(c)};department=user.get('department_id')
    if kind=='task' and meeting_id:
        row=c.execute('SELECT department_id FROM meetings WHERE id=?',(meeting_id,)).fetchone()
        if row:department=row[0]
    matched=[];text=norm(text)
    for row in c.execute("SELECT id,name,department_id FROM users WHERE active=1 AND (level IS NULL OR level NOT IN ('admin','auditor'))"):
        if row['id'] not in allowed:continue
        if kind=='task' and user.get('level')!='director' and row['department_id'] not in [department,*user.get('_delegated_departments',[])]:continue
        words=[w for w in norm(row['name']).split() if len(w)>=3]
        if any(re.search(r'(?<![а-яa-z])'+re.escape(alias)+r'(?![а-яa-z])',text) for w in words for alias in aliases(w)):
            matched.append(row['id'])
    if kind=='meeting':
        for code,stem in [('LOG','логистик'),('PROD','производств'),('SUP','поддержк'),('SALES','продаж')]:
            if re.search(r'\b'+stem,text):
                row=c.execute('SELECT head_user_id FROM departments WHERE code=?',(code,)).fetchone()
                if row and row[0] in allowed:matched.append(row[0])
    return list(dict.fromkeys(matched))


def day(text,now):
    today=now.astimezone(store.zone(store.DISPLAY_ZONE)).date();values=[];ambiguous=False
    for value in re.findall(r'\b\d{4}-\d{2}-\d{2}\b',text):
        try:values.append(date.fromisoformat(value))
        except ValueError:ambiguous=True
    for i,stem in enumerate(MONTHS,1):
        for found in re.finditer(r'\b(\d{1,2})\s+'+stem+r'[а-я]*(?:\s+(\d{4})(?:\s*года)?)?\b',text):
            try:
                value=date(int(found[2] or today.year),i,int(found[1]))
                if not found[2] and value<today:ambiguous=True
                else:values.append(value)
            except ValueError:ambiguous=True
    if re.search(r'\bпослезавтра\b',text):values.append(today+timedelta(days=2))
    if re.search(r'\bзавтра\b',text):values.append(today+timedelta(days=1))
    if re.search(r'\bсегодня\b',text):values.append(today)
    for i,stem in enumerate(WEEKDAYS):
        if re.search(r'\b'+stem+r'[а-я]*\b',text):
            delta=(i-today.weekday())%7
            if re.search(r'\bследующ\w*\s+'+stem,text):delta=7-today.weekday()+i
            values.append(today+timedelta(days=delta))
    for found in re.finditer(r'\bчерез\s+(\d{1,3})\s+(день|дня|дней|недел\w*)\b',text):
        n=int(found[1])*(7 if found[2].startswith('недел') else 1)
        if 1<=n<=365:values.append(today+timedelta(days=n))
        else:ambiguous=True
    unique=set(values)
    return next(iter(unique)) if len(unique)==1 and not ambiguous else None


def fields(c,user,text,kind,meeting_id=None,now=None):
    now=now or datetime.now(timezone.utc);parsed=number_words(text);when=day(parsed,now)
    selected=people(c,user,text,kind,meeting_id);missing=[]
    if kind=='task':
        owner=selected[0] if len(selected)==1 else None
        if owner is None:missing.append('ответственный')
        if when is None:missing.append('срок')
        return {'assignee_user_id':owner,'due':when.isoformat() if when else None,'requires_clarification':missing}
    duration=60
    found=re.search(r'\bна\s+(\d{1,3})\s*минут',parsed)
    if found and 15<=int(found[1])<=480:duration=int(found[1])
    elif re.search(r'\bна\s+полчаса\b',parsed):duration=30
    elif re.search(r'\bна\s+(?:1\s+)?час\b',parsed):duration=60
    if not selected:missing.append('участники')
    start=end=None
    clock=re.search(r'\bв\s+([01]?\d|2[0-3])(?:(?:[:.]([0-5]\d))(?!\d)|(?:\s*час(?:а|ов)?)?(?=\s*(?:$|[,;?!]|на\b|с\b|завтра\b|сегодня\b|послезавтра\b)))',parsed)
    if clock and clock[2] is None and int(clock[1])<9:clock=None  # ambiguous morning/evening spoken hour
    if when:
        zone=store.zone(store.DISPLAY_ZONE)
        if clock:
            value=datetime.combine(when,time(int(clock[1]),int(clock[2] or 0)),zone)
            start,end=value,value+timedelta(minutes=duration)
        else:
            start=datetime.combine(when,time(9),zone);end=datetime.combine(when,time(18),zone)
    if when is None:missing.append('дата')
    if clock is None:missing.append('время')
    return {'calendar_hint':{'participant_ids':selected,'range_start':start.isoformat() if start else None,
                            'range_end':end.isoformat() if end else None,'duration_minutes':duration,'timezone':store.DISPLAY_ZONE},
            'requires_clarification':missing}
