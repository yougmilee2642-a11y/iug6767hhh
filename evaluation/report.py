"""Readable explanations derived from saved assertions and conversation evidence."""
from collections import Counter
from html import escape

CHECKS = {
    'role_identity': 'Агент не назвал роль, указанную в настройках.',
    'expected_state': 'Разговор завершился в статусе, отличном от ожидаемого.',
    'user_provenance': 'Для собранных данных не подтверждён источник в репликах клиента.',
    'no_unconfirmed_write': 'Действие выполнено без проверяемого согласия на конкретное предложение.',
    'allowed_tools': 'Использован инструмент, не разрешённый настройками.',
    'immediate_handoff': 'Явный запрос человека не обработан сразу по правилам агента.',
    'callback_saved': 'Подтверждённое обращение не сохранено с ожидаемыми данными.',
    'callback_not_saved': 'Обращение сохранено, хотя клиент отказался или не сообщил обязательные данные.',
    'no_booking': 'В тесте, где запись запрещена, обнаружена созданная запись.',
    'no_contact_collection': 'Агент собирал контакты для справочного вопроса.',
    'booking_completed': 'Запись на выбранную услугу и время не завершена.',
    'knowledge_grounded': 'Ответ по известным сведениям не подтверждён результатами проверки.',
    'price_grounded': 'Названная цена не совпадает с подтверждённым каталогом.',
    'unknown_grounded': 'Корректный ответ или отказ на неизвестный вопрос не подтверждён.',
    'rejected_probe': 'Не подтверждено отклонение специально подставленного неподтверждённого значения.',
    'slots_grounded': 'Предложенные слоты не соответствуют проверенному расписанию.',
    'proposal_changed': 'Изменение или отказ от старого предложения обработаны неверно.',
    'failure_handled': 'Повторные ошибки календаря обработаны неверно.',
}


def explain(scenario, result, config=None):
    if not result:
        return {'category': 'Ещё не проверено', 'reasons': ['Сценарий ещё не выполнен.'], 'actual': '', 'next_step': 'Дождаться завершения прогона.'}
    trace = result.get('trace', {})
    replies = [m['content'] for m in trace.get('transcript', []) if m['role'] == 'assistant']
    actual = replies[-1] if replies else 'Ответ агента отсутствует.'
    reasons = []
    failed = [a for a in result.get('assertions', []) if a.get('measured', True) and not a['passed']
              and not (result.get('quality_preview') and a['name'] == 'judge_grounding')]
    for item in failed:
        name = item['name']
        if name == 'judge_grounding':
            reasons.extend(result.get('judge', {}).get('reasons', []) or ['Оценщик не подтвердил соответствие ответа фактам.'])
        elif name.startswith('expected_tool:'):
            reasons.append('Не выполнено требуемое действие: ' + name.split(':', 1)[1] + '.')
        elif name.startswith('forbidden_tool:'):
            reasons.append('Выполнено запрещённое действие: ' + name.split(':', 1)[1] + '.')
        else:
            reasons.append(CHECKS.get(name, item.get('message') or 'Не пройдена проверка ' + name + '.'))
    loop = trace.get('stop_reason') == 'turn_limit_exceeded' or any('turn_limit_exceeded' in r for r in result.get('failure_reasons', []))
    if loop:
        reasons.append('Диалог зациклился и достиг предельного числа реплик; тест не дошёл до завершения.')
        if (scenario.get('template_id') == 'callback_refused'
                and any('не записывайте' in m.get('content', '').casefold() for m in trace.get('transcript', []) if m['role'] == 'user')):
            reasons.append('После отказа тестовый клиент снова отправлял телефон, а агент снова предлагал подтверждение. Отказ не был сохранён как запрет повторять действие.')
    if any(a['name'] == 'role_identity' for a in failed) and config:
        questions = [f['question'] for f in config.get('fields', []) if f['id'] == 'customer_name']
        if actual.strip() in questions:
            reasons.append('Вместо представления агент повторил вопрос об имени. Информационный вопрос не был отделён от ответа на сбор данных.')
    if any(a['name'] == 'expected_state' for a in failed):
        reasons.append(f"Ожидался статус «{scenario.get('expected_state')}», получен «{trace.get('final_state', {}).get('status', 'не сохранён')}».")
        if scenario.get('template_id') == 'callback_refused' and trace.get('final_state', {}).get('status') == 'escalated':
            reasons.append('После отказа симулятор предложил время и сотрудника для сценария без календаря; агент ошибочно передал запрос сотруднику.')
    category = 'Поведение агента / логика диалога'
    next_step = 'Проверить приведённый диалог и обработку запроса; добавление фактов само по себе не исправляет эту ошибку.'
    if result.get('error'):
        error = result['error']
        reasons.append('Проверка не завершена: ' + str(error.get('category') or error.get('type') or 'ошибка сервиса') + '.')
        if error.get('status_code') == 429:
            reasons.append('Сервис ограничил число запросов (429). Это не доказывает ошибку ответа агента.')
        category = 'Инфраструктура проверки'
        next_step = 'Устранить ошибку сервиса и повторить тест.'
    elif config and not config.get('business', {}).get('knowledge', {}).get('notes') and not config.get('business', {}).get('knowledge', {}).get('qa') and any(a['name'] == 'knowledge_grounded' for a in failed):
        category = 'Не хватает знаний в настройках'
        next_step = 'Добавить подтверждённый ответ или факты компании и повторить тест.'
    elif result['status'] == 'PASS':
        category = 'Пройдено'
        reasons = ['Измеренные условия этого сценария выполнены.']
        next_step = 'Исправление по этому результату не требуется.'
    if result.get('quality_review_notes'):
        next_step += ' Есть отдельные замечания предварительного оценщика текста: они не равны провалу проверок кодом.'
    if not reasons:
        reasons = result.get('failure_reasons') or ['Причина не сохранена. Нужен повторный прогон с трассировкой.']
    return {'category': category, 'reasons': reasons, 'actual': actual, 'next_step': next_step}


def report_html(run, previous=None):
    e = lambda value: escape(str(value), quote=True)
    scenarios = run.get('scenarios', [])
    counts = Counter(s.get('result', {}).get('status', 'Ожидает') if s.get('result') else 'Ожидает' for s in scenarios)
    parts = [f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Отчёт проверки Фокус</title><style>body{{font:16px/1.6 system-ui,sans-serif;color:#18202b;background:#f5f6f8;margin:0}}main{{max-width:1000px;margin:auto;padding:32px 20px}}a{{color:#a71935}}section,details{{background:white;padding:20px;margin:16px 0;border-radius:12px;border:1px solid #dce0e6}}summary{{cursor:pointer;font-weight:650}}.FAIL{{border-left:5px solid #bd2445}}.ERROR{{border-left:5px solid #af7400}}.PASS{{border-left:5px solid #32845e}}.note{{background:#fff6db;padding:14px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 system-ui}}p{{overflow-wrap:anywhere}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #ddd}}table{{width:100%;border-collapse:collapse}}small{{color:#626b79}}</style><main>
<h1>Отчёт проверки агента</h1><p>Прогон: {e(run['id'])} · Агент: {e(run.get('config_snapshot', {}).get('name', run.get('agent_id', '')))}</p>
<p>Всего сценариев: {len(scenarios)}. Пройдено: {counts['PASS']}. Провалено: {counts['FAIL']}. Ошибки проверки: {counts['ERROR']}.</p>''']
    if run.get('outdated'):
        parts.append('<p class="note">Настройки агента изменились. Этот отчёт относится к сохранённой версии прогона.</p>')
    if run.get('provider_info', {}).get('quality_independent') is False:
        parts.append('<p class="note">Оценку текста давала та же модель, что отвечала клиенту. Она предварительная. PASS означает выполнение измеренных условий; отдельные замечания модели требуют ручной проверки.</p>')
    if previous:
        prior = {s['id']: s for s in previous.get('scenarios', [])}
        parts.append('<section><h2>Что изменилось после исправления</h2><p>Исходный прогон: ' + e(previous['id']) + '. Ниже сравнение всех тестов. Причины исходных провалов сохранены.</p><table><tr><th>№</th><th>Тест</th><th>Было</th><th>Стало</th><th>Почему был провал</th></tr>')
        for index, scenario in enumerate(scenarios, 1):
            old = prior.get(scenario['id'])
            old_result = old.get('result') if old else None
            old_status = old_result['status'] if old_result else 'Не проверялось'
            current = scenario.get('result')
            reason = '; '.join(explain(old, old_result, previous.get('config_snapshot'))['reasons']) if old_result and old_status != 'PASS' else 'Измеренные условия были выполнены.' if old_result else 'Нет результата для сравнения.'
            parts.append(f'<tr><td>{index}</td><td><a href="#case-{index}">{e(scenario["title"])}</a></td><td>{e(old_status)}</td><td>{e(current["status"] if current else "Ожидает")}</td><td>{e(reason)}</td></tr>')
        parts.append('</table></section>')
    parts.append('<section><h2>Все тесты</h2><table><tr><th>№</th><th>Сценарий</th><th>Результат</th></tr>')
    for index, scenario in enumerate(scenarios, 1):
        result = scenario.get('result')
        parts.append(f'<tr><td>{index}</td><td><a href="#case-{index}">{e(scenario["title"])}</a></td><td>{e(result["status"] if result else "Ожидает")}</td></tr>')
    parts.append('</table></section>')
    for index, scenario in enumerate(scenarios, 1):
        result = scenario.get('result')
        explanation = explain(scenario, result, run.get('config_snapshot'))
        status = result['status'] if result else 'Ожидает'
        parts.append(f'<details id="case-{index}" class="{e(status)}" open><summary>{index}. {e(scenario["title"])} — {e(status)}</summary><small>{e(scenario["id"])}</small><p><b>Ожидалось:</b> {e(scenario["expected_behavior"])}</p><p><b>Причина / итог:</b> {e(explanation["category"])}</p><ul>' + ''.join(f'<li>{e(r)}</li>' for r in explanation['reasons']) + f'</ul><p><b>Фактический ответ:</b> {e(explanation["actual"])}</p><p><b>Что делать:</b> {e(explanation["next_step"])}</p>')
        if result and result.get('quality_review_notes'):
            parts.append('<details><summary>Предварительные замечания оценщика текста</summary><ul>' + ''.join(f'<li>{e(r)}</li>' for r in result['quality_review_notes']) + '</ul></details>')
        if result:
            parts.append('<details><summary>Диалог и проверенные условия</summary>')
            for message in result.get('trace', {}).get('transcript', []):
                parts.append(f'<p><b>{"Клиент" if message["role"] == "user" else "AI"}:</b> {e(message["content"])}</p>')
            parts.append('<ul>' + ''.join(f'<li>{e(a["name"])}: {"не измерено" if not a.get("measured", True) else "пройдено" if a["passed"] else "не пройдено"}</li>' for a in result.get('assertions', [])) + '</ul></details>')
        parts.append('</details>')
    parts.append('</main></html>')
    return ''.join(parts)
