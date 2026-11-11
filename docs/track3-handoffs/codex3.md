# Codex 3 — выпуск и интеграция

База cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3. Отдельная clone и integration worktree.
Ветки codex/track3-release и codex/track3-integration **опубликованы**.
[Draft PR #4](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/4) направлен в main;
main не менялся. Подключение владельца yougmilee2642-a11y разрешает push. Публикация
проведена через GitHub API; все trees сверены с локальными. Первоначальные SHA
наблюдений сопоставляются с опубликованными через reports/publication-map.json.

## Выполнено

- Первый commit 9a51a28 содержит пакет заданий, SHA/ветки/команды/gates.
  docs/track3-team/README.md и CONTRACT отсутствовали в исходном remote; CONTRACT
  восстановлен со статусом «на согласование», не выдан за ранее утверждённый.
- Gold/corpus frozen commit 9d1c2dc: 24 TXT разных деловых типов, 3 transcript,
  18 задач и 16 QA-кейсов. Никаких результатов модели при создании gold не использовали.
- MeetingLLM использует providers.ollama.endpoint(), Bearer, no redirects/proxy,
  cloud rejection, прежние schema/think/context/predict/timeout. Защита тестируется.
- Отдельный seed с ACL/задачами/aware датами/календарём/KPI по handoff авторов.
  Других схем не создаёт, требует core migration v8. Орбита и её seed сохранены.
- Safe cleanup/start/check/HTTP-smoke и lock зависимостей; app.py и voice не патчились.
  Старый --reset seed не удаляет рабочую data/ без явного test path/confirm.
- Оценщик настоящей модели и независимый manual scorer; один gold ↔ один prediction,
  точные цитаты, conservative matching, owner/due ошибки, latency и raw report.
- Выполнено merge core → knowledge → UI → release, затем обычные merge обновлений
  владельцев. Зависимые импорты добавлены Claude. Авторские SHA и API в STATUS.
- Реальный HTTP start→2 роли→ACL/audit→ручной протокол/confirm→task/calendar
  cancel-confirm→KPI→QA-отказ→restart пройден без модельного двойника и voice weights.
- CI CPU без секретов, API/architecture/retention/licenses/runbook/demo/10-slide outline.

## Фактические результаты

Актуальные логи и passed/failed/not-run: [STATUS](../track3-release/STATUS.md).
Ни старые live-результаты Орбиты, ни тестовые fixtures не засчитываются новым recall.
Настоящая модель здесь недоступна: ConnectError /api/version. Chromium заблокирован
системным socket permission до сценариев. Независимый повтор установки не выполнен.
Релиз **НЕ ГОТОВ**.

## Конкретные оставшиеся действия владельцев

1. Публикация закрыта: обе ветки и draft PR #4 существуют. Release уже включён
   в integration, поэтому отдельный PR release → integration имел бы пустое сравнение.
   Не сливать main до остальных gates; текущий integration SHA виден в PR.
2. Команда: согласовать восстановленный CONTRACT. Формат seed уже соответствует
   опубликованным handoff Claude/Codex 2; интеграционные тесты схемы проходят.
3. Другой участник: пройти RUNBOOK от нового venv, записать OS/Python, cache/network,
   время до /meetings, 2 роли, restart. Текущий install.json — тот же участник,
   тёплый cache, не независимое измерение.
4. Владелец GPU: предоставить разрешённый endpoint и ключ **через env**, не git/PR;
   согласовать одно окно без тяжёлых параллельных запросов. Предзагрузить точную модель.
   Выполнить `python scripts/live_meetings_check.py --track3 --exclusive-gpu-window
   --output <absolute report.json>`, передать raw report независимому проверяющему.
5. Codex 1 / CI runner: выполнить точную браузерную команду из handoff и workflow на
   итоговой integration. Ошибка текущей среды не является найденной ошибкой UI.
6. Владелец продукта: решить PyMuPDF AGPL/commercial и проверить точные voice-asset
   notices перед поставкой голоса. Не приписывать весам лицензию кода по аналогии.

Замечаний к чужой продуктовой логике по выполненным проверкам не осталось. Исторический
PDF fallback baseline даёт один fragment вместо ≥3; воспроизведение:
минимальное окружение без PyMuPDF → pytest test_meetings.py::test_upload_formats_and_bad_files.
Сейчас воспроизводимость закрыта явной существующей PyMuPDF-зависимостью. Замена
самого PDF parser должна идти через Claude; Codex 3 её не делал.
