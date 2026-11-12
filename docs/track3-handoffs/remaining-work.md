# Продолжить весь V2_SPEC

Лёша поручил доделать весь остаток. Один исполнитель; модели/реальные аккаунты
не запускать, дизайн main сохранить. ТЗ docs/track3-team/V2_SPEC.md.
Checkout /workspace/scratch/fc4569615d04/track3-v2; branch
track3/v2-fotoprint-continued-local. Venv
/workspace/scratch/80c6e160b1f6/track3-clean-venv/bin/python.
Старый dirty checkout80c6e160b1f6/track3-v2 не трогать.

## Текущий срез

main17c3ff4 (дизайн/KPI/voicechat/maleTTS) включён merge031e1eb.
E7/E9 committed47bb388/944ec17, lifecycle543467b, reports50acf8b;
E5.2 spoken owner/dates/calendarhint + E7 modeltopics042c036.
Все подробности и точные ограничения в agent-v2.md, STATUS, SELF_AUDIT.
API111путей; media/jobs/calls/agenda/actionbasis, assistant/history/readtools,
operations/retention/notifications, Bitrix scope/map/transport/durable outbox,
ICS/shifts/BitrixCalendar, document FTS/versions/model-selector реализованы.
Voice parser без модели/записей, humanconfirm создаёт только проект встречи;
настройка слота отдельно. Topics optionalкод+ID+quote+ACLrecheck, secretdeny.

Полныйpytest1614passed/28skipped/0failed279.20s, Node66, HTTPdouble5.662s/
unavailable6.073s. Evaluatordouble30/30tasks,17/17claims,0rights/falseactions.
Cleaninstall042c036 runtime33.259/base38.675passed. Browser locally NOT RUN
(socket EPERM), сценарии должны пройти в новомPR CI. Первичные reports
v2-p1-fields-*. Live scripts только --help, inference не запускалась.

## Следующее

1. Публикация checkpoint/newdraftPR/CI. PR12 УЖЕ MERGED владельцем.
GitHub yougmilee2642-a11y/iug6767hhh, link_6af46af9328c8191b6c424fd52d939b1.
Remotebranch7a7d38398458fffb1fb071b3e404db179378e8ef; main17c3ff45686547762619642fcb916c25cbd56497.
CLI fetchworks, pushnocredentials. create_tree(base origin/main tree, diffHEAD),
create_commit(parentremote7a, additionalmain17c), update_ref expectedsha/forcefalse.
Compare exacttrees. Fontblobcdf8630280e37a7e8040dd5a32e3c13a9794e6d4.
Explicit publication authorization V2_SPEC§10 уже проверена и принята.
Scratch publish_entries.py создаёт manifest HEAD, publish_chunk.py chunks.
functions store OLDmanifest не переиспользовать; fresh regenerate.
2. P2: GoogleCalendar reusing integrations/providers/gates; meetingseries и
настраиваемые reminders; conflict/commitment extraction + humanconfirm;
weeklydigest preview/localoutbox;4–6week seasonalformula; qualityradar/PVZ
≤2days/actiondraft/effectchecks; roomlivehints/corridor30secbriefing/mobile.
Внешние opt-in Telegram/Bitrix transports doubles. Embeddings/ATCwatcher/OCR
опциональны поТЗ. Официальные API Google/Bitrix уже прочитаны через web.
3. Final sixbranchtraceability/E13calls/README/API/DEMO/PITCH/licenses/secrets/
cleaninstall/CI. Никаких живых аккаунтов/моделей. Не merge при обязательном
NOTRUN/незелёномP0; не выдавать весьТЗ за завершённый.

No .env/data/models/secrets/start-gateway ownchanges; no add./reset/clean/force/
rebase. Explicit gitaddpaths, set-e перед commit. Истинный Codexauthor, неClaude.

## Актуально после d0f4895/af29c96

Пользователь прямо разрешил с нового пункта вливать всё в MAIN с автотестами.
Не спрашивать повторно: прежний publicationblock разрешён новым указанием.
main5272c1c включён mergeaf29c96, voicebothkept. Calendars d0f4895
full1619/28skip, Node66, HTTP6.534, cleanruntime26.482passed.
Сейчас E6.4/evidence/voice secret guard ещё uncommitted, target37passed;
нужны full/HTTP/cleaninstall/commit и публикацияновогоPR→CI→mainmerge.
Не использовать planning-publish-manifest: там treeстарогоd0, аparentmain527
НЕ соответствуетbaseстарого17! Regeneratefreshmanifestотcurrentoriginmain.
functions p1_tree_result0a9909d естьнаGitHub; егоchildtreeнепубликоватьсновым
mainparentбезmerge. Existinglocal scripts publish_entries.py generatestree
fromHEADcorrectoriginmain. Upstreammain changesfrequently: fetch+mergeбезпотерь.
ОстатокпослеE6.4: weeklydigest/seasonal/qualityPVZ/effect/room/corridor;
externalnotificationtransports optionalgated, finaltraceability/docs.

## Актуальный checkpoint продолжения (важнее старых разделов)

Пользователь: «начиная со следующего пункта лей все в мейн но не забывай
проводить автотесты». Авторизация публикации/обычного merge в main есть,
старый auto-review block разрешён прямым новым указанием. Не спрашивать снова.

Три отдельных worktree одного repo, исполнитель один:
- track3-v2: основная поставка/исправления CI, branch track3/v2-fotoprint-continued-local.
  Сейчас local f47c9c7, tree7deea3dd5b2bfb5bbf643bce483c2efcda2a6698.
- track3-next: room/corridor, branch track3/v2-insights-next, f47c9c7;
  уже влита в основную локальную ветку.
- track3-radar: ТЕКУЩАЯ разработка, branch track3/v2-radar-next от241a70c,
  НEзакоммиченные advanced reports / migration21 / seed extension / UI.
Все пути под /workspace/scratch/fc4569615d04/. Venv прежний80c6e160b1f6.

GitHub PR13 OPEN DRAFT, base main5272c1c36be15fc8ae4c73580da9234aa3457ba6,
head branchtrack3/v2-fotoprint latest PUBLISHED27a03dcaa0a0fbf19b01ea43c3d29ab90acb4dc9.
Tree опубликованного27a точно совпадает f47c9c7. PR:
https://github.com/yougmilee2642-a11y/iug6767hhh/pull/13
Последний CI run43220251122 (номер37) именно27a. Мониторить JOBS, workflow
верхнеуровневый status отстаёт. Предыдущие35/36 отменились после новых push.
Не merge до зелёных current head/browser. Затем ready+merge --merge без squash.

main527 включён mergeaf29c96: сохранены новые voice_agenda,1.25x,automatic wake,
дизайн. В voice_agenda дополнительно закрыт secret, текущие версии scoped.
В private speech возвращён явный solo-room checkbox: автоматический wake
не разрешает speak_private=true (ТЗ E2). Публичная речь/новые voiceфункции сохранены.

Первый CI43213981781: все4 Linux/Windows install/release jobs passed, browser
failed35scenarios (2fail39errors). Root causes исправлены: iconarrow менял
accessible name кнопки (теперь aria-label), multipart wake WAV fixture ошибочно
читалкакJSON (теперьcontent-typeguard+scriptednotactivated),selectorscard→row
в тестах безудаленияstatus/date/TZassertions; docs min-width0/gridtrack shrink
для mobileoverflow. Артефакт13942998442 скачан в scratch track3-pr13-ci.zip.
Raw joblog stored functions pr13_browser_cancel_log. Локальный Chromium
socketEPERM; не заявлять localbrowserPASS. CurrentCI должен подтвердить fixes.

Полные результаты:
- E6.4/merge main snapshot230fdfe:1642passed/28skip286.51s; Node66;
  cleanruntime28.092/base29.534passed; HTTP5.726s passed.
- room/corridor241a70c:1646passed/28skip287.45s; target90passed34.27s.
- afterUImerge&atomicread room+fixture5passed4.51s, Node66.
Source reports copied into docs/reports/v2-document-insights-*,v2-meeting-hints-*,
v2-room-ui-*. Live НЕ запускались. Все tests на doubles/синтетике.

Текущий НЕкоммитнутый radar: миграция21 добавляетseasonality_samples,
pickup_storage(LOG minimalprojection),erp_orders.storage_expires_at,
weekly_digest_outbox,task_effect_checks. Frozen fixturesv1/v2 НЕ менялись:
новыйdemo/track3/seasonality.json отдельно (история2025 75%→111%,coef1.48).
seed_insights.py idempotentdatasetextension, UTF8 explicit; вызывается в seed
какдляновойтакдляужеseededDB. retention cleanup/deleteuser расширены.
management/advanced.py:6weekmovingaverage3weeks×Dec coefficient, qualityradar,
PVZexpiry≤2days, signed insight sources rehydrated currentACL; sourcefactory
binds both rawrows and computedprojection. New routes in advanced_api.py;
Basis allowsinsight; source resolver handleradded. weekly_digest.py preview/
confirm/cancel/replay, owner localEML/readrecheck; effect_checks.py confirms
metricgoal afterdecision, tick afterNdays only fresh newdata,111→96unitcontrol,
no claim ofcausality/no taskstatuschanges. baseline_json/aftermetricIDs guard
ACL onread/tick. AdvancedUI in static/meetings/advanced.js and hookoverview;
sourcepanel supportsinsight basis/counts/points. No newdesign/deps.
Targettests6passed9.03s, integrationseed/operations/basis total28passed23.77s
BEFORE last tiny readtransaction/status-open patches. JSsyntax passed.
Need addHTTP/browser scenarios, docs/formulas/privacy/APIexport/workflowsyntax,
run full/Node/evaluator/cleaninstall, explicitcommit, then mergeprimaryUIfixes
into radar before publication. Do not accidentally publishradarbeforefull.

Остаток послеradar: E12 gated Telegram/Bitrix notification transport and
SMTP optionalhumanpreviewconfirm, tests onlyMockTransport. Пока кода нет,
естьresearch+план; existing queues/localEML alreadywork. Official API sources:
core.telegram.org/bots/api(sendMessage/link_preview_options), docs.python.org/3/
library/smtplib.html(SMTP_SSL), apidocs.bitrix24.com im.notify.personal.add.
Then final E13/E14traceability6branches/API/README/DEMO/PITCH/licenses/secrets,
CI+cleaninstall+mainmerge. Embeddings/OCR/ATCwatcher explicitlyoptional, no need
turnthem into compulsorywork. No liveaccounts/models, .env/data/models secrets
or start-gateway edits; no add./reset/clean/rebase/force; no subagents.

Publicationhelpers are scratchPython; publish_small.py always reads HEAD from
track3-v2 and diff current origin/track3/v2-fotoprint, so DO NOT useit directly
for radar until merged into primary or editexplicitroot. It writes
small-publish-manifest.json, read_small_chunk.py reads12000Unicodechars;
load chunks in Promise.allSettled batches10, creates tree base remote tree,
verifyexactlocaltree, createcommit parentremote, update_ref expectedsha falseforce.
Other manifests/functions stores OLD; regenerate after every commit/merge.
Get GitHubmetadata in ALL_TOOLS. Linkid6af46af9328c8191b6c424fd52d939b1.
