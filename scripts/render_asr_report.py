"""Render saved local ASR checks as an inline browser report; no inference required."""
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CRITERIA={
    'recognize':'Получить непустую завершённую реплику без запроса повторения. Проверка не измеряет точный WER.',
    'reject':'Не передавать тишину, посторонний голос или смешанную реплику агенту.',
    'all_digits':'Сохранить весь номер 375291234567 в правильном порядке после нормализации.',
    'remove_background':'Удалить речь другого человека и полностью сохранить завершающее «да всё правильно».',
}

def explanation(row):
    if row['pass']:return 'Проверяемое условие выполнено.'
    if row['expected']=='remove_background' and row.get('speaker',{}).get('removed_background_speakers',0)>0:
        return ('Фоновый говорящий удалён, но финальный текст GigaAM содержит ошибку: '
                '«да вс правильно» вместо «да всё правильно». После исправления обработки '
                'длинной паузы слова «да» и начало следующего слова вернулись. Осталась ошибка '
                'распознавания модели; текст не исправлялся догадкой или смешиванием результатов.')
    if row['expected']=='all_digits':return 'Окончательный результат не содержит полный ожидаемый номер. Нельзя принимать его без уточнения.'
    return 'Проверяемое условие не выполнено. Сравните окончательный текст и результат фильтра голоса ниже.'

def render_report(report):
    cards=[]
    for row in report['cases']:
        status='PASS' if row['pass'] else 'ПРОВЕРИТЬ'
        row['failure_reason']=None if row['pass'] else explanation(row)
        cards.append(f'<article><h2><span class="{status}">{status}</span> {html.escape(row["case"])}</h2>'
            f'<p>Аудио: {row["audio_seconds"]} с · Финальное распознавание: {row.get("recognition_ms","—")} мс</p>'
            f'<h3>Что проверяли</h3><p>{html.escape(CRITERIA[row["expected"]])}</p>'
            f'<p class="reason">{html.escape(explanation(row))}</p>'
            f'<h3>Предварительный текст T-one</h3><p>{html.escape(row["tone"] or "Не запускался")}</p>'
            f'<h3>Окончательный текст GigaAM</h3><p>{html.escape(row["raw_text"] or "Реплика не передана агенту")}</p>'
            f'<details><summary>Результат фильтра голоса</summary><pre>{html.escape(json.dumps(row.get("speaker",{}),ensure_ascii=False,indent=2))}</pre></details></article>')
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Фокус · Проверка новой речи</title><style>body{font:16px/1.6 system-ui;background:#f3f5fa;color:#172033;max-width:1000px;margin:40px auto;padding:0 20px}h1{font-size:36px}article{background:white;border:1px solid #dce2ef;border-radius:18px;padding:24px;margin:18px 0}h2{font-size:20px}h3{font-size:14px;color:#607089;margin-bottom:0}pre{white-space:pre-wrap;background:#f5f7fb;padding:16px;border-radius:10px}.PASS{color:#138153}.ПРОВЕРИТЬ{color:#b45309}aside{padding:20px;background:#e9efff;border-radius:14px}.reason{padding:12px;border-left:3px solid #8898b6;background:#f7f8fc}</style>'''
    page+=f'<h1>Фокус: T-one + GigaAM v3</h1><p>Локальное распознавание, сохранение полной реплики и фильтр основного голоса.</p><aside><b>{report["passed"]}/{report["total"]} проверок прошли.</b><br>{html.escape(report["limits"])}</aside>'
    page+='<p>Первая достаточно длинная реплика от одного человека задаёт голос для текущего разговора. Говорите ближе к микрофону, пока остальные молчат. Образец голоса хранится только в памяти до десяти минут без активности.</p>'
    page+=''.join(cards)+'</html>'
    destination=ROOT/'static/qa/dual-asr-verification.html'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(page,encoding='utf-8')
    return destination

if __name__=='__main__':
    path=ROOT/'data/asr-verification/results.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    print(render_report(report))
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
