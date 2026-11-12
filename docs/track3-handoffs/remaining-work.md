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
