# Продолжение полного задания — рабочая запись

Пользователь прямо поручил доделать **весь** остаток ТЗ, затем повторил «продолжай
с того, на чём остановился». Не заканчивать работу только планом/оценкой процента.
Работа одним агентом (V2_SPEC отменяет старое распределение файлов).

Рабочий checkout: /workspace/scratch/fc4569615d04/track3-v2.
Последний опубликованный HEAD: e5a17b8, PR12 draft. CI43187145155 завершился
SUCCESS целиком, включая Windows и браузер. Main и start-gateway не трогать.
Git CLI fetch работает, push без credentials не работает: публиковать через
GitHub create_tree/create_commit/update_ref с expected_sha, без force. Аккаунт
link_6af46af9328c8191b6c424fd52d939b1, репозиторий yougmilee2642-a11y/iug6767hhh.
Не выдавать локальные SHA за опубликованные; сравнивать деревья до update_ref.

## Новые изменения в рабочей папке, ещё не опубликованы

- Миграция14: assistant conversations/messages/evidence/task_origins.
- E10: 7 базовых read-tools + брифинг/календарь, JSON selector за флагом,
  серверные кандидаты, checked claims, повторная проверка источников/истории,
  личные диалоги, feedback, UI. Actions preview/confirm: ручное поручение,
  новая встреча без приглашений, смена статуса существующей задачи. Ручное
  поручение не вставляет вымышленную реплику в запись, provenance task_origins.
- E5: голосовые action_draft без записи; чтение заказов/обращений/своих задач/
  календаря через те же scoped tools, speaker privacy. Реальных моделей нет.
- Миграция15: retention policy, delete requests, notifications/settings/outbox,
  comments/history, rate buckets и заготовка series.
- E11: Origin+X-Focus-Request для браузерных мутаций, SameSite cookie сохранён,
  persisted rate limits, security headers/CSP без внешних источников. Jost
  скачан из google/fonts, локальный TTF и полный OFL в static/fonts/jost;
  SHA256 TTF6343b70971000b04c5d401c96ae08ce371086135e999d5e1e1413039c0213076.
  Есть retention job/сроки/удаление по запросу через admin preview/confirm,
  marked-test-only cleanup с отменой и повтором; периодический worker60s.
- E12: внутренний центр, назначение/срок завтра/просрочка/эскалация/встреча15мин/
  брифинг; generic внешние payload только opt-in в outbox, реальных отправок нет.
- E8: комментарии/история; DnD = preview/confirm, клавиатурный edit сохранён.
- Миграция16: protocol_mail_outbox. Экспорт подтверждённых пунктов MD/HTML
  (разрешённый ТЗ fallback без python-docx), рассылка preview/confirm,
  ACL получателя повторно проверяется, EML download/local physical EML worker.
- E3: Bitrix24Connector REST v1, HTTPS/no proxies/no redirects, redact webhook,
  tag/hash before create, uncertain/no retry, normalized employee/department,
  task/status/comment/deal; factory gated MEETINGS_BITRIX_ENABLED=0 default.
  Mary/1C/HR mock, Amo/Zoho explicit stubs. Employee mapping preview/confirm,
  роли не синхронизируются автоматически. Транспорт тестируется MockTransport.

## Проверки

Venv: /workspace/scratch/80c6e160b1f6/track3-clean-venv/bin/python.
Последний полный прогон **до последних E3/E5/E8 изменений**:
1490 passed,28 skipped,0 failed,210.10s; Node66 passed.
Raw /workspace/scratch/fc4569615d04/all-progress-python.log, all-progress-node.log.
После добавления E3/E5/E8 целевые69 passed, затем добавлены ещё проверки sync/
uncertain/status-change, идёт повтор. Самый свежий лог phase-target3.log,
завершён:86 passed; после E4 новый full phase2-python.log. Предыдущие phase-target2 ошибки SyntaxError в sync.py
исправлены apply_patch; compileall прошёл. Не заявлять полный прогон последнего
кода до фактического повтора.

## Остаток — выполнить, а не просто описать

1. Довести текущие целевые тесты/HTTP/UI-smoke, документацию/OpenAPI/лицензии,
   сохранить текущий большой блок отдельными коммитами и в PR12.
2. E3: проверить остальные методы contact/activity/mapping scope и имена/поля
   по официальной документации; хорошие docs источники уже найдены на apidocs.
3. E4: Mock/Bitrix + scoped mapping/recheck и durable uncertain outbox реализованы.
   Google, серии/напоминания P2 после P1. Tests test_track3_calendar_providers.py.
4. E7: media_jobs/assets/segments, consent, decoder/ASR/diarization adapters,
   реальная запись файла без моделей при недоступности, плеер/timecodes,
   speaker mapping, аналитика, calls support/sales с 17 темами/checklist,
   scopes/quote proof, dashboard, agenda hook, frozen call control/live script.
5. E9.2: source-validated drilldown→preview action→meeting/task; E8.6 KPI/
   просроченные решения/проблемы звонков в следующей повестке.
6. E6: опциональный выбор salient quotes моделью с цитатной проверкой (сейчас
   «Кратко» честно extractive), затем P2 конфликты/обязательства.
7. P2 после зелёных P0/P1: серии, дайджест, сезонный радар (проверяемая формула),
   commitments/качество/ПВЗ/action-effect loop/переговорная/слова-числа/mobile.
8. E13: call evaluation и полная traceability всех требований, scripts/live
   для хоста. Не запускать Ollama/ASR/TTS/diarization агентом.
9. Финальный self-audit, clean install, секреты/лицензии, CI и merge только при
   критериях ТЗ. «Требует живой проверки» не превращать в PASS.

## Известные нюансы текущего кода для review

- IntegrationError наследует ValueError: в Bitrix.call добавлено отдельное
  except IntegrationError: raise перед generic ValueError, иначе config терялся.
- Синхронизация исключает admin/auditor; текущее исправление Sync SQL кавычек
  уже применено. Последний test_employee_mapping выбирает первый допустимый ID.
- Старый voice_never_writes обновлён под action_proposed только для поддержанных
  «Поставь/Пригласи», counts задач/подтверждений/приглашений и no-model сохранены.
- HR таблица work_shifts (user_id), не hr_shifts; финансы finance_aggregates.
- Retention очистка должна сохранять audit, не удалять произвольные файлы.
- manual_request provenance сохранена при retention старой стенограммы.
- TODO review: новый calendar voice route использует scheduled_at и explicit
  calendar participant/owner; реальные внешние календари ещё не подцеплены.
- TODO review: дополнительные файлы source_ref остаются у оригинала (уже
  исправлено в опубликованном e5a17b8); не копировать UNIQUE ref в новую версию.

## Проверенный checkpoint перед E7

Сведён удалённый c7b6763 с E6 lifecycle. Merge b0cdd1f:1547/28/0,
224.42s; Node66; обе HTTP ветки passed. Reports v2-assistant-operations-*.
Снимок публикации не включает незарегистрированные meetings/media и migration
media.py — это следующий рабочий блок. Новый GitHub SHA сверить после update_ref.
