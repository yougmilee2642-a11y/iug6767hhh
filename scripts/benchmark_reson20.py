"""First 20 general_noisily rows: actual production ASR vs pinned official references.

No training, no reference hints, no dialogue turns, no production DB writes.
"""
import hashlib
import html
import io
import json
import os
import re
import statistics
import string
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
REVISION='21301635963415883d3868fd88b26d1df19881e9'
SUBSET='general_noisily'
SOURCE='https://huggingface.co/datasets/MTSAIR/mws-reson-asr-osd'
CACHE=ROOT/'downloads/reson-first20'
OUT=ROOT/'data/reson-first20'
PAGE=ROOT/'static/qa/reson-first20.html'


def normalized(text):
    text=unicodedata.normalize('NFKC',text).lower().replace('ё','е').replace('-',' ')
    text=''.join(c for c in text if not unicodedata.category(c).startswith('P'))
    return ' '.join(t for t in text.split() if t not in {'ээ','аа','мм'})


def align(reference,hypothesis):
    ref=normalized(reference).split();hyp=normalized(hypothesis).split()
    matrix=[[0]*(len(hyp)+1) for _ in range(len(ref)+1)]
    for i in range(len(ref)+1):matrix[i][0]=i
    for j in range(len(hyp)+1):matrix[0][j]=j
    for i in range(1,len(ref)+1):
        for j in range(1,len(hyp)+1):
            matrix[i][j]=min(matrix[i-1][j]+1,matrix[i][j-1]+1,matrix[i-1][j-1]+(ref[i-1]!=hyp[j-1]))
    operations=[];i,j=len(ref),len(hyp)
    while i or j:
        if i and j and ref[i-1]==hyp[j-1] and matrix[i][j]==matrix[i-1][j-1]:
            operations.append({'type':'equal','reference':ref[i-1],'hypothesis':hyp[j-1]});i-=1;j-=1
        elif i and j and matrix[i][j]==matrix[i-1][j-1]+1:
            operations.append({'type':'substitute','reference':ref[i-1],'hypothesis':hyp[j-1]});i-=1;j-=1
        elif i and matrix[i][j]==matrix[i-1][j]+1:
            operations.append({'type':'delete','reference':ref[i-1],'hypothesis':''});i-=1
        else:
            operations.append({'type':'insert','reference':'','hypothesis':hyp[j-1]});j-=1
    operations.reverse()
    counts={kind:sum(op['type']==kind for op in operations) for kind in ('substitute','delete','insert')}
    return {'reference_words':len(ref),'word_errors':matrix[-1][-1],
            'wer':matrix[-1][-1]/len(ref) if ref else (0 if not hyp else None),
            'exact':ref==hyp,'counts':counts,'operations':operations}


def distance(ref,hyp):
    prev=list(range(len(hyp)+1))
    for i,a in enumerate(ref,1):
        row=[i]
        for j,b in enumerate(hyp,1):row.append(min(row[-1]+1,prev[j]+1,prev[j-1]+(a!=b)))
        prev=row
    return prev[-1]


def download(relative):
    import requests
    path=CACHE/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_file():return path
    url=f'{SOURCE}/resolve/{REVISION}/{SUBSET}/{relative}'
    for attempt in range(4):
        try:
            response=requests.get(url,timeout=(30,90))
            response.raise_for_status()
            temp=path.with_suffix(path.suffix+'.part');temp.write_bytes(response.content);temp.replace(path)
            return path
        except Exception:
            if attempt==3:raise
            time.sleep(attempt+1)


def benchmark():
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TRANSFORMERS_OFFLINE']='1'
    import soundfile as sf
    import numpy as np
    from services import local_speech as speech,dual_asr
    from providers.language import normalize_transcript
    CACHE.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    metadata=download('metadata.jsonl')
    entries=[json.loads(line) for line in metadata.read_text(encoding='utf-8').splitlines() if line][:20]
    assert len(entries)==20
    if any(not re.fullmatch(r'wavs/[A-Za-z0-9_-]+\.wav',r['file_name']) for r in entries):
        raise ValueError('Unexpected audio path in dataset metadata')
    (OUT/'selection.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    began=time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:files=list(pool.map(lambda r:download(r['file_name']),entries))
    print(f'Downloaded {len(files)} files in {time.perf_counter()-began:.1f}s',flush=True)
    speech.warm_up()
    rows=[]
    for index,(entry,path) in enumerate(zip(entries,files),1):
        audio_bytes=path.read_bytes();waveform=dual_asr.decode_audio(audio_bytes)
        native,sample_rate=sf.read(path,dtype='float32')
        assert sample_rate==8000 and native.ndim==1
        identity=f'reson:{index}:{entry["id"]}'
        row={'number':index,**entry,'audio_sha256':hashlib.sha256(audio_bytes).hexdigest(),
             'native_sample_rate':sample_rate,'actual_duration':len(native)/sample_rate}
        began=time.perf_counter();preview='';packets=0
        try:
            for sequence,start in enumerate(range(0,len(waveform),14400)):
                buf=io.BytesIO();sf.write(buf,waveform[start:start+14400],16000,format='WAV',subtype='PCM_16')
                result=speech.transcribe_preview(buf.getvalue(),identity,'utterance',sequence)
                preview=result['raw_text'];packets+=1
            row.update(tone_preview=preview,tone_packets=packets,tone_seconds=time.perf_counter()-began)
            began=time.perf_counter()
            production=speech.transcribe_final(audio_bytes,interaction_id=identity,stream_id='utterance')
            row['final_seconds']=time.perf_counter()-began
            row.update(hypothesis=normalize_transcript(production['raw_text'],'','ru'),
                       raw_hypothesis=production['raw_text'],speaker=production.get('speaker',{}),
                       provider=production.get('provider','T-one + GigaAM v3 RNNT'))
            # Same audio and ASR, speaker filter disabled only in this diagnostic call.
            # This is not the score of the live production mode.
            began=time.perf_counter()
            control=speech.transcribe_final(audio_bytes,interaction_id='')
            row.update(control_hypothesis=control['raw_text'],control_seconds=time.perf_counter()-began)
        except Exception as error:
            row.update(hypothesis='',raw_hypothesis='',control_hypothesis='',error=f'{type(error).__name__}: {error}')
        finally:
            dual_asr.close_stream(identity,'utterance');dual_asr._speakers.pop(identity,None)
        row['spoken']=align(entry['text'],row['hypothesis'])
        row['written']=align(entry['e2e_text'],row['hypothesis'])
        row['control_spoken']=align(entry['text'],row['control_hypothesis'])
        row['tone_spoken']=align(entry['text'],row.get('tone_preview',''))
        ref,hyp=normalized(entry['text']),normalized(row['hypothesis'])
        row.update(reference_chars=len(ref),char_errors=distance(ref,hyp))
        rows.append(row)
        (OUT/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'done':index,'id':entry['id'],'wer':round(row['spoken']['wer']*100,2),
            'control_wer':round(row['control_spoken']['wer']*100,2),'speaker':row.get('speaker',{}).get('status'),'error':row.get('error')},ensure_ascii=True),flush=True)
    metrics={}
    for name in ('spoken','written','control_spoken','tone_spoken'):
        words=sum(r[name]['reference_words'] for r in rows);errors=sum(r[name]['word_errors'] for r in rows)
        metrics[name]={'wer':errors/words,'word_errors':errors,'reference_words':words,
            'exact_recordings':sum(r[name]['exact'] for r in rows),
            'counts':{k:sum(r[name]['counts'][k] for r in rows) for k in ('substitute','delete','insert')}}
    chars=sum(r['reference_chars'] for r in rows)
    summary={'created_at':datetime.now(timezone.utc).isoformat(),'source':SOURCE,'revision':REVISION,
        'subset':SUBSET,'selection':'First 20 metadata.jsonl rows, original order','count':len(rows),
        'audio_seconds':sum(r['actual_duration'] for r in rows),'metrics':metrics,
        'cer':sum(r['char_errors'] for r in rows)/chars,
        'repeat_requests':sum(bool(r.get('speaker',{}).get('requires_repeat')) for r in rows),
        'technical_errors':sum('error' in r for r in rows),
        'mean_final_seconds':statistics.mean(r.get('final_seconds',0) for r in rows),
        'readiness':speech.readiness(),'engine_source_hashes':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['services/dual_asr.py','services/local_speech.py','providers/language.py']},
        'metadata_sha256':hashlib.sha256(metadata.read_bytes()).hexdigest(),
        'normalization':'Lowercase, ё→е, punctuation removed, hyphen→space, spaces collapsed, exact fillers ээ/аа/мм removed. No number/brand substitutions. CER includes spaces.',
        'limitations':'20 consecutive noisy records, not a representative/random sample. Independent new voice session for each recording. Complete files, not browser endpoint capture. Control bypasses only speaker filter. T-one score is unfinished preview and is not final product output.',
        'rows':rows}
    (OUT/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    render(summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in {'rows','engine_source_hashes'}},ensure_ascii=True),flush=True)


def render(summary):
    esc=html.escape
    def pct(x):return f'{100*x:.2f}%'
    cards=[]
    for row in summary['rows']:
        status='Совпало' if row['spoken']['exact'] else ('Нужен повтор' if row.get('speaker',{}).get('requires_repeat') else 'Есть расхождения')
        if 'error' in row:reason='Техническая ошибка: '+row['error']
        elif row.get('speaker',{}).get('requires_repeat'):
            reason='Фильтр голоса отклонил запись: '+row['speaker'].get('message','Потребовалось повторение.')+' Для WER пустой ответ считается пропуском всех слов. Ниже есть результат той же записи без фильтра.'
        elif row['spoken']['exact']:reason='Все слова совпадают после описанной нормализации.'
        else:
            reason=f'Замены: {row["spoken"]["counts"]["substitute"]}; пропуски: {row["spoken"]["counts"]["delete"]}; лишние слова: {row["spoken"]["counts"]["insert"]}. '
            if row['number']==2:reason+='Различие написания бренда: «Эко-Пылесос» → «экопылесос». Замена дефиса пробелом в протоколе создаёт два ошибочных токена, хотя смысл названия сохраняется.'
            elif row['number']==5:reason+='Различие написания бренда: «Дом-ру» → «домру». В контрольном вызове без фильтра получилось «дом ру», что совпало после нормализации.'
            elif row['number']==6:reason+='Перед основной репликой добавлены «по размеру ледовых площадок». Этих слов нет в эталоне; они также присутствуют в результате без фильтра. Возможная фоновая речь — это предположение, которое нужно проверить прослушиванием.'
            elif row['number']==11:reason+='Изменён падеж: «Почты России» → «почта россии». Такая же замена в контрольном распознавании.'
            elif row['number']==13:reason+='Пропущено слово «автоинфо». Без фильтра также пропущено это слово и дополнительно изменено «Путешествий» → «путешествие».'
            elif row['number']==16:reason+='Бренд «Декатлон» распознан как «дикатлон». Такая же замена в контрольном распознавании.'
            elif row['number']==18:reason+='Бренд «Купер» распознан как «копер». Такая же замена в контрольном распознавании.'
            else:reason+='Это расхождения с разметкой; без прослушивания каждое расхождение нельзя автоматически считать ошибкой модели.'
        marked=[]
        for op in row['spoken']['operations']:
            if op['type']=='equal':marked.append(esc(op['reference']))
            elif op['type']=='substitute':marked.append(f'<span class="replacement"><del>{esc(op["reference"])}</del> → <ins>{esc(op["hypothesis"])}</ins></span>')
            elif op['type']=='delete':marked.append(f'<del>{esc(op["reference"])}</del>')
            else:marked.append(f'<ins>{esc(op["hypothesis"])}</ins>')
        source=f'{SOURCE}/blob/{REVISION}/{SUBSET}/{row["file_name"]}'
        cards.append(f'<article data-error="{str(not row["spoken"]["exact"]).lower()}" id="case-{row["number"]}"><div class="row"><h2>#{row["number"]} · {esc(status)}</h2><b>WER {pct(row["spoken"]["wer"])}</b></div><p class="muted">{esc(row["id"])} · {row["actual_duration"]:.2f} с · {esc(str(row.get("speaker",{}).get("status","—")))}</p><p class="reason">{esc(reason)}</p><h3>Эталон сайта · text</h3><p>{esc(row["text"])}</p><h3>Наш окончательный результат</h3><p>{esc(row["hypothesis"] or "Пустой ответ — текст не передан агенту")}</p><h3>Различия по словам</h3><p class="diff">{" ".join(marked)}</p><details><summary>Письменный эталон, результат без фильтра и T-one</summary><h3>e2e_text · WER {pct(row["written"]["wer"])}</h3><p>{esc(row["e2e_text"])}</p><h3>GigaAM без фильтра голоса · WER {pct(row["control_spoken"]["wer"])}</h3><p>{esc(row["control_hypothesis"] or "Пустой ответ")}</p><h3>Предварительный T-one</h3><p>{esc(row.get("tone_preview", ""))}</p><pre>{esc(json.dumps(row.get("speaker",{}),ensure_ascii=False,indent=2))}</pre></details><a href="{source}" target="_blank" rel="noopener">Открыть исходную запись на Hugging Face ↗</a></article>')
    m=summary['metrics'];stats=m['spoken'];counts=stats['counts']
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Фокус · RESON · первые 20</title><style>body{margin:0;background:#f3f5fa;color:#192339;font:16px/1.65 system-ui}.wrap{max-width:1060px;margin:40px auto;padding:0 22px}h1{font-size:36px;line-height:1.2}h2{font-size:20px;margin:0}h3{font-size:14px;color:#66758a;margin-bottom:0}article,section{background:white;border:1px solid #dce3ef;border-radius:18px;padding:24px;margin:20px 0}.row{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.stat{padding:16px;background:#edf2ff;border-radius:14px}.stat strong{display:block;font-size:26px}.muted{font-size:14px;color:#67768b;overflow-wrap:anywhere}.reason{border-left:3px solid #6b7ea5;padding:12px;background:#f7f8fb}del{color:#a52129;background:#ffe8e9;text-decoration:line-through;padding:1px 3px;border-radius:3px}ins{color:#126846;background:#def5e9;text-decoration:none;padding:1px 3px;border-radius:3px}.diff{line-height:2}pre{white-space:pre-wrap;background:#f6f8fc;padding:16px;border-radius:10px}a{color:#244fad}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #e1e7f1;text-align:left}details{margin-bottom:16px}label{cursor:pointer}small{color:#64748b}</style><div class="wrap">'''
    page+=f'<p class="muted">ФОКУС · ЛОКАЛЬНЫЙ ASR · СРАВНЕНИЕ С ЭТАЛОНОМ</p><h1>Первые 20 записей MWS RESON</h1><p>Раздел <b>{SUBSET}</b>, исходный порядок metadata.jsonl. {summary["audio_seconds"]/60:.2f} минуты шумной телефонной речи. Модели не обучались на этих записях; эталоны не передавались распознаванию.</p>'
    page+=f'<div class="grid"><div class="stat"><small>WER нашего движка · text</small><strong>{pct(stats["wer"])}</strong></div><div class="stat"><small>Точные совпадения слов</small><strong>{stats["exact_recordings"]}/20</strong></div><div class="stat"><small>Просьбы повторить</small><strong>{summary["repeat_requests"]}/20</strong></div><div class="stat"><small>GigaAM без фильтра</small><strong>{pct(m["control_spoken"]["wer"])}</strong></div></div>'
    refused=[r for r in summary['rows'] if r.get('speaker',{}).get('requires_repeat')]
    omitted=sum(r['spoken']['reference_words'] for r in refused)
    page+=f'<section><h2>Главное наблюдение</h2><p>Фильтр основного голоса полностью отклонил записи <b>{", ".join("№"+str(r["number"]) for r in refused)}</b>. Это дало {omitted} пропуска слов из {stats["word_errors"]} всех расхождений. В обеих записях контрольная GigaAM без фильтра совпала с произнесённым эталоном.</p><p>Правило «несколько голосов в первой реплике → попросить повторить» слишком строго для этих шумных файлов. Следующий кандидат на доработку — поведение фильтра до появления чистого образца основного голоса. Движок во время этого сравнения не менялся.</p><p>Другие расхождения: написание составных брендов, «Декатлон/дикатлон», «Купер/копер», «Почты/почта», пропуск «автоинфо» и четыре добавленных слова в №6. Ниже каждый случай показан полностью.</p></section>'
    page+=f'<section><h2>Что именно посчитано</h2><p>WER — (замены + пропуски + вставки) / число слов эталона, суммарно по всем 20 записям. Получено <b>{stats["word_errors"]} ошибок на {stats["reference_words"]} слов</b>: замен {counts["substitute"]}, пропусков {counts["delete"]}, вставок {counts["insert"]}. CER: {pct(summary["cer"])}.</p><table><tr><th>Режим</th><th>WER</th></tr><tr><td>Рабочий движок с фильтром, эталон text</td><td>{pct(stats["wer"])}</td></tr><tr><td>Тот же результат против e2e_text</td><td>{pct(m["written"]["wer"])}</td></tr><tr><td>GigaAM с VAD, фильтр говорящего отключён только для диагностики</td><td>{pct(m["control_spoken"]["wer"])}</td></tr><tr><td>Предварительный, незавершённый текст T-one</td><td>{pct(m["tone_spoken"]["wer"])}</td></tr></table><p>Регистр, пунктуация, ё/е, пробелы и отдельные «ээ», «аа», «мм» нормализованы одинаково. Числа и названия не переписывались. Слова вместо цифр считаются ошибками против e2e_text — это различие формата, которое не обязательно означает, что речь не расслышана.</p><p>Каждый файл — новый разговор без заранее записанного образца голоса. Отказ фильтра учитывается как пустая транскрипция, а не исключается из оценки. Полные записи подаются без обрезания браузером. Исходные 8 кГц переводятся в 16 кГц для GigaAM/VAD и в 8 кГц для T-one.</p><p><b>Ограничение:</b> это 20 последовательных шумных записей, а не результат по всем 12 114 записям и не случайная выборка. Технических ошибок: {summary["technical_errors"]}. Средняя длительность финального распознавания: {summary["mean_final_seconds"]:.2f} с, без загрузки моделей и сетевых запросов.</p><p class="muted">Датасет MTSAIR, MIT, © 2026 MTS AI. Ревизия: {REVISION}. <a href="{SOURCE}" target="_blank" rel="noopener">Карточка датасета</a>.</p></section>'
    page+='<p><label><input type="checkbox" id="errors"> Показывать только расхождения</label> · <del>удалённое слово</del> <ins>добавленное слово</ins></p>'
    page+=''.join(cards)+'''</div><script>document.querySelector('#errors').onchange=e=>document.querySelectorAll('article').forEach(a=>a.hidden=e.target.checked&&a.dataset.error==='false');</script></html>'''
    PAGE.parent.mkdir(exist_ok=True);PAGE.write_text(page,encoding='utf-8')


if __name__=='__main__':
    if '--render-only' in sys.argv:render(json.loads((OUT/'results.json').read_text(encoding='utf-8')))
    else:benchmark()
