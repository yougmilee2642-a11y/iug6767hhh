import { documentLibrary } from './documents.js';
import { formulaLine } from './formula.js';

// Демо «Фотопринт»: вопросы, на которые в документах роли есть подтверждённый ответ.
const EXAMPLE_QUESTIONS = {
  director: ['Каков демо-бюджет акции Premium?', 'Какова доля завершённых в срок заказов по срезу ERP?'],
  prod_head: ['По скольким контрольным точкам ОТК проверяет переплёт Premium?', 'Когда назначено плановое ТО Kolbus и какова его продолжительность по графику?',
    'Каков прогноз загрузки переплёта Kolbus на 15–21 декабря?', 'При каком условии подтверждённый брак Premium направляется на бесплатную перепечатку?'],
  sup_head: ['Какова цель первого ответа по браку и кому передаётся просрочка?', 'Сколько из 400 обращений закрыла Mary и на сколько ответили в SLA?'],
  mod_lead: ['Какое разрешение проверяет модерация макетов Premium перед производством?'],
  designer: ['Какие поля обреза нужны для макета обложки Premium по брифу дизайнера?'],
  picpac_lead: ['Каков срок изготовления Lite, Classic и Premium без доставки в демо?'],
  mkt_lead: ['Какова скидка демо-акции Premium и до какой даты она действует?'],
  sales_head: ['Что согласуется для корпоративных выпускных альбомов до запуска печати?'],
};
const $ = (selector) => document.querySelector(selector);
// Track 3 views. API payloads follow the core and knowledge server handoffs.
// This module has no demo fallback; fixtures live exclusively in tests/ui_track3.
export function track3UI(h) {
  const { node, makeButton: button, makeInput: input, makeTextarea: textarea, makeSelect: select,
    request, runAction: run, state, dateLabel: date, render, openMeeting, showNotice, toast } = h;
  let overview = null;
  let overviewStatus = 'idle';
  let answer = null;
  let question = '';
  let includeHistory = false;
  let context = '';
  let qaBusy = false;
  let qaSequence = 0;
  let answerContext = '';
  let answerQuestion = '';
  let calendarDrafts = new Map();
  let taskDrafts = new Map();
  let activeDialog = null;
  let generation = 0;
  const can = (capability) => state.capabilities.includes(capability);
  const key = () => crypto.randomUUID();
  const field = (label, control) => {
    control.setAttribute('aria-label',label);
    const wrap = node('label', 'meeting-field');
    wrap.append(node('span', 'field-label', label), control);
    return wrap;
  };
  const heading = (parent, title, description) => {
    const copy = node('header', 'meetings-heading');
    const text = node('div');
    text.append(node('h1', '', title), node('p', 'muted-copy', description));
    copy.append(text); parent.append(copy);
  };
  const sourceDate = (source) => `Дата источника: ${date(source?.source_at)}`;
  const formatTime = (value, zone) => {
    try { return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short', timeZone: zone }).format(new Date(value)); }
    catch { return date(value); }
  };

  const documents = documentLibrary({...h, dialog, field, sourceButton, claims});

  function reset({ keepDrafts = false } = {}) {
    generation++;
    documents.reset();
    overview = answer = null;
    overviewStatus = 'idle';
    question = context = answerContext = answerQuestion = '';
    includeHistory = false;
    qaSequence++;
    qaBusy = false;
    if (!keepDrafts) { calendarDrafts = new Map(); taskDrafts = new Map(); }
    activeDialog?.close();
    activeDialog?.remove();
    activeDialog = null;
  }

  function discardForeignDrafts(userId) {
    for (const drafts of [calendarDrafts, taskDrafts]) {
      for (const id of drafts.keys()) if (!id.startsWith(`${userId}/`)) drafts.delete(id);
    }
  }

  // A native dialog supplies a focus trap, Escape, and focus return in the browser.
  function dialog(title, content, confirmAction, cancelAction, confirmLabel = 'Подтвердить', returnFocus = document.activeElement) {
    if (activeDialog?.open) return;
    const origin = returnFocus;
    const openedGeneration = generation;
    const modal = node('dialog', 'meet-preview');
    const id = `preview-${key()}`;
    modal.setAttribute('aria-labelledby', id);
    const label = node('h2', '', title); label.id = id;
    const error = node('p', 'inline-error'); error.setAttribute('role', 'alert');
    const actions = node('div', 'inline-actions');
    let busy = false;
    let committed = false;
    const restoreOrigin = () => {
      if (generation !== openedGeneration) return;
      const target = origin?.isConnected ? origin : document.querySelector('#app h1');
      if (target) { if (target.tagName === 'H1') target.tabIndex = -1; target.focus(); }
    };
    // Native cancel hides the dialog before its later close event. Restore focus
    // synchronously so Escape completion always includes focus returning to origin.
    const dismiss = () => { modal.close(); restoreOrigin(); };
    const cancel = button('Отмена', dismiss);
    const confirm = button(confirmLabel, async () => {
      if (busy || generation !== openedGeneration) return;
      busy = true; cancel.disabled = confirm.disabled = true;
      error.textContent = '';
      const controls = [...content.querySelectorAll('input, textarea, select')].map((control) => [control, control.disabled]);
      controls.forEach(([control]) => { control.disabled = true; });
      try {
        await confirmAction(); committed = true; modal.close();
      } catch (e) {
        if (e.code !== 'stale_session') error.textContent = e.message;
      } finally {
        busy = false; cancel.disabled = confirm.disabled = false;
        controls.forEach(([control, disabled]) => { control.disabled = disabled; });
      }
    }, 'primary-button');
    actions.append(cancel, confirm);
    modal.append(label, content, error, actions);
    modal.addEventListener('cancel', (event) => { event.preventDefault(); if (!busy) dismiss(); });
    modal.addEventListener('close', () => {
      if (generation === openedGeneration && !committed && cancelAction) void cancelAction().catch((e) => {
        if (state.user && generation === openedGeneration) showNotice(`Предпросмотр закрыт. ${e.message}`);
      });
      if (generation === openedGeneration) h.markSaved(modal);
      modal.remove(); if (activeDialog === modal) activeDialog = null;
      restoreOrigin();
    }, { once: true });
    document.body.append(modal); activeDialog = modal; modal.showModal(); cancel.focus();
    return modal;
  }

  function sourceButton(source) {
    return button(`${source.title || 'Источник'} · ${sourceDate(source)}`, async () => {
      const kind = { document: 'fragment', utterance: 'utterance' }[source.kind];
      if (kind) return h.openSource(kind, source.id, source.quote, source);
      await h.openSource(source.kind, source.id, source.quote, source);
    }, 'citation-chip');
  }

  function claims(parent, values) {
    for (const claim of values || []) {
      const card = node('article', 'claim-item');
      card.append(node('p', '', claim.text));
      for (const source of claim.sources || []) card.append(sourceButton(source));
      parent.append(card);
    }
  }

  async function loadOverview() {
    if (overviewStatus === 'loading') return;
    const current = generation;
    overviewStatus = 'loading'; overview = null;
    if (state.page === 'overview') render();
    try {
      const result = await request('/overview');
      if (current !== generation) return;
      overview = result; overviewStatus = 'ready';
    } catch (e) {
      if (current !== generation) return;
      overviewStatus = 'error'; overview = { message: e.message };
    }
    if (state.page === 'overview') render();
  }

  const zoneDay = (value, zone) => {
    try { return new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value)); }
    catch { return String(value).slice(0, 10); }
  };
  const zoneTime = (value, zone) => {
    try { return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: zone }).format(new Date(value)); }
    catch { return ''; }
  };

  function todayColumn(parent) {
    const zone = state.timezone;
    const today = zoneDay(new Date(), zone);
    const dated = state.meetings.filter((m) => m.scheduled_at).sort((a, b) => String(a.scheduled_at).localeCompare(String(b.scheduled_at)));
    let list = dated.filter((m) => zoneDay(m.scheduled_at, m.timezone || zone) === today);
    const title = list.length ? 'Сегодня' : 'Ближайшие встречи';
    if (!list.length) list = dated.filter((m) => zoneDay(m.scheduled_at, m.timezone || zone) > today).slice(0, 3);
    const column = node('section', 'overview-column');
    column.append(node('h2', '', title));
    if (!list.length) column.append(node('p', 'empty-copy', 'Запланированных встреч нет.'));
    for (const meeting of list) {
      const row = node('article', 'overview-meeting');
      const when = zoneDay(meeting.scheduled_at, meeting.timezone || zone) === today
        ? zoneTime(meeting.scheduled_at, meeting.timezone || zone)
        : new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' }).format(new Date(meeting.scheduled_at));
      const copy = node('div', '');
      const people = (meeting.participants || []).length;
      const topic = meeting.topic && meeting.topic.trim() !== (meeting.title || '').trim() ? meeting.topic : '';
      copy.append(node('b', '', meeting.title || 'Без названия'), node('small', '', [topic, people ? `${people} ${people % 10 === 1 && people % 100 !== 11 ? 'участник' : people % 10 >= 2 && people % 10 <= 4 && (people % 100 < 10 || people % 100 >= 20) ? 'участника' : 'участников'}` : ''].filter(Boolean).join(' · ')));
      row.append(node('span', 'overview-time', when), copy, button('Открыть', () => void openMeeting(meeting.id), 'task-meeting-link'));
      column.append(row);
    }
    return column;
  }

  function attentionColumn() {
    const column = node('section', 'overview-column');
    column.append(node('h2', '', 'Требуют внимания'));
    const tasks = overview.overdue_tasks || [];
    if (!tasks.length) column.append(node('p', 'empty-copy', 'Просроченных задач в доступных данных нет.'));
    for (const task of tasks) {
      const row = node('article', 'overview-attention');
      row.append(node('b', '', task.text), node('small', '', `до ${date(task.due)}${task.meeting_title ? ` · ${task.meeting_title}` : ''}`));
      row.append(button(`Открыть задачу во встрече «${task.meeting_title || task.meeting_id}»`, () => void openTask(task), 'task-meeting-link'));
      column.append(row);
    }
    return column;
  }

  function renderOverview(parent) {
    const day = new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', timeZone: state.timezone }).format(new Date());
    const hour = Number(new Intl.DateTimeFormat('ru-RU', { hour: 'numeric', hour12: false, timeZone: state.timezone }).format(new Date()));
    const hello = hour >= 5 && hour < 12 ? 'Доброе утро' : hour >= 12 && hour < 18 ? 'Добрый день' : hour >= 18 && hour < 23 ? 'Добрый вечер' : 'Доброй ночи';
    const name = String(state.user?.name || '').trim().split(/\s+/)[0];
    heading(parent, 'Обзор', `${hello}${name ? `, ${name}` : ''} · ${day.charAt(0).toUpperCase() + day.slice(1)}`);
    if (can('meetings.create')) {
      const create = button('Новая встреча', () => { state.showCreateMeeting = true; h.navigate('meetings'); }, 'primary-button accent-button');
      parent.lastElementChild.append(create);
    }
    if (overviewStatus === 'idle') { void loadOverview(); return; }
    if (overviewStatus === 'loading') { parent.append(node('p', '', 'Загружаю показатели…')); return; }
    if (overviewStatus === 'error') {
      parent.append(button('Обновить обзор', () => void loadOverview()), node('p', 'inline-error', overview.message)); return;
    }
    for (const warning of overview.warnings || []) parent.append(node('p', 'gap-state', warning));
    const columns = node('div', 'overview-columns');
    columns.append(todayColumn(), attentionColumn());
    parent.append(columns);
    const meta = node('div', 'overview-meta');
    meta.append(node('h2', '', 'Показатели'), node('p', 'muted-copy', `Актуальность витрины: ${date(overview.as_of)} · Рассчитано: ${date(overview.generated_at)}`),
      button('Обновить обзор', () => void loadOverview(), 'text-button'));
    parent.append(meta);
    const grid = node('div', 'meet-kpi-grid');
    for (const metric of overview.metrics || []) {
      const card = node('article', 'panel meet-kpi');
      card.append(node('h2', '', metric.label), node('strong', 'meet-kpi-value', metric.value == null ? 'Нет данных' : `${metric.value} ${metric.unit || ''}`));
      card.append(formulaLine(node, metric));
      if (['warning', 'critical'].includes(metric.status)) card.append(node('p', metric.status === 'critical' ? 'warning-badge red' : 'warning-badge amber', `Демо-порог: ${metric.status === 'critical' ? 'критично' : 'внимание'}`));
      if (metric.source) card.append(sourceButton(metric.source));
      grid.append(card);
    }
    if (!grid.childNodes.length) grid.append(node('p', 'empty-copy', 'Доступных показателей нет.'));
    parent.append(grid);
    if ((overview.capacity_forecast || []).length) {
      parent.append(node('h2','','Прогноз мощности · доступные будущие периоды'));
      for (const point of overview.capacity_forecast) parent.append(node('p','',`${date(point.period_start)} — ${date(point.period_end)}: ${point.value ?? 'не рассчитано'} % (${point.occupied_hours}/${point.available_hours} часов)`));
    }
    if ((overview.delay_reasons || []).length) {
      parent.append(node('h2','','Причины просрочки завершённых заказов'));
      for (const reason of overview.delay_reasons) {
        parent.append(node('p','',`${reason.reason}: ${reason.count}/${reason.total_late} · ${reason.percent} %`));
        if (reason.source) parent.append(sourceButton(reason.source));
      }
    }
    if ((overview.decision_controls || []).length) {
      parent.append(node('h2','','Решения на контроле'));
      for (const decision of overview.decision_controls) {
        const row=node('article','panel task-card');
        row.append(node('p','',decision.text),node('p','task-meta',`Ответственный: ${decision.owner_name || 'не уточнён'} · срок: ${decision.due ? date(decision.due):'не уточнён'} · ${{open:'открыто',done:'завершено',cancelled:'отменено'}[decision.status]}`));
        row.append(button('Открыть решение в протоколе',()=>openMeeting(decision.meeting_id,'protocol'),'task-meeting-link'));
        if (decision.source_quote?.utterance_id) row.append(button('Реплика решения',()=>h.openSource('utterance',decision.source_quote.utterance_id,decision.source_quote.text),'citation-chip'));
        if (can('protocol.confirm')) row.append(button('Изменить контроль решения',()=>void controlDecision({id:decision.protocol_item_id,text:decision.text},decision.meeting_id,decision)));
        parent.append(row);
      }
    }
    claims(parent, overview.summary);
  }

  async function controlDecision(item, meetingId, existing = null) {
    const origin = document.activeElement; const current = generation;
    try {
      if (!existing) existing = (await request('/decisions')).decisions.find(row => row.protocol_item_id === item.id) || null;
      if (current !== generation || !state.user) return;
      const form = node('form','meet-form-grid');
      const people = [{value:'',label:'Ответственный не уточнён'}, ...state.users.filter(user=>user.active && !['admin','auditor'].includes(user.level)).map(user=>({value:String(user.id),label:user.name}))];
      if (existing?.owner_user_id && !people.some(person=>person.value===String(existing.owner_user_id))) people.push({value:String(existing.owner_user_id),label:(existing.owner_name || 'Прежний ответственный')+' · неактивен'});
      const owner = select(people,String(existing?.owner_user_id || ''));
      const due = input({label:'Срок контроля',type:'date',value:existing?.due || ''});
      const status = select([{value:'open',label:'Открыто'}, {value:'done',label:'Завершено'}, {value:'cancelled',label:'Отменено'}],existing?.status || 'open');
      form.append(node('p','',item.text),field('Ответственный за решение',owner),due.wrap,field('Статус контроля',status));
      const editor = dialog('Контроль решения',form,async()=>{
        const preview = await request(`/decisions/${item.id}/preview`,{method:'POST',body:{owner_user_id:owner.value ? Number(owner.value):null,due:due.input.value || null,status:status.value}});
        editor.close(); editor.addEventListener('close',()=>{
          if (generation !== current || !state.user) return;
          const content = node('div'); const change=preview.preview.after;
          content.append(node('p','',preview.preview.text),node('p','',`Ответственный: ${people.find(person=>person.value===String(change.owner_user_id))?.label || 'не уточнён'}`),node('p','',`Срок: ${change.due ? date(change.due) : 'не уточнён'}`),node('p','',`Статус: ${{open:'открыто',done:'завершено',cancelled:'отменено'}[change.status]}`));
          const quote=preview.preview.source_quote;
          content.append(button('Реплика-основание',()=>h.openSource('utterance',quote.utterance_id,quote.text),'citation-chip'));
          const idempotency=key();
          dialog('Подтвердить контроль решения',content,async()=>{
            await request(`/decisions/${item.id}/confirm`,{method:'POST',body:{confirmation_id:preview.confirmation_id,idempotency_key:idempotency}});
            if (state.page==='overview') await loadOverview(); else await h.refreshMeeting(meetingId);
            toast('Контроль решения сохранён');
          },()=>cancelConfirmation(preview.confirmation_id),'Подтвердить',origin);
        },{once:true});
      },null,'Предпросмотр',origin);
      form.addEventListener('submit',event=>event.preventDefault());
    } catch(error) { if (current===generation && state.user) showNotice(error.message); }
  }

  async function openTask(task) {
    await openMeeting(task.meeting_id, 'tasks');
    document.getElementById(`task-${task.id}`)?.focus();
  }

  function openKnowledge(meetingId = '') {
    if (String(context) !== String(meetingId)) { answer = null; qaSequence++; qaBusy = false; }
    context = String(meetingId);
    h.navigate('knowledge');
  }

  function renderKnowledge(parent) {
    heading(parent, 'Знания', 'Спросите о встречах и документах');
    const layout = node('div', 'knowledge-layout');
    const aside = node('aside', 'knowledge-sources');
    aside.append(node('h2', '', 'Источники'));
    const recent = state.documents.filter((d) => !d.superseded).slice(0, 8);
    const list = node('ul', 'knowledge-source-list');
    for (const doc of recent) {
      const item = node('li', '');
      item.append(button(doc.title || doc.filename || 'Документ', () => void run(null, () => documents.open(doc)), 'source-link'));
      list.append(item);
    }
    if (!recent.length) aside.append(node('p', 'empty-copy', 'Доступных материалов пока нет.'));
    else aside.append(list);
    documents.render(aside);
    const main = node('div', 'knowledge-main');
    layout.append(aside, main);
    parent.append(layout);
    parent = main;
    const form = node('form', 'panel meet-knowledge');
    const scope = select([{ value: '', label: 'Все доступные материалы' }, ...state.meetings.map((m) => ({ value: m.id, label: m.title }))], context);
    scope.addEventListener('change', () => { context = scope.value; answer = null; qaSequence++; render(); });
    const q = textarea({ label: 'Ваш вопрос', value: question, required: true, rows: 3 });
    q.input.maxLength = 2000;
    q.input.addEventListener('input', () => { question = q.input.value; });
    const history = input({label:'Искать также в истории версий',type:'checkbox'});
    history.input.checked=includeHistory;history.input.disabled=qaBusy;
    history.input.addEventListener('change',()=>{includeHistory=history.input.checked;answer=null;qaSequence++;render();});
    const submit = button(qaBusy ? 'Формируется ответ…' : 'Задать вопрос', null, 'primary-button', 'submit');
    submit.disabled = qaBusy || !can('qa.ask');
    scope.disabled = qaBusy;
    form.append(field('Контекст', scope), q.wrap, history.wrap, submit);
    form.addEventListener('submit', async (event) => {
      event.preventDefault(); if (qaBusy || !q.input.value.trim()) return;
      question = q.input.value;
      const current = generation;
      const askedContext = context;
      const askedQuestion = question.trim();
      const sequence = ++qaSequence;
      qaBusy = true; answer = null; submit.disabled = true;
      await run(submit, async () => {
        const result = await request('/qa', { method: 'POST', body: { question: askedQuestion, include_history:history.input.checked, ...(askedContext ? { meeting_id: Number(askedContext) } : {}) } });
        if (current === generation && sequence === qaSequence) { answer = result; answerContext = askedContext; answerQuestion = askedQuestion; qaBusy = false; if (state.page === 'knowledge') render(); }
      }, { model: true, label: 'Формируется ответ…' });
      if (current !== generation || sequence !== qaSequence) return;
      qaBusy = false;
      if (state.page === 'knowledge') render();
    });
    parent.append(form);
    const examples = EXAMPLE_QUESTIONS[state.user?.login] || [];
    if (examples.length && !qaBusy) {
      const box = node('div', 'question-examples');
      box.append(node('span', 'question-examples-title', 'Например'));
      for (const text of examples) box.append(button(text, () => { question = text; answer = null; render(); $('.knowledge-main textarea')?.focus(); }, 'question-example'));
      parent.append(box);
    }
    if (qaBusy) parent.append(node('p', 'muted-copy', 'Модель обрабатывает вопрос. Можно перейти в другой раздел.'));
    if (!answer) return;
    const result = node('section', 'panel meet-knowledge');
    result.setAttribute('aria-label', 'Ответ');
    const groundedClaims = (answer.claims || []).filter((claim) => claim.sources?.length);
    result.append(node('p', 'task-meta', `Вопрос: ${answerQuestion}`));
    if (answer.status !== 'grounded' || !groundedClaims.length) {
      result.append(node('h2', '', 'Оснований не найдено'), node('p', '', 'В доступных материалах недостаточно проверяемых данных. Уточните вопрос или добавьте материалы.'));
    } else {
      result.append(node('h2', '', 'Ответ с источниками'));
      // Render only claims carrying server-verified sources, never free-form answer HTML.
      claims(result, groundedClaims);
    }
    (answer.warnings || []).forEach(w=>result.append(node('p','access-limited-note',w.message)));
    result.append(node('p', 'task-meta', `Сформировано: ${date(answer.generated_at)}`));
    result.append(feedback('qa_answer', answer.answer_id, askedMeeting()));
    parent.append(result);
  }
  const askedMeeting = () => answerContext ? Number(answerContext) : undefined;

  function feedback(type, id, meetingId) {
    const form = node('form', 'meet-feedback');
    form.dataset.itemId = `feedback-${type}-${id}`;
    form.append(node('h3', '', 'Обратная связь'));
    if (!can('feedback.create') || id == null) {
      form.append(node('p', 'empty-copy', 'Обратная связь недоступна для этого результата.')); return form;
    }
    const rating = select([{ value: 'useful', label: 'Полезно' }, { value: 'incorrect', label: 'Ошибка' }]);
    const comment = textarea({ label: 'Комментарий (необязательно)', rows: 2 }); comment.input.maxLength = 1000;
    const submit = button('Отправить отзыв', null, 'secondary-button', 'submit');
    form.append(field('Оценка', rating), comment.wrap, submit);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const success = await run(submit, () => request('/feedback', { method: 'POST', body: {
        target_type: type, target_id: String(id), rating: rating.value, comment: comment.input.value,
        ...(meetingId != null ? { meeting_id: meetingId } : {}), ...(type === 'qa_answer' ? { answer_id: id } : {}),
      } }));
      if (success) { h.markSaved(form); form.replaceChildren(node('p', '', 'Отзыв отправлен')); toast('Спасибо, отзыв сохранён'); }
    });
    if (type === 'qa_answer') return form;
    const disclosure = node('details', 'meet-feedback-disclosure');
    disclosure.append(node('summary', '', 'Обратная связь: полезно / ошибка'), form);
    return disclosure;
  }

  function planning(parent) {
    const meeting = state.meetingData.meeting;
    const meetingId = meeting.id;
    const calendarKey = `${state.user.id}/${meetingId}`;
    const saved = calendarDrafts.get(calendarKey) || {};
    const panel = node('section', 'panel meet-planning');
    panel.append(node('h2', '', 'Параметры и свободное время'));
    const edit = node('form', 'meet-form-grid');
    const topic = textarea({ label: 'Тема и цель встречи', value: saved.topic ?? meeting.topic, rows: 2 });
    const people = textarea({ label: 'Участники встречи (по одному в строке)', value: saved.people ?? (meeting.participants || []).join('\n'), rows: 2 });
    const remember = () => calendarDrafts.set(calendarKey, { ...calendarDrafts.get(calendarKey), topic: topic.input.value, people: people.input.value });
    topic.input.addEventListener('input', remember); people.input.addEventListener('input', remember);
    topic.input.disabled = people.input.disabled = !can('meetings.edit');
    edit.append(topic.wrap, people.wrap);
    const save = button('Сохранить тему и участников', null, 'secondary-button', 'submit'); save.disabled = !can('meetings.edit');
    edit.append(save);
    edit.addEventListener('submit', async (event) => {
      event.preventDefault();
      await run(save, async () => {
        const acknowledge = h.draftCheckpoint(edit);
        const sent = { topic: topic.input.value, people: people.input.value };
        const result = await request(`/meetings/${meetingId}`, { method: 'PATCH', body: {
          topic: sent.topic.trim(), participants: sent.people.split(/[\n,;]+/).map((v) => v.trim()).filter(Boolean),
        } });
        if (state.meetingData?.meeting?.id === meetingId) state.meetingData.meeting = result.meeting;
        state.meetings = state.meetings.map((item) => String(item.id) === String(meetingId) ? result.meeting : item);
        acknowledge();
        const draft = calendarDrafts.get(calendarKey) || {};
        for (const field of ['topic', 'people']) if (draft[field] === sent[field]) delete draft[field];
        calendarDrafts.set(calendarKey, draft);
        if (state.page === 'meeting' && state.meetingData?.meeting?.id === meetingId) render();
        toast('Параметры сохранены');
      });
    });
    panel.append(edit);
    const form = node('form', 'meet-form-grid');
    const zone = input({ label: 'Часовой пояс IANA', value: saved.zone || state.timezone, required: true });
    const start = input({ label: 'Начало поиска (дата и время в зоне)', type: 'datetime-local', value: saved.start || '', required: true });
    const end = input({ label: 'Конец поиска (дата и время в зоне)', type: 'datetime-local', value: saved.end || '', required: true });
    const duration = input({ label: 'Продолжительность, минут', type: 'number', value: saved.duration || 60, required: true });
    duration.input.min = 15; duration.input.max = 540; duration.input.step = 15;
    const smart = node('input');smart.type='checkbox';smart.checked=saved.smart ?? true;
    const smartLabel=field('Учитывать смены, перерывы и буфер 10 минут',smart);
    const weekends=node('input');weekends.type='checkbox';weekends.checked=saved.weekends ?? false;
    const weekendsLabel=field('Искать также в выходные (при наличии рабочих смен)',weekends);
    let revision = 0;
    const viewGeneration = generation;
    const participants = node('fieldset', 'access-users'); participants.append(node('legend', '', 'Календарные участники из тестового справочника'));
    const load = button('Загрузить участников', async () => {
      await run(load, async () => {
        const result = await request('/calendar/participants');
        if (viewGeneration !== generation) return;
        calendarDrafts.set(calendarKey, { ...calendarDrafts.get(calendarKey), directory: result.participants || [] });
        renderParticipants(result.participants || []);
      });
    });
    participants.append(load);
    const search = button('Найти свободное время', null, 'secondary-button', 'submit');
    search.disabled = !can('calendar.view') || !saved.directory;
    form.append(zone.wrap, start.wrap, end.wrap, duration.wrap, smartLabel, weekendsLabel, participants, search);
    const slots = node('div', 'meet-slots'); slots.setAttribute('aria-live', 'polite');
    const rememberRange = () => calendarDrafts.set(calendarKey, { ...calendarDrafts.get(calendarKey), zone: zone.input.value,
      start: start.input.value, end: end.input.value, duration: duration.input.value,
      smart:smart.checked,weekends:weekends.checked,
      participantIds: [...participants.querySelectorAll('input[data-calendar-role="participant"]:checked')].map((box) => box.value),
      optionalIds:[...participants.querySelectorAll('input[data-calendar-role="optional"]:checked')].map((box)=>box.value) });
    function renderParticipants(directory) {
      const selected = calendarDrafts.get(calendarKey)?.participantIds;
      participants.replaceChildren(node('legend', '', 'Календарные участники'));
      participants.append(node('p', 'task-meta', 'Организатор включён в приглашение автоматически.'));
      for (const person of directory) {
        const label = node('label', 'check-label'); const box = node('input'); box.type = 'checkbox'; box.value = person.id;
        box.dataset.calendarRole='participant';
        const organizer = String(person.id) === String(state.user?.id);
        box.checked = organizer || Boolean(selected?.includes(String(person.id)));
        box.disabled = organizer;
        label.append(box, node('span', '', person.name)); participants.append(label);
        if (!organizer) {
          const optionalLabel=node('label','check-label'),optionalBox=node('input');optionalBox.type='checkbox';optionalBox.value=person.id;
          optionalBox.dataset.calendarRole='optional';optionalBox.checked=Boolean(saved.optionalIds?.includes(String(person.id)));
          optionalBox.disabled=!smart.checked || !box.checked;
          optionalLabel.append(optionalBox,node('span','',`Необязательный участник: ${person.name}`));participants.append(optionalLabel);
          box.addEventListener('change',()=>{optionalBox.disabled=!smart.checked||!box.checked;if(!box.checked)optionalBox.checked=false;});
        }
      }
      search.disabled = !can('calendar.view');
      rememberRange();
    }
    if (saved.directory) renderParticipants(saved.directory);
    form.addEventListener('input', () => {
      for(const optionalBox of participants.querySelectorAll('input[data-calendar-role="optional"]')) {
        const main=[...participants.querySelectorAll('input[data-calendar-role="participant"]')].find(box=>box.value===optionalBox.value);
        optionalBox.disabled=!smart.checked || !main.checked;
      }
      rememberRange(); revision++;
      slots.replaceChildren(node('p', 'muted-copy', 'Параметры изменились. Подберите свободное время заново.'));
    });
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (search.disabled) return;
      rememberRange();
      await run(search, async () => {
        const searchedRevision = revision;
        const body = {
          timezone: zone.input.value.trim(), range_start: zonedISO(start.input.value, zone.input.value.trim()),
          range_end: zonedISO(end.input.value, zone.input.value.trim()), duration_minutes: Number(duration.input.value),
          smart:smart.checked,
          include_weekends:weekends.checked,
          participant_ids: [...participants.querySelectorAll('input[data-calendar-role="participant"]:checked')].filter(box=>!smart.checked || !participants.querySelector(`input[data-calendar-role="optional"][value="${box.value}"]`)?.checked).map((box) => Number(box.value)),
          optional_participant_ids:smart.checked ? [...participants.querySelectorAll('input[data-calendar-role="optional"]:checked:not(:disabled)')].map(box=>Number(box.value)) : [],
        };
        slots.replaceChildren(node('p', '', 'Подбираю время…'));
        let result;
        try { result = await request('/calendar/slots', { method: 'POST', body }); }
        catch (e) { slots.replaceChildren(node('p', 'inline-error', 'Не удалось подобрать время. Измените параметры или повторите поиск.')); throw e; }
        if (!form.isConnected || searchedRevision !== revision || viewGeneration !== generation) return;
        slots.replaceChildren(node('p', 'muted-copy', `${result.provider==='mock' ? 'Тестовый календарь' : 'Внешний календарь'} · зона ${result.timezone} · ${(result.participants || []).map((p) => p.name).join(', ')}`));
        for(const warning of result.warnings || [])slots.append(node('p','gap-state',warning));
        if(result.generated_at)slots.append(node('p','task-meta',`Подбор рассчитан: ${date(result.generated_at)}`));
        if (!result.slots?.length) slots.append(node('p', '', 'Свободных слотов нет. Измените диапазон или состав участников.'));
        for (const slot of result.slots || []) {
          const choose = button(`${formatTime(slot.start_at, result.timezone)} — ${formatTime(slot.end_at, result.timezone)}`, async () => {
            if (searchedRevision !== revision) return;
            await run(choose, async () => {
              let preview;
              try { preview = await request('/calendar/preview', { method: 'POST', body: {
                meeting_id: meetingId, participant_ids: body.participant_ids, start_at: slot.start_at,
                duration_minutes: body.duration_minutes, timezone: body.timezone,
                smart:body.smart,optional_participant_ids:body.optional_participant_ids,
              } }); } catch (e) {
                if (e.status === 409) slots.replaceChildren(node('p', 'gap-state', `${e.message} Введённые параметры сохранены.`), button('Обновить слоты', () => form.requestSubmit()));
                throw e;
              }
              if (!form.isConnected || searchedRevision !== revision || viewGeneration !== generation) {
                if (viewGeneration === generation) await cancelConfirmation(preview.confirmation_id);
                return;
              }
              const content = calendarPreview(preview);
              const idempotencyKey = key();
              dialog('Проверить встречу и приглашения', content, async () => {
                try {
                  await request('/calendar/confirm', { method: 'POST', body: { confirmation_id: preview.confirmation_id, idempotency_key: idempotencyKey } });
                  toast('Встреча назначена. Приглашения сохранены в локальной очереди.');
                  h.markSaved(form);
                  try { await h.refreshMeeting(meetingId); }
                  catch (e) {
                    if (viewGeneration === generation && state.user) showNotice('Встреча назначена. Не удалось обновить данные; повторите загрузку.', () => run(null, () => h.refreshMeeting(meetingId)));
                  }
                } catch (e) {
                  if (e.status === 409) {
                    content.append(button('Обновить слоты', () => { activeDialog?.close(); form.requestSubmit(); }));
                    e.message = `${e.message} Обновите слоты. Введённые параметры сохранены.`;
                  }
                  throw e;
                }
              }, () => cancelConfirmation(preview.confirmation_id), 'Подтвердить', choose);
            });
          });
          choose.disabled = !can('calendar.invite'); slots.append(choose);
          if(slot.reason)slots.append(node('p','task-meta',slot.reason));
        }
      });
    });
    panel.append(form, slots, button('Вопрос по материалам этой встречи', () => openKnowledge(meetingId), 'text-button'));
    parent.append(panel);
  }

  function calendarPreview(result) {
    const p = result.preview; const content = node('div');
    content.append(node('p', '', p.title), node('p', '', `${formatTime(p.start_at, p.timezone)} — ${formatTime(p.end_at, p.timezone)} · ${p.timezone}`));
    content.append(node('p', '', `Участники: ${(p.participants || []).map((person) => person.name).join(', ')}`));
    content.append(node('p', 'gap-state', 'Тестовые приглашения: запись только в локальную очередь. Реальные письма не отправляются.'));
    for (const invitation of p.invitations || []) {
      content.append(node('h3', '', invitation.recipient_name), node('p', '', invitation.subject), node('p', 'source-full-text', invitation.body));
    }
    for (const warning of p.warnings || []) content.append(node('p', 'gap-state', warning));
    content.append(node('p', 'task-meta', `Предпросмотр действителен до ${date(result.expires_at)}`));
    return content;
  }

  const cancelConfirmation = (id) => request(`/confirmations/${encodeURIComponent(id)}/cancel`, { method: 'POST' });

  function editTask(task, collection, meetingOnly) {
    const origin = document.activeElement;
    const viewGeneration = generation;
    const draftKey = `${state.user.id}/${task.id}`;
    const draft = taskDrafts.get(draftKey) || task;
    const form = node('form', 'meet-form-grid');
    form.dataset.itemId = `task-${task.id}`;
    const status = select([{ value: 'open', label: 'Открыта' }, { value: 'in_progress', label: 'В работе' }, { value: 'done', label: 'Готова' }, {value:'blocked',label:'Заблокирована'}, {value:'cancelled',label:'Отменена'}], draft.status);
    const assignee = input({ label: 'Ответственный', value: draft.assignee || '' });
    const due = input({ label: 'Срок', type: 'date', value: draft.due || '' });
    const priority = select([{value:'low',label:'Низкий'}, {value:'normal',label:'Обычный'}, {value:'high',label:'Высокий'}, {value:'urgent',label:'Срочный'}], draft.priority || 'normal');
    const links = textarea({label:'Связи · по строке: order:PP-2611-00042, customer:client-0001, document:12',
      value:(draft.linked_entities || []).map(entity => `${entity.kind}:${entity.id}`).join('\n'), rows:3});
    const ownStatusOnly = state.user?.level === 'employee' && !(state.user.delegations || []).some(grant => grant.department_id === task.department_id);
    assignee.input.disabled = due.input.disabled = priority.disabled = links.input.disabled = ownStatusOnly;
    form.append(node('p', '', task.text), field('Статус задачи', status), assignee.wrap, due.wrap, field('Приоритет',priority), links.wrap);
    if (!task.due && task.due_text) form.append(node('p', 'task-meta', `Срок словами: ${task.due_text}. Он сохраняется, если не назначать новую дату.`));
    form.addEventListener('input', () => taskDrafts.set(draftKey, {status: status.value, assignee: assignee.input.value, due: due.input.value, priority:priority.value, linked_entities:(links.input.value.split('\n').filter(line=>line.trim()).map(line=>{const split=line.indexOf(':');return {kind:line.slice(0,split),id:line.slice(split+1).trim()};}))}));
    const editor = dialog('Изменить подтверждённую задачу', form, async () => {
      const linked_entities = links.input.value.split('\n').map(line=>line.trim()).filter(Boolean).map(line=>{
        const split=line.indexOf(':'); if (split<1) throw new Error('Связь должна иметь формат тип:ID.');
        return {kind:line.slice(0,split),id:line.slice(split+1).trim()};
      });
      const values = ownStatusOnly ? {status:status.value} : { status: status.value, assignee: assignee.input.value.trim() || null, due: due.input.value || null, priority:priority.value, linked_entities };
      const changes = Object.fromEntries(Object.entries(values).filter(([field, value]) => JSON.stringify(value) !== JSON.stringify(task[field] ?? (field==='linked_entities' ? [] : field==='priority' ? 'normal' : null))));
      if (!Object.keys(changes).length) throw new Error('Изменений нет. Измените статус, исполнителя или срок перед предпросмотром.');
      const result = await request(`/tasks/${task.id}/preview`, { method: 'POST', body: { changes } });
      editor.close();
      // Wait for the editor close event before opening the next modal.
      editor.addEventListener('close', () => {
        if (generation !== viewGeneration || !state.user) return;
        const content = node('div'); content.append(node('p', '', result.preview.text));
        const names = { status: 'Статус', assignee: 'Ответственный', due: 'Срок', priority:'Приоритет', linked_entities:'Связи' };
        const statuses = { open: 'Открыта', in_progress: 'В работе', done: 'Готова', blocked:'Заблокирована', cancelled:'Отменена', low:'Низкий', normal:'Обычный', high:'Высокий', urgent:'Срочный' };
        for (const [name, label] of Object.entries(names)) content.append(node('p', '', `${label}: ${Array.isArray(result.preview.before[name]) ? JSON.stringify(result.preview.before[name]) : statuses[result.preview.before[name]] || result.preview.before[name] || 'Не указан'} → ${Array.isArray(result.preview.after[name]) ? JSON.stringify(result.preview.after[name]) : statuses[result.preview.after[name]] || result.preview.after[name] || 'Не указан'}`));
        if (!Object.hasOwn(changes, 'due') && task.due_text) content.append(node('p', 'task-meta', `Срок словами сохраняется: ${task.due_text}`));
        const idempotencyKey = key();
        const previewDialog = dialog('Подтвердить изменение задачи', content, async () => {
          const changed = await request(`/tasks/${task.id}/confirm`, { method: 'POST', body: { confirmation_id: result.confirmation_id, idempotency_key: idempotencyKey } });
          const index = collection.findIndex((item) => String(item.id) === String(task.id));
          if (index >= 0) collection[index] = changed.task;
          if (!meetingOnly) state.tasks = collection;
          taskDrafts.delete(draftKey);
          render(); toast('Задача обновлена');
        }, () => cancelConfirmation(result.confirmation_id));
        previewDialog?.addEventListener('close', () => { if (origin?.isConnected) origin.focus(); }, { once: true });
      }, { once: true });
    }, null, 'Предпросмотр');
    form.addEventListener('submit', (event) => event.preventDefault());
  }

  // datetime-local has no offset. Resolve it explicitly in the chosen IANA zone.
  // Ambiguous and nonexistent DST wall times are rejected instead of silently shifted.
  function zonedISO(value, zone) {
    const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
    if (!parts) throw new Error('Укажите дату и время.');
    const target = Date.UTC(...parts.slice(1).map((v, i) => Number(v) - (i === 1 ? 1 : 0)));
    const fmt = new Intl.DateTimeFormat('sv-SE', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    const wall = (ms) => Object.fromEntries(fmt.formatToParts(new Date(ms)).map((p) => [p.type, p.value]));
    const candidates = new Set();
    for (let hours = -36; hours <= 36; hours += 6) {
      const instant = target + hours * 3600000; const p = wall(instant);
      const projected = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute));
      const possible = target - (projected - instant);
      const t = wall(possible);
      if (`${t.year}-${t.month}-${t.day}T${t.hour}:${t.minute}` === value) candidates.add(possible);
    }
    if (candidates.size !== 1) throw new Error('Это время неоднозначно или отсутствует из-за перевода часов. Выберите другое время.');
    return new Date([...candidates][0]).toISOString();
  }

  async function seedCalendar(meetingId,hint) {
    const owner=state.user?.id,current=generation,page=state.page;
    const result=await request('/calendar/participants');
    if(state.user?.id!==owner || generation!==current || state.page!==page)return false;
    const zone=hint.timezone || state.timezone;
    const local=(value)=>{
      if(!value)return '';
      const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(p=>[p.type,p.value]));
      return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
    };
    calendarDrafts.set(`${owner}/${meetingId}`,{zone,start:local(hint.range_start),end:local(hint.range_end),duration:hint.duration_minutes,
      smart:true,weekends:hint.range_start?['Sat','Sun'].includes(new Intl.DateTimeFormat('en-US',{timeZone:zone,weekday:'short'}).format(new Date(hint.range_start))):false,
      participantIds:hint.participant_ids.map(String),directory:result.participants});
    return true;
  }
  return { can, reset, discardForeignDrafts, dialog, planning, seedCalendar, feedback, sourceButton, renderOverview, renderKnowledge, openKnowledge, editTask, controlDecision, loadOverview, zonedISO };
}
