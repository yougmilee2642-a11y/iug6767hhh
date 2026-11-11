"""Conservative Russian booking facts. No model inference, fuzzy prices or slot invention."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from services.business_hours import within_hours


def label_pattern(label):
    words=label.casefold().split()
    result=[]
    for word in words:
        if len(word)>4 and re.fullmatch('[а-яё]+',word):
            if word.endswith('ие'): pattern=re.escape(word[:-2])+r'(?:ие|ия|ию|ии|ием)'
            elif word.endswith('а'): pattern=re.escape(word[:-1])+r'(?:а|у|ы|е|ой|ою)'
            elif word.endswith('я'): pattern=re.escape(word[:-1])+r'(?:я|ю|и|е|ей)'
            else: pattern=re.escape(word)+r'(?:а|у|ом|е|ы)?'
        else:pattern=re.escape(word)
        result.append(pattern)
    return r'\b'+r'\s+'.join(result)+r'\b'


def service_matches(text,knowledge):
    result=[]
    aliases=knowledge.get('service_aliases',{})
    for service in knowledge.get('services',[]):
        key=service.get('id',service['name'])
        configured=aliases.get(key,[]) if isinstance(aliases,dict) else []
        labels=[service['name'],*(configured if isinstance(configured,list) else [])]
        for label in labels:
            if not isinstance(label,str) or not label.strip():continue
            matches=list(re.finditer(label_pattern(label),text,re.I))
            if any(not re.search(r'\b(?:не(?:\s+на)?|вместо)\s*$',text[:match.start()],re.I) for match in matches):
                result.append(service);break
    return result


def booking_request(text):
    return bool(re.search(r'\b(?:записаться|записать|запишите|запиши|забронировать|забронируйте|бронь)\b',text,re.I))


def unknown_service(text,knowledge):
    if not booking_request(text):return None
    for match in re.finditer(r'\bна\s+(?:услугу\s+)?([^,.!?;]+)',text,re.I):
        candidate=re.split(r'\b(?:сегодня|завтра|послезавтра|вчера|в\s+(?:\d|[а-яё]+\s+час|пять|шесть|семь|восемь|девять|десять)|к\s+|меня зовут|мой телефон)\b',match[1],maxsplit=1,flags=re.I)[0].strip()
        if (not candidate or re.match(r'^(?:\d|сегодня|завтра|послезавтра|пятниц|суббот|воскрес|понедель|вторник|сред|четверг|ближайш|любое время)',candidate,re.I)):
            continue
        if not service_matches(candidate,knowledge):return candidate[:100]
    return None


def time_candidates(text,hours):
    # Contact declarations are not clock expressions. Keep other clauses intact.
    value=re.sub(r'\b(?:мой телефон|мой номер|номер телефона|телефон для связи)\s*[:—-]?\s*\+?[\d ()-]{7,30}',' ',text,flags=re.I)
    value=re.sub(r'\b\d{4}-\d{2}-\d{2}\b','',value)
    value=re.sub(r'\+?\d(?:[ ()-]*\d){6,}','',value)
    value=re.sub(r'\b(?:цена|стоит|стоимость)\s+\d+(?:[.,]\d+)?(?:\s*(?:BYN|руб\w*))?',' ',value,flags=re.I)
    if re.search(r'\bне\b.+\bа\b',value,re.I):value=re.split(r'\bа\b',value,flags=re.I)[-1]
    clocks=re.findall(r'(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?!\d)',value)
    if clocks:return sorted({f'{int(hour):02d}:{minute}' for hour,minute in clocks})
    numeric=re.search(r'\b(?:в|на|после)\s+(\d{1,2})\b',value,re.I) or re.fullmatch(r'\s*(\d{1,2})(?:\s+час(?:а|ов)?)?[.!]?\s*',value)
    minute=0
    if numeric:
        hour=int(numeric[1])
        if hour>23:return []
        tail=value[numeric.end():]
        minutes=re.search(r'^\s*(?:час(?:а|ов)?\s*)?(\d{1,2})(?:\s*минут\w*)?(?:[.!?]|$)',tail,re.I)
        if minutes:
            minute=int(minutes[1])
            if minute>59:return []
    else:
        pattern='|'.join(sorted(map(re.escape,hours),key=len,reverse=True))
        if re.fullmatch(r'\s*(?:'+pattern+r')(?:\s+час(?:а|ов)?)?[.!]?\s*',value,re.I):value='в '+value
        match=re.search(r'\b(?:в|на|после)\s+('+pattern+r')(?:\s+(один|два|три))?\b',value,re.I)
        if not match:return []
        hour=hours[match[1].casefold()]
        if hour==20 and match[2]:hour+=hours[match[2].casefold()]
        minute_words={**{key:number for key,number in hours.items() if number<20},
                      'двадцать':20,'тридцать':30,'сорок':40,'пятьдесят':50}
        suffix=value[match.end():].strip()
        minute_pattern='|'.join(sorted(map(re.escape,minute_words),key=len,reverse=True))
        parsed=re.match(r'('+minute_pattern+r')(?:\s+('+minute_pattern+r'))?\b',suffix,re.I)
        if parsed:
            minute=minute_words[parsed[1].casefold()]
            if minute>=20 and parsed[2] and minute_words[parsed[2].casefold()]<10:minute+=minute_words[parsed[2].casefold()]
    if re.search(r'\b(?:утра|ночи)\b',value,re.I):candidates={hour%12}
    elif re.search(r'\bвечера\b',value,re.I):candidates={hour%12+12 if hour<12 else hour}
    elif re.search(r'\bдня\b',value,re.I):candidates={hour+12 if hour<12 else hour}
    elif 0<hour<12:candidates={hour,hour+12}
    else:candidates={hour}
    return [f'{candidate:02d}:{minute:02d}' for candidate in sorted(candidates)]


def resolve_time(candidates,config,day,service):
    if len(candidates)<2:return candidates
    # Disambiguate AM/PM only using published working hours, never remaining availability.
    try:
        zone=ZoneInfo(config.business.timezone)
        working=[clock for clock in candidates if within_hours(datetime.fromisoformat(day+'T'+clock).replace(tzinfo=zone),
                 service['duration_minutes'],config.business.schedule,zone)]
    except (ValueError,TypeError):return candidates
    return working if len(working)==1 else candidates
