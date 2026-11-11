import { track3UI } from './meetings/track3.js';
import { protocolPayload } from './meetings/protocol.js';

const API = '/api/meet';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  user: null,
  capabilities: [],
  timezone: 'Europe/Minsk',
  epoch: 0,
  authTransition: null,
  users: [],
  meetings: [],
  documents: [],
  tasks: [],
  tasksStatus: 'idle',
  tasksError: '',
  meetingData: null,
  page: 'meetings',
  tab: 'prep',
  showCreateMeeting: false,
  searchQuery: '',
  searchResults: [],
  searchStatus: 'idle',
  searchError: '',
  transcriptDrafts: Object.create(null),
  protocolDrafts: Object.create(null),
  protocolSelection: new Set(),
  voiceDrafts: Object.create(null),
  voiceCapture: null,
  nextAgenda: null,
};

const dirtyFields = new Map();
const busyButtons = new WeakSet();
const pendingOperations = new Set();
let sourceSequence = 0;
let meetingSequence = 0;
let searchSequence = 0;
const ui = track3UI({ node, makeButton, makeInput, makeTextarea, makeSelect, request, runAction, state,
  dateLabel, render, openMeeting, openSource, showNotice, toast, refreshMeeting, markSaved, draftCheckpoint,
  navigate: setPage });

function operation(button, key) {
  key = `${state.epoch}:${key}`;
  button.dataset.operation = key;
  button.dataset.idleLabel = button.textContent;
  if (pendingOperations.has(key)) {
    button.disabled = true; button.textContent = 'Выполняется…'; button.setAttribute('aria-busy', 'true');
  }
  return button;
}

function permit(control, capability) {
  control.dataset.capability = capability;
  control.hidden = !ui.can(capability);
  return control;
}

function draftKey(control) {
  if (control.dataset.draftKey) return control.dataset.draftKey;
  if (!state.user || control.type === 'password' || control.type === 'file' || control.type === 'checkbox') return null;
  const label = control.closest('label, .speaker-map-row')?.querySelector('.field-label, .speaker-label')?.textContent;
  if (!label) return null;
  const itemId = control.closest('[data-item-id]')?.dataset.itemId || control.closest('[data-utterance-id]')?.dataset.utteranceId || '';
  const key = [state.user.id, state.page, state.meetingData?.meeting?.id || '', state.tab, itemId, label, control.tagName].join('|');
  control.dataset.draftKey = key;
  return key;
}

function restoreDrafts(root = document) {
  for (const control of $$('input, textarea, select', root)) {
    const key = draftKey(control);
    if (key && dirtyFields.has(key)) {
      control.value = dirtyFields.get(key);
      if (control.closest('.protocol-item') || (control.closest('.speaker-map-row') && control.tagName === 'SELECT')) control.dispatchEvent(new Event(control.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    }
  }
}

// A response may acknowledge an older value while the user is already typing a new one.
function draftCheckpoint(root) {
  const sent = new Map($$('input, textarea, select', root).map((control) => [draftKey(control), control.value]));
  return () => {
    for (const [key, value] of sent) if (key && dirtyFields.get(key) === value) dirtyFields.delete(key);
  };
}

function markSaved(root) {
  for (const control of $$('input, textarea, select', root || $('#app'))) {
    const key = draftKey(control);
    if (key) dirtyFields.delete(key);
  }
}

function closeSource() {
  sourceSequence++;
  const panel = $('#source-panel');
  if (panel.open) panel.close();
  panel.hidden = true;
  $('#source-content').replaceChildren();
  $('#source-title').textContent = 'Цитата';
}

function clearIdentity({ keepDrafts = false } = {}) {
  state.epoch++;
  meetingSequence++; searchSequence++;
  if (state.voiceCapture) {
    state.voiceCapture.cancelled = true;
    state.voiceCapture.stream.getTracks().forEach((track) => track.stop());
    void stopVoiceCapture();
  }
  state.user = null;
  state.capabilities = [];
  for (const name of ['users', 'meetings', 'documents', 'tasks', 'searchResults']) state[name] = [];
  state.meetingData = state.nextAgenda = null;
  state.tasksStatus = 'idle'; state.tasksError = '';
  state.transcriptDrafts = Object.create(null);
  state.protocolDrafts = Object.create(null);
  state.protocolSelection = new Set();
  state.voiceDrafts = Object.create(null);
  state.searchQuery = ''; state.searchStatus = 'idle'; state.searchError = '';
  state.showCreateMeeting = false;
  state.page = 'meetings';
  closeSource(); ui.reset({ keepDrafts });
  clearNotice(); $('#toast').textContent = '';
  if (!keepDrafts) dirtyFields.clear();
}

function acceptIdentity(me) {
  if (state.user && String(state.user.id) !== String(me.user.id)) clearIdentity();
  state.user = me.user;
  state.capabilities = me.capabilities || me.user.capabilities || [];
  ui.discardForeignDrafts(state.user.id);
  state.timezone = me.timezone || 'Europe/Minsk';
  // In-memory drafts can only be restored to the same authenticated identity.
  for (const key of dirtyFields.keys()) if (!key.startsWith(`${state.user.id}|`)) dirtyFields.delete(key);
}

class ApiError extends Error {
  constructor(message, status, code) {
    super(message || 'Не удалось выполнить запрос.');
    this.name = 'ApiError';
    this.status = status;
    this.code = code || '';
  }
}

function node(tag, className, value) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (value !== undefined && value !== null) item.textContent = String(value);
  return item;
}

function add(parent, ...children) {
  for (const child of children) if (child) parent.append(child);
  return parent;
}

function textBlock(tag, value, className = '') {
  return node(tag, className, value ?? '');
}

function makeButton(label, onClick, className = 'secondary-button', type = 'button') {
  const button = node('button', className, label);
  button.type = type;
  if (onClick) button.addEventListener('click', onClick);
  return button;
}

function makeInput({ label, type = 'text', value = '', placeholder = '', required = false, name = '', className = '' } = {}) {
  const wrap = node('label', `meeting-field ${className}`.trim());
  if (label) wrap.append(node('span', 'field-label', label));
  const input = node('input', '');
  input.type = type;
  input.value = value ?? '';
  if (placeholder) input.placeholder = placeholder;
  if (required) input.required = true;
  if (name) input.name = name;
  wrap.append(input);
  return { wrap, input };
}

function makeTextarea({ label, value = '', placeholder = '', rows = 4, required = false, className = '' } = {}) {
  const wrap = node('label', `meeting-field ${className}`.trim());
  if (label) wrap.append(node('span', 'field-label', label));
  const area = node('textarea', '');
  area.value = value ?? '';
  area.rows = rows;
  if (placeholder) area.placeholder = placeholder;
  if (required) area.required = true;
  wrap.append(area);
  return { wrap, input: area };
}

function makeSelect(options, selected = '') {
  const select = node('select', '');
  for (const option of options) {
    const item = node('option', '', option.label);
    item.value = option.value;
    item.selected = String(option.value) === String(selected);
    select.append(item);
  }
  return select;
}

async function request(path, { method = 'GET', body, headers = {} } = {}) {
  const epoch = state.epoch;
  const requestHeaders = { ...headers };
  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    requestHeaders['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  let response;
  try { response = await fetch(path.startsWith('/api/') ? path : `${API}${path}`, {
    method,
    headers: requestHeaders,
    body: payload,
    credentials: 'same-origin',
  }); } catch {
    throw new ApiError('Не удалось связаться с сервером. Проверьте соединение и повторите.', 0, epoch === state.epoch ? 'network_error' : 'stale_session');
  }
  let data = null;
  try {
    data = response.status === 204 ? null : await response.json();
  } catch {
    data = null;
  }
  if (epoch !== state.epoch) throw new ApiError('Сессия изменилась. Повторите действие после входа.', 0, 'stale_session');
  if (!response.ok) {
    if (response.status === 401 && state.user) {
      clearIdentity({ keepDrafts: true }); render();
      showNotice('Сессия завершилась. Войдите снова. Несохранённый ввод сохранён в памяти вкладки только для вашего профиля.');
    } else if (response.status === 403 && state.user) {
      closeSource(); ui.reset({ keepDrafts: true });
      showNotice('Права изменились. Несохранённый ввод сохранён в памяти вкладки.');
      void request('/me').then((me) => { acceptIdentity(me); render(); }).catch(() => {});
    }
    const detail = Array.isArray(data?.detail) ? data.detail.map((item) => `${(item.loc || []).filter((part) => part !== 'body').join('.')}: ${item.msg || 'Некорректное значение'}`).join('; ') : data?.detail;
    throw new ApiError(typeof detail === 'string' ? detail : `Ошибка запроса (${response.status}).`, response.status, data?.code);
  }
  return data;
}

function clearNotice() {
  const notice = $('#notice');
  notice.replaceChildren();
  notice.hidden = true;
}

function showNotice(message, retry) {
  const notice = $('#notice');
  notice.replaceChildren();
  notice.hidden = false;
  notice.className = 'meetings-notice';
  notice.append(node('p', '', message));
  if (retry) notice.append(makeButton('Повторить', () => void retry(), 'retry-button'));
}

function toast(message) {
  const target = $('#toast');
  target.textContent = message;
  target.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => target.classList.remove('show'), 3200);
}

function isModelError(error) {
  return error?.status === 503 && String(error.code || '').startsWith('model_');
}

async function runAction(button, task, { model = false, label = 'Выполняется…' } = {}) {
  const operationKey = button?.dataset.operation;
  if ((button && busyButtons.has(button)) || (operationKey && pendingOperations.has(operationKey))) return false;
  if (operationKey) {
    pendingOperations.add(operationKey);
    for (const group of $$('[data-operation-group]')) if (group.dataset.operationGroup === operationKey) group.disabled = true;
  }
  if (button) busyButtons.add(button);
  const epoch = state.epoch;
  const oldLabel = button?.textContent;
  if (button) {
    button.disabled = true;
    button.classList.add('is-busy');
    button.textContent = label;
    button.setAttribute('aria-busy', 'true');
  }
  clearNotice();
  try {
    await task();
    return true;
  } catch (error) {
    if (error?.code === 'stale_session' || epoch !== state.epoch) return false;
    const message = error?.status === 403 ? 'Доступ запрещён: права изменились. Черновик сохранён в памяти вкладки.' : error?.message || 'Не удалось выполнить действие.';
    if (model && isModelError(error)) {
      showNotice(`${message} Данные встречи сохранены. Можно повторить попытку.`, () => runAction(button, task, { model, label }));
    } else {
      showNotice(message, (error?.status >= 500 || error?.code === 'network_error') ? () => runAction(button, task, { model, label }) : undefined);
    }
    return false;
  } finally {
    if (operationKey) {
      pendingOperations.delete(operationKey);
      for (const group of $$('[data-operation-group]')) if (group.dataset.operationGroup === operationKey) group.disabled = false;
      for (const current of $$('[data-operation]')) if (current.dataset.operation === operationKey) {
        current.disabled = false; current.textContent = current.dataset.idleLabel; current.removeAttribute('aria-busy');
      }
    }
    if (button) {
      busyButtons.delete(button);
      button.disabled = false;
      button.classList.remove('is-busy');
      button.removeAttribute('aria-busy');
      if (oldLabel !== undefined) button.textContent = oldLabel;
    }
  }
}

function dateLabel(value, timeZone = 'Europe/Moscow') {
  if (!value) return 'Дата не указана';
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(String(value));
  const date = dateOnly ? new Date(`${value}T12:00:00Z`) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('ru-RU', dateOnly ? { dateStyle: 'medium', timeZone: 'UTC' } : { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(date);
}

function fileKind(documentItem) {
  return String(documentItem?.kind || documentItem?.filename?.split('.').pop() || 'файл').toUpperCase();
}

function downloadLink(documentItem) {
  const link = node('a', 'download-link', `Скачать: ${documentItem.filename || documentItem.title || 'документ'}`);
  link.href = `${API}/documents/${encodeURIComponent(documentItem.id)}/download`;
  link.setAttribute('download', documentItem.filename || '');
  return link;
}

function updateAccount() {
  const account = $('#account');
  account.replaceChildren();
  if (!state.user) return;
  account.append(node('span', 'account-name', state.user.name || state.user.login));
  account.append(makeButton('Выйти', () => void logout(), 'logout-button'));
}

function setPage(page) {
  if (!state.user) { render(); return; }
  meetingSequence++; searchSequence++;
  if (state.voiceCapture?.recording) void stopVoiceCapture();
  state.page = page;
  render();
  if (page === 'overview') void ui.loadOverview();
  if (dirtyFields.size) toast('Несохранённый ввод остаётся в памяти этой вкладки.');
}

function updateNavigation() {
  for (const button of $$('.meetings-nav [data-action]')) {
    button.disabled = !state.user;
    const page = button.dataset.action.replace('show-', '');
    const active = page === state.page || (page === 'meetings' && state.page === 'meeting');
    button.classList.toggle('nav-current', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
}

function render() {
  updateAccount();
  updateNavigation();
  const app = $('#app');
  app.replaceChildren();
  if (!state.user) {
    $('#global-search')?.remove();
    renderLogin(app);
    return;
  }
  if (state.page === 'meeting' && state.meetingData) renderMeeting(app);
  else if (state.page === 'overview') ui.renderOverview(app);
  else if (state.page === 'knowledge') ui.renderKnowledge(app);
  else if (state.page === 'tasks') renderTaskBoard(app, state.tasks, false);
  else if (state.page === 'search') renderSearchResults(app);
  else renderMeetings(app);
  renderGlobalSearch();
  restoreDrafts();
}

function renderGlobalSearch() {
  let form = $('#global-search');
  if (!form) {
    form = node('form', 'global-search');
    form.id = 'global-search';
    const input = node('input', '');
    input.type = 'search';
    input.name = 'q';
    input.placeholder = 'Поиск по документам';
    input.setAttribute('aria-label', 'Поиск по документам');
    const button = makeButton('Найти', null, 'search-button', 'submit');
    form.append(input, button);
    $('.meetings-topbar').insertBefore(form, $('#account'));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const query = new FormData(form).get('q').toString().trim();
      if (!query) return;
      void loadSearch(query);
    });
  }
  const field = $('input[name="q"]', form);
  if (field && document.activeElement !== field) field.value = state.searchQuery;
}

function renderLogin(app) {
  const shell = node('section', 'login-card panel');
  shell.append(node('p', 'eyebrow', 'РАБОЧЕЕ ПРОСТРАНСТВО'));
  shell.append(node('h1', '', 'Встречи и решения'));
  shell.append(node('p', 'login-copy', 'Войдите в демо-профиль, чтобы открыть свои встречи и материалы.'));
  const form = node('form', 'login-form');
  const login = makeInput({ label: 'Логин', required: true, name: 'login', placeholder: 'irina или petr' });
  const password = makeInput({ label: 'Пароль', type: 'password', required: true, name: 'password', placeholder: 'Пароль демо-профиля' });
  const submit = makeButton('Войти', null, 'primary-button', 'submit');
  submit.disabled = login.input.disabled = password.input.disabled = Boolean(state.authTransition);
  if (state.authTransition) shell.append(node('p', 'muted-copy', 'Завершаю выход из аккаунта…'));
  form.append(login.wrap, password.wrap, submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (state.authTransition) return;
    const payload = { login: login.input.value.trim(), password: password.input.value };
    await runAction(submit, async () => {
      await request('/login', { method: 'POST', body: payload });
      await loadSignedInData();
      state.page = 'overview';
      clearNotice();
      render();
    });
  });
  shell.append(form);
  const demo = node('div', 'demo-accounts');
  demo.append(node('span', 'field-label', 'Демо-доступ'));
  const irina = makeButton('Ирина · irina / irina-demo', () => {
    login.input.value = 'irina'; password.input.value = 'irina-demo'; login.input.focus();
  }, 'demo-account-button');
  const petr = makeButton('Пётр · petr / petr-demo', () => {
    login.input.value = 'petr'; password.input.value = 'petr-demo'; login.input.focus();
  }, 'demo-account-button');
  irina.disabled = petr.disabled = Boolean(state.authTransition);
  demo.append(irina, petr);
  shell.append(demo);
  app.append(shell);
}

async function loadSignedInData() {
  const me = await request('/me');
  acceptIdentity(me);
  const [users, meetings, documents] = await Promise.all([
    request('/users'), request('/meetings'), request('/documents'),
  ]);
  state.users = users.users || [];
  state.meetings = meetings.meetings || [];
  state.documents = documents.documents || [];
}

async function loginBootstrap() {
  updateNavigation();
  $('#app').textContent = 'Загружаю рабочее пространство…';
  try { await loadSignedInData(); state.page = 'overview'; render(); }
  catch (error) {
    render();
    if (error.status !== 401 && error.code !== 'stale_session') showNotice(error.message, loginBootstrap);
  }
}

async function logout() {
  if (state.authTransition) return;
  state.authTransition = 'logout';
  clearIdentity(); render();
  try { await request('/logout', { method: 'POST' }); }
  catch (error) { if (error.status !== 401) showNotice('Не удалось завершить сессию на сервере. Повторите выход.', logout); }
  finally { state.authTransition = null; render(); }
}

function renderMeetings(app) {
  const intro = node('section', 'meetings-heading');
  const copy = node('div', '');
  copy.append(node('p', 'eyebrow', 'ПЛАНИРОВАНИЕ И ИТОГИ'));
  copy.append(node('h1', '', 'Встречи'));
  copy.append(node('p', 'muted-copy', 'Подготовьте повестку, сохраните материалы и подтвердите решения.'));
  const createToggle = makeButton(state.showCreateMeeting ? 'Скрыть форму' : 'Новая встреча', () => {
    state.showCreateMeeting = !state.showCreateMeeting;
    render();
  }, 'primary-button');
  intro.append(copy, permit(createToggle, 'meetings.create'));
  app.append(intro);
  if (state.showCreateMeeting && ui.can('meetings.create')) app.append(renderCreateMeetingForm());
  const list = node('section', 'meeting-list');
  list.append(node('h2', '', 'Мои встречи'));
  if (!state.meetings.length) {
    list.append(emptyState('Пока нет встреч', 'Создайте первую встречу, чтобы добавить документы и материалы.'));
  } else {
    const cards = node('div', 'meeting-card-grid');
    state.meetings.forEach((meeting) => {
      const card = node('article', 'meeting-card panel');
      card.append(node('span', 'meeting-date-chip', `${dateLabel(meeting.scheduled_at, meeting.timezone || state.timezone)} · ${meeting.timezone || state.timezone}`));
      card.append(node('h3', '', meeting.title || 'Без названия'));
      card.append(node('p', 'meeting-topic', meeting.topic || 'Тема не указана'));
      const participants = node('p', 'meeting-participants', (meeting.participants || []).join(' · ') || 'Участники не указаны');
      card.append(participants);
      const open = makeButton('Открыть встречу', () => void openMeeting(meeting.id), 'text-button');
      card.append(open);
      cards.append(card);
    });
    list.append(cards);
  }
  app.append(list);
}

function emptyState(title, description) {
  const empty = node('div', 'empty-state panel');
  empty.append(node('span', 'empty-symbol', '•'));
  empty.append(node('b', '', title));
  empty.append(node('p', '', description));
  return empty;
}

function renderCreateMeetingForm() {
  const card = node('section', 'panel create-meeting-card');
  card.append(node('h2', '', 'Новая встреча'));
  const form = node('form', 'create-meeting-form');
  const title = makeInput({ label: 'Название', required: true, placeholder: 'Например, запуск продукта' });
  const topic = makeTextarea({ label: 'Тема и цель', rows: 3, placeholder: 'Что нужно обсудить?' });
  const scheduled = makeInput({ label: 'Дата и время', type: 'datetime-local' });
  const timezone = makeInput({ label: 'Часовой пояс IANA', value: state.timezone, required: true });
  const participants = makeTextarea({ label: 'Участники', rows: 3, placeholder: 'По одному имени в строке' });
  form.append(title.wrap, topic.wrap, scheduled.wrap, timezone.wrap, participants.wrap);
  const access = node('fieldset', 'access-users');
  access.append(node('legend', '', 'Кому доступна встреча'));
  state.users.filter((person) => person.id !== state.user?.id).forEach((person) => {
    const label = node('label', 'check-label');
    const checkbox = node('input', '');
    checkbox.type = 'checkbox';
    checkbox.value = person.id;
    label.append(checkbox, node('span', '', person.name || person.login));
    access.append(label);
  });
  form.append(access);
  const submit = makeButton('Создать встречу', null, 'primary-button', 'submit');
  form.append(submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const names = participants.input.value.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean);
    const payload = {
      title: title.input.value.trim(),
      topic: topic.input.value.trim(),
      participants: names,
      access_user_ids: $$('input[type="checkbox"]:checked', access).map((item) => item.value),
    };
    const success = await runAction(submit, async () => {
      if (scheduled.input.value) { payload.scheduled_at = ui.zonedISO(scheduled.input.value, timezone.input.value); payload.timezone = timezone.input.value; }
      const result = await request('/meetings', { method: 'POST', body: payload });
      markSaved(form);
      state.showCreateMeeting = false;
      await refreshMeetings();
      await openMeeting(result.meeting.id);
    });
    if (success) toast('Встреча создана');
  });
  card.append(form);
  return card;
}

async function refreshMeetings() {
  const result = await request('/meetings');
  state.meetings = result.meetings || [];
}

async function openMeeting(id, tab = 'prep') {
  const sequence = ++meetingSequence;
  if (state.voiceCapture?.recording) await stopVoiceCapture();
  clearNotice();
  try {
    const detail = await request(`/meetings/${encodeURIComponent(id)}`);
    if (sequence !== meetingSequence) return;
    state.meetingData = detail;
    state.page = 'meeting';
    state.tab = tab;
    state.nextAgenda = null;
    render();
  } catch (error) {
    if (error.code !== 'stale_session') showNotice(error.message, () => openMeeting(id, tab));
  }
}

function renderMeeting(app) {
  const data = state.meetingData;
  const meeting = data.meeting || {};
  const head = node('section', 'meeting-detail-heading');
  head.append(makeButton('← Все встречи', () => setPage('meetings'), 'back-button'));
  const copy = node('div', 'meeting-detail-copy');
  copy.append(node('p', 'eyebrow', `${dateLabel(meeting.scheduled_at, meeting.timezone || state.timezone)} · ${meeting.timezone || state.timezone}`));
  copy.append(node('h1', '', meeting.title || 'Встреча'));
  copy.append(node('p', 'muted-copy', meeting.topic || 'Тема не указана'));
  head.append(copy);
  app.append(head);
  const tabs = node('nav', 'meeting-tabs');
  const tabList = [
    ['prep', '1 · Подготовка'], ['materials', '2 · Материалы'], ['protocol', '3 · Протокол'], ['tasks', '4 · Задачи'],
  ];
  for (const [key, label] of tabList) {
    const tab = makeButton(label, () => {
      if (state.voiceCapture?.recording && key !== 'materials') void stopVoiceCapture();
      state.tab = key;
      tabs.querySelectorAll('.meeting-tab').forEach((other) => {
        const active = other === tab;
        other.classList.toggle('active', active);
        other.setAttribute('aria-current', active ? 'step' : 'false');
      });
      renderMeetingContent();
    }, key === state.tab ? 'meeting-tab active' : 'meeting-tab');
    tab.setAttribute('aria-current', key === state.tab ? 'step' : 'false');
    tabs.append(tab);
  }
  app.append(tabs);
  const content = node('section', 'meeting-tab-content');
  content.id = 'meeting-content';
  app.append(content);
  renderMeetingContent();
}

function renderMeetingContent() {
  const target = $('#meeting-content');
  if (!target || !state.meetingData) return;
  target.replaceChildren();
  if (state.tab === 'prep') renderPreparation(target);
  else if (state.tab === 'materials') renderMaterials(target);
  else if (state.tab === 'protocol') renderProtocol(target);
  else renderMeetingTasks(target);
  restoreDrafts(target);
}

function renderPreparation(target) {
  const data = state.meetingData;
  const meeting = data.meeting;
  ui.planning(target);
  const left = node('div', 'prep-layout');
  const docs = node('section', 'panel attached-documents');
  docs.append(node('h2', '', 'Материалы встречи'));
  docs.append(node('p', 'muted-copy', 'Прикрепите документ или выберите уже доступный файл.'));
  const upload = node('form', 'upload-form');
  const fileLabel = node('label', 'file-picker');
  fileLabel.append(node('span', 'field-label', 'Загрузить TXT, DOCX или PDF'));
  const file = node('input', '');
  file.type = 'file';
  file.accept = '.txt,.docx,.pdf,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  file.required = true;
  fileLabel.append(file);
  upload.append(fileLabel);
  const submit = makeButton('Загрузить и прикрепить', null, 'secondary-button', 'submit');
  upload.append(submit);
  upload.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!file.files?.[0]) return;
    const payload = new FormData();
    payload.append('file', file.files[0]);
    payload.append('meeting_id', meeting.id);
    const shareIds = (meeting.access_user_ids || []).map(String);
    if (shareIds.length) payload.append('share_with', shareIds.join(','));
    await runAction(submit, async () => {
      const uploaded = await request('/documents', { method: 'POST', body: payload });
      if (uploaded.document) state.documents = [...state.documents.filter((item) => String(item.id) !== String(uploaded.document.id)), uploaded.document];
      await refreshMeeting();
      toast('Документ добавлен');
    });
  });
  docs.append(permit(upload, 'documents.upload'));
  const attach = node('form', 'attach-existing-form');
  const select = makeSelect([
    { value: '', label: 'Выберите доступный документ' },
    ...state.documents.filter((item) => !(data.documents || []).some((attached) => String(attached.id) === String(item.id)))
      .map((item) => ({ value: item.id, label: `${item.title || item.filename} · ${fileKind(item)}` })),
  ]);
  attach.append(select);
  const attachButton = makeButton('Прикрепить файл', null, 'secondary-button', 'submit');
  attach.append(attachButton);
  attach.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!select.value) return;
    await runAction(attachButton, async () => {
      await request(`/meetings/${encodeURIComponent(meeting.id)}/documents`, { method: 'POST', body: { document_id: select.value } });
      await refreshMeeting();
    });
  });
  select.setAttribute('aria-label', 'Прикрепить доступный документ');
  docs.append(permit(attach, 'meetings.edit'));
  if (Number(data.hidden_documents) > 0) {
    docs.append(node('p', 'access-limited-note', `${data.hidden_documents} документов недоступны вам.`));
  }
  const attached = node('div', 'attached-list');
  if (!(data.documents || []).length) attached.append(node('p', 'empty-copy', 'К встрече пока не прикреплены документы.'));
  (data.documents || []).forEach((documentItem) => {
    const row = node('article', 'document-row');
    const copy = node('div', '');
    copy.append(node('span', 'document-kind', fileKind(documentItem)));
    copy.append(node('b', '', documentItem.title || documentItem.filename || 'Документ'));
    copy.append(node('small', '', documentItem.filename || ''));
    row.append(copy, downloadLink(documentItem));
    const detach = makeButton('Убрать', async () => {
      const okay = await runAction(detach, async () => {
        await request(`/meetings/${encodeURIComponent(meeting.id)}/documents/${encodeURIComponent(documentItem.id)}`, { method: 'DELETE' });
        await refreshMeeting();
      });
      if (okay) toast('Документ удалён из встречи');
    }, 'remove-button');
    row.append(permit(detach, 'meetings.edit'));
    attached.append(row);
  });
  docs.append(attached);
  left.append(docs);

  const prep = node('section', 'panel prep-result');
  const heading = node('div', 'section-heading');
  const headingCopy = node('div', '');
  headingCopy.append(node('p', 'eyebrow', 'ПОДГОТОВКА'));
  headingCopy.append(node('h2', '', 'Справка к встрече'));
  const generate = operation(makeButton('Сформировать справку', null, 'primary-button'), `prepare-${meeting.id}`);
  generate.disabled ||= !(data.documents || []).length;
  generate.addEventListener('click', () => void runAction(generate, async () => {
    const result = await request(`/meetings/${encodeURIComponent(meeting.id)}/prepare`, { method: 'POST' });
    data.prep = result.prep;
    if (String(state.meetingData?.meeting?.id) === String(meeting.id)) state.meetingData.prep = result.prep;
    renderMeetingContent();
  }, { model: true }));
  heading.append(headingCopy, permit(generate, 'prep.generate'));
  prep.append(heading);
  const result = data.prep;
  if (!result) prep.append(emptyState('Справки пока нет', (data.documents || []).length ? 'Нажмите «Сформировать справку» — локальная модель соберёт факты со ссылками на фрагменты.' : 'Сначала прикрепите документы, затем сформируйте краткую справку.'));
  else {
    if (result.status === 'insufficient_data') {
      const gaps = node('div', 'gap-state');
      gaps.append(node('b', '', 'Недостаточно данных'));
      gaps.append(node('p', '', 'В документах не нашлось надёжной опоры для части утверждений. Ниже перечислены пробелы.'));
      if ((result.gaps || []).length) {
        const list = node('ul', 'gap-list');
        result.gaps.forEach((item) => list.append(node('li', '', item)));
        gaps.append(list);
      }
      prep.append(gaps);
    }
    renderClaimGroup(prep, 'Краткая справка', result.brief || []);
    renderClaimGroup(prep, 'Предлагаемая повестка', result.agenda || []);
    renderClaimGroup(prep, 'Вопросы', result.questions || []);
    if ((result.gaps || []).length && result.status !== 'insufficient_data') {
      renderStringList(prep, 'Что осталось проверить', result.gaps);
    }
    if (result.generated_at) prep.append(node('p', 'muted-copy generated-meta', `Сформировано ${dateLabel(result.generated_at)}${result.model ? ` · ${result.model}` : ''}`));
  }
  // Open tasks of previous meetings come live from the server (data.followup) even before a briefing exists.
  const followup = result || data.followup;
  if (result || (data.followup?.open_tasks || []).length) {
    const tasks = followup.open_tasks || [];
    prep.append(node('h3', '', 'Открытые задачи предыдущих встреч'));
    if (!tasks.length) prep.append(node('p', 'empty-copy', 'Открытых задач предыдущих встреч нет.'));
    for (const task of tasks) prep.append(renderTaskCard(task, tasks, true));
    for (const q of followup.task_questions || []) {
      prep.append(node('p', '', q.text));
      for (const source of q.sources || []) prep.append(ui.sourceButton({ ...source, id: String(source.id).replace(/^T/, '') }));
    }
    if (result) prep.append(ui.feedback('prep', meeting.id, meeting.id));
  }
  left.append(prep);
  target.append(left);
}

function renderStringList(parent, title, values) {
  const section = node('section', 'claim-group');
  section.append(node('h3', '', title));
  const list = node('ul', 'gap-list');
  values.forEach((value) => list.append(node('li', '', value)));
  section.append(list);
  parent.append(section);
}

function renderClaimGroup(parent, title, claims) {
  const section = node('section', 'claim-group');
  section.append(node('h3', '', title));
  if (!claims.length) section.append(node('p', 'empty-copy', 'Пока нет пунктов.'));
  claims.forEach((claim) => {
    const item = node('article', 'claim-item');
    item.append(node('p', '', claim.text || ''));
    (claim.citations || []).forEach((citation) => item.append(citationButton(citation.fragment_id, citation.quote, 'fragment')));
    section.append(item);
  });
  parent.append(section);
}

async function refreshMeeting(id = state.meetingData?.meeting?.id) {
  if (!id) return;
  const data = await request(`/meetings/${encodeURIComponent(id)}`);
  state.meetings = state.meetings.map((meeting) => String(meeting.id) === String(id) ? data.meeting : meeting);
  if (String(state.meetingData?.meeting?.id) !== String(id)) return;
  state.meetingData = data;
  if (state.page === 'meeting') render();
}

function renderMaterials(target) {
  const data = state.meetingData;
  const meetingId = data.meeting.id;
  const layout = node('div', 'materials-layout');
  const transcript = node('section', 'panel transcript-editor');
  transcript.append(node('p', 'eyebrow', 'ТЕКСТОВАЯ РАСШИФРОВКА'));
  transcript.append(node('h2', '', 'Вставить стенограмму'));
  transcript.append(node('p', 'muted-copy', 'Строки с именем перед двоеточием будут разобраны на отдельные реплики.'));
  const form = node('form', 'transcript-form');
  const editor = makeTextarea({
    label: 'Текст стенограммы',
    value: state.transcriptDrafts[meetingId] || '',
    rows: 8,
    placeholder: 'Ирина: Обсудим план запуска\nАнна: Я подготовлю макет',
    className: 'transcript-textarea',
  });
  editor.input.addEventListener('input', () => { state.transcriptDrafts[meetingId] = editor.input.value; });
  form.append(editor.wrap);
  const save = makeButton('Сохранить стенограмму', null, 'primary-button', 'submit');
  form.append(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const value = editor.input.value.trim();
    if (!value) return;
    await runAction(save, async () => {
      const result = await request(`/meetings/${encodeURIComponent(meetingId)}/transcript`, { method: 'PUT', body: { text: value } });
      data.utterances = result.utterances || [];
      state.transcriptDrafts[meetingId] = '';
      markSaved(form);
      editor.input.value = '';
      renderUtteranceList();
      renderSpeakerMapping();
      toast('Стенограмма сохранена');
    });
  });
  transcript.append(permit(form, 'transcript.edit'));

  const voice = node('section', 'panel voice-capture-panel');
  voice.append(node('p', 'eyebrow', 'ГОЛОСОВОЙ РЕЖИМ'));
  voice.append(node('h2', '', 'Записать встречу'));
  voice.append(node('p', 'muted-copy', 'Речь распознаётся короткими фрагментами. Каждый фрагмент можно исправить перед добавлением.'));
  const voiceState = node('div', 'voice-capture-status');
  voiceState.id = 'voice-capture-status';
  voiceState.textContent = state.voiceCapture?.recording ? 'Идёт запись · фрагменты до 15 секунд'
    : state.voiceCapture ? 'Завершается распознавание фрагментов…' : 'Микрофон выключен';
  voice.append(voiceState);
  const consentLabel = node('label', 'record-consent');
  const consent = node('input', '');
  consent.type = 'checkbox';
  consentLabel.append(consent, node('span', '', 'Я подтвердил(а), что все участники согласны на запись и расшифровку встречи.'));
  consentLabel.hidden = Boolean(state.voiceCapture?.recording);
  voice.append(permit(consentLabel, 'transcript.edit'));
  const voiceButton = makeButton(state.voiceCapture?.recording ? 'Остановить запись' : state.voiceCapture ? 'Распознавание…' : 'Начать запись', null,
    state.voiceCapture?.recording ? 'stop-recording-button' : 'primary-button');
  voiceButton.disabled = Boolean(state.voiceCapture && !state.voiceCapture.recording) || (!state.voiceCapture?.recording && !consent.checked);
  voiceButton.id = 'voice-capture-toggle';
  consent.addEventListener('change', () => { voiceButton.disabled = Boolean(state.voiceCapture && !state.voiceCapture.recording) || !consent.checked; });
  voiceButton.addEventListener('click', () => {
    if (state.voiceCapture?.recording) void stopVoiceCapture();
    else void startVoiceCapture(meetingId, voiceButton);
  });
  voice.append(permit(voiceButton, 'transcript.edit'));
  const disclaimer = node('small', 'voice-note', 'Для записи нужен разрешённый доступ браузера к микрофону.');
  voice.append(disclaimer);
  const drafts = node('div', 'voice-drafts');
  drafts.id = 'voice-drafts';
  voice.append(drafts);
  (state.voiceDrafts[meetingId] || []).forEach((draft) => drafts.append(renderVoiceDraft(draft)));

  const utterances = node('section', 'panel utterances-panel');
  utterances.append(node('div', 'section-heading'));
  const uh = $('.section-heading', utterances);
  uh.append(node('div', '')); 
  $('.section-heading > div', utterances).append(node('p', 'eyebrow', 'СОХРАНЁННЫЕ МАТЕРИАЛЫ'), node('h2', '', 'Реплики'));
  const counter = node('span', 'small-chip', `${(data.utterances || []).length} шт.`);
  counter.id = 'utterance-count';
  uh.append(counter);
  const mapping = node('div', 'speaker-mapping');
  mapping.id = 'speaker-mapping';
  utterances.append(mapping);
  const list = node('div', 'utterance-list');
  list.id = 'utterance-list';
  utterances.append(list);
  layout.append(transcript, voice, utterances);
  target.append(layout);
  renderUtteranceList();
  renderSpeakerMapping();
}

function renderUtteranceList() {
  const list = $('#utterance-list');
  if (!list || !state.meetingData) return;
  list.replaceChildren();
  const data = state.meetingData;
  const utterances = data.utterances || [];
  const counter = $('#utterance-count');
  if (counter) counter.textContent = `${utterances.length} шт.`;
  if (!utterances.length) {
    list.append(node('p', 'empty-copy', 'Пока нет реплик. Вставьте стенограмму или включите запись.'));
    return;
  }
  utterances.forEach((utterance) => {
    const card = node('article', 'utterance-card');
    card.dataset.utteranceId = utterance.id;
    const top = node('div', 'utterance-card-head');
    top.append(node('span', 'speaker-badge', utterance.speaker || utterance.speaker_label || 'Говорящий ?'));
    top.append(node('span', 'utterance-meta', `Реплика ${utterance.idx ?? ''}${utterance.source ? ` · ${utterance.source === 'voice' ? 'голос' : 'текст'}` : ''}`));
    card.append(top);
    const speaker = makeInput({ label: 'Метка говорящего', value: utterance.speaker_label || 'Говорящий ?' });
    const words = makeTextarea({ label: 'Текст реплики', value: utterance.text || '', rows: Math.max(2, Math.min(5, Math.ceil((utterance.text || '').length / 100))) });
    speaker.input.disabled = words.input.disabled = !ui.can('transcript.edit');
    card.append(speaker.wrap, words.wrap);
    if (utterance.edited) card.append(node('small', 'edited-note', `Исходный текст: ${utterance.original_text || ''}`));
    const actions = node('div', 'inline-actions');
    const save = makeButton('Сохранить правку', async () => {
      const success = await runAction(save, async () => {
        const result = await request(`/utterances/${encodeURIComponent(utterance.id)}`, {
          method: 'PATCH', body: { text: words.input.value, speaker_label: speaker.input.value.trim() || 'Говорящий ?' },
        });
        data.utterances = utterances.map((item) => String(item.id) === String(utterance.id) ? result.utterance : item);
        renderUtteranceList();
        renderSpeakerMapping();
      });
      if (success) { markSaved(card); toast('Правка сохранена'); }
    });
    const remove = makeButton('Удалить', async () => {
      const success = await runAction(remove, async () => {
        await request(`/utterances/${encodeURIComponent(utterance.id)}`, { method: 'DELETE' });
        data.utterances = utterances.filter((item) => String(item.id) !== String(utterance.id));
        renderUtteranceList();
        renderSpeakerMapping();
      });
      if (success) toast('Реплика удалена');
    }, 'remove-button');
    actions.append(permit(save, 'transcript.edit'), permit(remove, 'transcript.edit'), citationButton(utterance.id, utterance.text, 'utterance', 'Открыть источник'));
    card.append(actions);
    list.append(card);
  });
}

function renderSpeakerMapping() {
  const target = $('#speaker-mapping');
  if (!target || !state.meetingData) return;
  target.replaceChildren();
  if (!ui.can('transcript.edit')) return;
  const data = state.meetingData;
  const utterances = data.utterances || [];
  const labels = [...new Set(utterances.map((item) => item.speaker_label).filter(Boolean))];
  if (!labels.length) return;
  target.append(node('h3', '', 'Сопоставить говорящих'));
  const meeting = state.meetingData.meeting;
  const map = { ...(meeting.speaker_map || {}) };
  labels.forEach((label) => {
    const row = node('div', 'speaker-map-row');
    row.append(node('span', 'speaker-label', label));
    const options = [
      { value: '', label: 'Выберите участника' },
      ...(meeting.participants || []).map((name) => ({ value: name, label: name })),
      { value: '__custom__', label: 'Другое имя…' },
    ];
    const initial = map[label] && !(meeting.participants || []).includes(map[label]) ? '__custom__' : (map[label] || '');
    const select = makeSelect(options, initial);
    select.setAttribute('aria-label', `Имя для ${label}`);
    const custom = node('input', 'custom-speaker-name');
    custom.placeholder = 'Имя участника';
    custom.setAttribute('aria-label', `Другое имя для ${label}`);
    custom.value = map[label] && !(meeting.participants || []).includes(map[label]) ? map[label] : '';
    custom.hidden = select.value !== '__custom__';
    select.addEventListener('change', () => { custom.hidden = select.value !== '__custom__'; });
    row.append(select, custom);
    target.append(row);
  });
  const save = makeButton('Сохранить сопоставление', async () => {
    const mapping = {};
    $$('.speaker-map-row', target).forEach((row) => {
      const label = $('.speaker-label', row).textContent;
      const select = $('select', row);
      const custom = $('.custom-speaker-name', row);
      const value = select.value === '__custom__' ? custom.value.trim() : select.value;
      if (value) mapping[label] = value;
    });
    const success = await runAction(save, async () => {
      const result = await request(`/meetings/${encodeURIComponent(meeting.id)}/speakers`, { method: 'PUT', body: { speaker_map: mapping } });
      data.meeting = result.meeting;
      data.utterances = result.utterances || [];
      renderUtteranceList();
      renderSpeakerMapping();
    });
    if (success) { markSaved(target); toast('Говорящие сопоставлены'); }
  });
  target.append(permit(save, 'transcript.edit'));
}

function renderVoiceDraft(record) {
  const card = node('article', `voice-draft-card${record.loading ? ' is-loading' : ''}`);
  record.node = card;
  card.dataset.itemId = `voice-${record.id}`;
  const header = node('div', 'voice-draft-head');
  header.append(node('b', '', `Голосовой фрагмент · ${Math.round(record.startMs / 1000)} сек.`));
  header.append(node('span', 'voice-draft-status', record.status || 'Ожидает распознавания'));
  card.append(header);
  const speaker = makeInput({ label: 'Метка говорящего', value: record.speakerLabel || 'Говорящий ?' });
  speaker.input.addEventListener('input', () => { record.speakerLabel = speaker.input.value; });
  const transcript = makeTextarea({ label: 'Распознанный текст', value: record.text || '', rows: 3, placeholder: 'Результат появится здесь. Его можно исправить.' });
  let saveButton = null;
  transcript.input.addEventListener('input', () => {
    record.text = transcript.input.value;
    if (saveButton) saveButton.disabled = Boolean(record.loading) || !record.text.trim();
  });
  card.append(speaker.wrap, transcript.wrap);
  const actions = node('div', 'inline-actions');
  if (!record.transcribed) {
    const retry = makeButton(record.loading ? 'Распознаётся…' : record.error ? 'Повторить' : 'Распознать фрагмент', () => void recognizeVoiceDraft(record), 'secondary-button');
    retry.disabled = Boolean(record.loading);
    actions.append(retry);
  }
  saveButton = makeButton('Добавить в материалы', async () => {
    const success = await runAction(saveButton, async () => {
      const result = await request(`/meetings/${encodeURIComponent(record.meetingId)}/utterances`, {
        method: 'POST',
        body: { text: transcript.input.value.trim(), speaker_label: speaker.input.value.trim() || 'Говорящий ?', source: 'voice', start_ms: record.startMs },
      });
      record.saved = true;
      markSaved(card);
      if (String(state.meetingData?.meeting?.id) === String(record.meetingId)) state.meetingData.utterances = [...(state.meetingData.utterances || []), result.utterance];
      state.voiceDrafts[record.meetingId] = (state.voiceDrafts[record.meetingId] || []).filter((item) => item !== record);
      card.remove();
      renderUtteranceList();
      renderSpeakerMapping();
    });
    if (success) toast('Реплика добавлена');
  }, 'primary-button');
  saveButton.disabled = Boolean(record.loading) || !record.text?.trim();
  actions.append(saveButton);
  if (record.error) card.append(node('p', 'inline-error', record.error));
  card.append(actions);
  return card;
}

function addVoiceDraft(meetingId, blob, startMs) {
  if (!state.user || !ui.can('transcript.edit')) return;
  const record = { id: crypto.randomUUID(), epoch: state.epoch, meetingId, blob, startMs, speakerLabel: 'Говорящий ?', text: '', status: 'Готов к распознаванию', transcribed: false, loading: false };
  state.voiceDrafts[meetingId] ||= [];
  state.voiceDrafts[meetingId].push(record);
  const list = $('#voice-drafts');
  if (list && String(state.meetingData?.meeting?.id) === String(meetingId)) list.prepend(renderVoiceDraft(record));
  return recognizeVoiceDraft(record);
}

async function recognizeVoiceDraft(record) {
  if (record.epoch !== state.epoch || record.loading || record.transcribed) return;
  record.loading = true;
  record.error = '';
  record.status = 'Распознаётся…';
  if (record.node) {
    const previous = record.node;
    const newNode = renderVoiceDraft(record);
    previous.replaceWith(newNode);
  }
  try {
    const form = new FormData();
    form.append('file', record.blob, 'meeting-voice.wav');
    form.append('mode', 'final');
    form.append('speaker_mode', 'all');
    form.append('meeting_consent', 'true');
    form.append('meeting_id', String(record.meetingId));
    const result = await request('/api/transcribe', { method: 'POST', body: form });
    const segments = Array.isArray(result.segments) ? result.segments.filter((segment) => segment.text?.trim()) : [];
    if (segments.length) {
      const drafts = state.voiceDrafts[record.meetingId] || [];
      const index = drafts.indexOf(record);
      const replacements = segments.map((segment) => ({
        id: crypto.randomUUID(), epoch: record.epoch, meetingId: record.meetingId, blob: record.blob,
        startMs: record.startMs + (Number(segment.start_ms) || 0), speakerLabel: segment.speaker_label || 'Говорящий ?',
        text: segment.text.trim(), status: 'Распознано · проверьте перед сохранением', transcribed: true, loading: false,
      }));
      drafts.splice(Math.max(0, index), index < 0 ? 0 : 1, ...replacements);
      const list = $('#voice-drafts');
      if (list && String(state.meetingData?.meeting?.id) === String(record.meetingId)) {
        record.node?.remove();
        [...replacements].reverse().forEach((item) => list.prepend(renderVoiceDraft(item)));
      }
      return;
    }
    record.text = String(result.raw_text || result.text || '').trim();
    record.transcribed = Boolean(record.text);
    record.status = record.text ? 'Распознано · проверьте перед сохранением' : 'Речь не распознана';
    if (!record.text) record.error = 'Попробуйте записать фрагмент ещё раз или добавьте текст вручную.';
  } catch (error) {
    record.status = 'Не удалось распознать';
    record.error = isModelError(error) ? `${error.message} Запись сохранена в браузере; можно повторить.` : error.message;
  } finally {
    record.loading = false;
    if (record.node?.isConnected) {
      const previous = record.node;
      const replacement = renderVoiceDraft(record);
      previous.replaceWith(replacement);
    }
  }
}

async function startVoiceCapture(meetingId, button) {
  const epoch = state.epoch;
  if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined') {
    showNotice('Этот браузер не поддерживает запись микрофона через AudioWorklet.');
    return;
  }
  const started = await runAction(button, async () => {
    let stream;
    let context;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      context = new AudioContext();
      await context.audioWorklet.addModule('/static/pcm-capture-worklet.js');
      if (epoch !== state.epoch) throw new ApiError('Сессия изменилась.', 0, 'stale_session');
      const source = context.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(context, 'callwise-pcm');
      const gain = context.createGain();
      gain.gain.value = 0;
      source.connect(worklet);
      worklet.connect(gain);
      gain.connect(context.destination);
      const capture = {
        meetingId, epoch, stream, context, source, worklet, gain, recording: true,
        frames: [], sampleCount: 0, sentSamples: 0, queue: Promise.resolve(), flushResolve: null,
      };
      worklet.port.onmessage = ({ data }) => {
        if (data === 'flushed') { capture.flushResolve?.(); capture.flushResolve = null; return; }
        if (data instanceof Float32Array) acceptVoiceFrame(capture, data);
      };
      worklet.onprocessorerror = () => {
        showNotice('Запись прервалась. Уже распознанные фрагменты сохранены.');
        void stopVoiceCapture();
      };
      state.voiceCapture = capture;
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop());
      await context?.close().catch(() => {});
      throw error;
    }
  });
  if (started) {
    const status = $('#voice-capture-status');
    if (status) status.textContent = 'Идёт запись · фрагменты до 15 секунд';
    const control = $('#voice-capture-toggle');
    if (control) { control.textContent = 'Остановить запись'; control.className = 'stop-recording-button'; }
    toast('Запись началась');
  }
}

function acceptVoiceFrame(capture, frame) {
  if (capture.closed || capture.cancelled || capture.epoch !== state.epoch) return;
  capture.frames.push(frame);
  capture.sampleCount += frame.length;
  const chunkSize = 16000 * 15;
  while (capture.sampleCount >= chunkSize) {
    const frames = takeVoiceSamples(capture, chunkSize);
    const startMs = Math.round(capture.sentSamples * 1000 / 16000);
    capture.sentSamples += chunkSize;
    queueVoiceTranscription(capture, frames, startMs);
  }
}

function takeVoiceSamples(capture, count) {
  const result = [];
  let remaining = count;
  while (remaining > 0 && capture.frames.length) {
    const frame = capture.frames[0];
    if (frame.length <= remaining) {
      result.push(capture.frames.shift());
      capture.sampleCount -= frame.length;
      remaining -= frame.length;
    } else {
      result.push(frame.slice(0, remaining));
      capture.frames[0] = frame.slice(remaining);
      capture.sampleCount -= remaining;
      remaining = 0;
    }
  }
  return result;
}

function queueVoiceTranscription(capture, frames, startMs) {
  const wav = window.CallwiseSTT?.wavPCM(frames);
  if (!wav) {
    showNotice('Не удалось собрать WAV-фрагмент записи.');
    return;
  }
  capture.queue = capture.queue.then(() => {
    if (capture.cancelled || capture.epoch !== state.epoch || (!capture.recording && !frames.length)) return;
    return addVoiceDraft(capture.meetingId, wav, startMs);
  });
}

async function stopVoiceCapture() {
  const capture = state.voiceCapture;
  if (!capture) return;
  if (capture.stopping) return capture.stopping;
  capture.recording = false;
  capture.stopping = (async () => {
  const status = $('#voice-capture-status');
  if (status) status.textContent = 'Завершение последнего фрагмента…';
  const control = $('#voice-capture-toggle');
  if (control) { control.disabled = true; control.textContent = 'Завершение…'; }
  await new Promise((resolve) => {
    capture.flushResolve = resolve;
    try { capture.worklet.port.postMessage('flush'); } catch { resolve(); }
    setTimeout(resolve, 1800);
  });
  capture.closed = true;
  if (capture.sampleCount > 0) {
    const frames = takeVoiceSamples(capture, capture.sampleCount);
    const startMs = Math.round(capture.sentSamples * 1000 / 16000);
    capture.sentSamples += frames.reduce((sum, frame) => sum + frame.length, 0);
    queueVoiceTranscription(capture, frames, startMs);
  }
  try { capture.source.disconnect(); capture.worklet.disconnect(); capture.gain.disconnect(); } catch { /* nodes may already be stopped */ }
  capture.stream.getTracks().forEach((track) => track.stop());
  await capture.context.close().catch(() => {});
  await capture.queue;
  if (state.voiceCapture === capture) state.voiceCapture = null;
  if (status) status.textContent = 'Микрофон выключен';
  if (control) { control.disabled = false; control.textContent = 'Начать запись'; control.className = 'primary-button'; }
  if (capture.epoch === state.epoch) toast('Запись остановлена');
  })();
  return capture.stopping;
}

function citationButton(id, quote, kind = 'fragment', label = '') {
  const excerpt = String(quote || 'Открыть источник');
  const button = makeButton(label || `«${excerpt.length > 92 ? `${excerpt.slice(0, 89)}…` : excerpt}»`, () => void openSource(kind, id, quote), 'citation-chip');
  button.title = 'Открыть источник цитаты';
  return button;
}

function appendHighlighted(parent, fullText, quote) {
  const text = String(fullText || '');
  const target = String(quote || '').trim();
  const start = target ? text.toLocaleLowerCase().indexOf(target.toLocaleLowerCase()) : -1;
  if (start < 0) {
    parent.append(node('p', 'source-full-text', text || 'Текст источника отсутствует.'));
    return;
  }
  const before = text.slice(0, start);
  const matched = text.slice(start, start + target.length);
  const after = text.slice(start + target.length);
  const paragraph = node('p', 'source-full-text');
  paragraph.append(document.createTextNode(before));
  const mark = node('mark', '', matched);
  paragraph.append(mark, document.createTextNode(after));
  parent.append(paragraph);
}

async function openSource(kind, id, quote, source = {}) {
  const panel = $('#source-panel');
  const content = $('#source-content');
  const title = $('#source-title');
  panel.hidden = false;
  if (!panel.open) panel.showModal();
  const epoch = state.epoch;
  const sequence = ++sourceSequence;
  content.replaceChildren(node('p', 'muted-copy', 'Загружаю источник…'));
  try {
    if (kind === 'fragment') {
      const result = await request(`/fragments/${encodeURIComponent(id)}`);
      if (!panel.open || sequence !== sourceSequence) return;
      const fragment = result.fragment;
      title.textContent = fragment.document_title || 'Фрагмент документа';
      content.replaceChildren();
      content.append(node('p', 'task-meta', `Дата источника (загрузка документа): ${dateLabel(source.source_at || fragment.source_at || state.documents.find((doc) => String(doc.id) === String(fragment.document_id))?.created_at || fragment.created_at)}`));
      content.append(node('p', 'source-location', fragment.location || `Фрагмент ${fragment.idx ?? ''}`));
      appendHighlighted(content, fragment.text, quote);
      content.append(downloadLink({ id: fragment.document_id, filename: fragment.document_title || 'Документ' }));
    } else if (kind === 'utterance') {
      const result = await request(`/utterances/${encodeURIComponent(id)}`);
      if (!panel.open || sequence !== sourceSequence) return;
      const utterance = result.utterance;
      title.textContent = result.meeting_title || 'Реплика встречи';
      content.replaceChildren();
      content.append(node('p', 'source-location', `${utterance.speaker || utterance.speaker_label || 'Говорящий ?'} · реплика ${utterance.idx ?? ''}`));
      appendHighlighted(content, utterance.text, quote);
      const meeting = String(utterance.meeting_id) === String(state.meetingData?.meeting?.id)
        ? state.meetingData
        : await request(`/meetings/${encodeURIComponent(utterance.meeting_id)}`).catch(() => null);
      if (!panel.open || sequence !== sourceSequence) return;
      content.prepend(node('p', 'task-meta', source.source_at ? `Дата источника: ${dateLabel(source.source_at)}` : `Дата встречи: ${dateLabel(meeting?.meeting?.scheduled_at)}`));
      if ((meeting?.documents || []).length) {
        content.append(node('h3', '', 'Документы встречи'));
        (meeting.documents || []).forEach((documentItem) => content.append(downloadLink(documentItem)));
      }
    } else {
      const result = await request(`/sources/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
      if (!panel.open || sequence !== sourceSequence) return;
      title.textContent = result.source?.title || 'Источник';
      content.replaceChildren(node('p', 'task-meta', `Дата источника: ${dateLabel(result.source?.source_at)}`));
      const data = result.data;
      const tasks = data?.tasks || (data?.text ? [data] : []);
      for (const task of tasks) {
        const row = node('article', 'claim-item');
        row.append(node('p', '', task.text), node('p', 'task-meta', `Ответственный: ${task.assignee || 'Не назван'} · Срок: ${dateLabel(task.due)}`));
        if (task.meeting_id) row.append(makeButton('Открыть задачу во встрече', () => { closeSource(); void openMeeting(task.meeting_id, 'tasks'); }, 'task-meeting-link'));
        content.append(row);
      }
      const labels = { numerator: 'Числитель', denominator: 'Знаменатель', completed_orders: 'Завершённые заказы', on_time_orders: 'Заказы в срок', produced_units: 'Произведено единиц', defective_units: 'Бракованных единиц', occupied_capacity: 'Занятая мощность', available_capacity: 'Доступная мощность' };
      const snapshots = data?.snapshots || [data];
      for (const snapshot of [data, ...snapshots.filter((item) => item !== data)]) {
        if (!snapshot) continue;
        if (snapshot.source_id) content.append(node('h3', '', `Снимок ${snapshot.source_id}`));
        if (snapshot.period_start) content.append(node('p', 'task-meta', `Период: ${dateLabel(snapshot.period_start)} — ${dateLabel(snapshot.period_end)}`));
        if (snapshot.as_of) content.append(node('p', 'task-meta', `Актуальность: ${dateLabel(snapshot.as_of)}`));
        for (const [key, label] of Object.entries(labels)) if (Object.hasOwn(snapshot, key)) content.append(node('p', '', `${label}: ${snapshot[key] ?? 'Нет данных'}`));
      }
    }
  } catch (error) {
    if (state.epoch === epoch && panel.open && sequence === sourceSequence) content.replaceChildren(node('p', 'inline-error', error.message), makeButton('Повторить', () => void openSource(kind, id, quote, source)));
  }
}

function renderProtocol(target) {
  const data = state.meetingData;
  const protocol = data.protocol;
  const section = node('section', 'panel protocol-panel');
  const heading = node('div', 'section-heading');
  const copy = node('div', '');
  copy.append(node('p', 'eyebrow', 'ПРОВЕРЬТЕ ПЕРЕД ПОДТВЕРЖДЕНИЕМ'));
  copy.append(node('h2', '', 'Черновик протокола'));
  const draft = operation(makeButton(protocol ? 'Обновить черновик' : 'Создать черновик', null, 'primary-button'), `protocol-draft-${data.meeting.id}`);
  draft.addEventListener('click', () => void runAction(draft, async () => {
    if (protocol) await saveProtocolEdits(data);
    const result = await request(`/meetings/${encodeURIComponent(data.meeting.id)}/protocol/draft`, { method: 'POST' });
    data.protocol = result.protocol;
    if (String(state.meetingData?.meeting?.id) === String(data.meeting.id)) state.meetingData.protocol = result.protocol;
    for (const item of [...(protocol?.items || []), ...(result.protocol?.items || [])]) { delete state.protocolDrafts[item.id]; state.protocolSelection.delete(String(item.id)); }
    renderMeetingContent();
  }, { model: true }));
  heading.append(copy, permit(draft, 'protocol.edit'));
  section.append(heading);
  if (!protocol) {
    section.append(emptyState('Протокол ещё не подготовлен', 'Сохраните стенограмму, затем создайте черновик протокола.'));
    target.append(section);
    return;
  }
  const body = node('fieldset', 'protocol-body');
  body.dataset.operationGroup = draft.dataset.operation;
  body.disabled = pendingOperations.has(draft.dataset.operation);
  section.append(body);
  if ((protocol.warnings || []).length) renderStringList(body, 'Нужно проверить', protocol.warnings);
  const summary = node('section', 'protocol-group');
  summary.append(node('h3', '', 'Краткое резюме'));
  if (!(protocol.summary || []).length) summary.append(node('p', 'empty-copy', 'Резюме пока нет.'));
  for (const claim of protocol.summary || []) {
    const row = node('article', 'claim-item'); row.append(node('p', '', claim.text));
    if (claim.status !== 'verified') row.append(node('p', 'warning-badge amber', claim.note || 'Требует уточнения'));
    for (const quote of claim.quotes || []) row.append(citationButton(quote.utterance_id, quote.text, 'utterance'));
    summary.append(row);
  }
  body.append(summary, ui.feedback('protocol_summary', data.meeting.id, data.meeting.id));
  const groupOrder = [
    ['decision', 'Решения'], ['proposal', 'Предложения'], ['task', 'Поручения'], ['risk', 'Риски'], ['open_question', 'Открытые вопросы'],
  ];
  for (const [kind, title] of groupOrder) {
    const items = (protocol.items || []).filter((item) => item.kind === kind);
    const group = node('section', 'protocol-group');
    group.append(node('h3', '', title));
    if (!items.length) group.append(node('p', 'empty-copy', 'Нет пунктов.'));
    items.forEach((item) => group.append(renderProtocolItem(item)));
    body.append(group);
  }
  const actions = node('div', 'protocol-actions');
  const save = makeButton('Сохранить правки', async () => {
    const success = await runAction(save, async () => {
      await saveProtocolEdits(data);
      await refreshMeeting(data.meeting.id);
      toast('Правки протокола сохранены');
    });
  });
  actions.append(permit(save, 'protocol.edit'));
  const confirm = makeButton('Подтвердить выбранные', () => {
    const selected = [...new Set($$('.protocol-item-select:checked', section).map((checkbox) => checkbox.value))];
    if (!selected.length) { toast('Выберите поручения для подтверждения'); return; }
    if (!validateProtocolText(protocol.items)) return;
    const preview = node('div');
    preview.append(node('p', '', 'Будут созданы только выбранные поручения:'));
    for (const item of protocol.items.filter((item) => selected.includes(String(item.id)))) {
      const effective = protocolPayload(item, state.protocolDrafts[item.id]);
      preview.append(node('p', '', `${effective.text} · Ответственный: ${effective.assignee || 'Не назван'} · Срок: ${effective.due ? dateLabel(effective.due) : effective.due_text || 'Не назван'}`));
    }
    ui.dialog('Подтвердить выбранные поручения', preview, async () => {
      await saveProtocolEdits(data);
      const result = await request(`/meetings/${encodeURIComponent(data.meeting.id)}/protocol/confirm`, { method: 'POST', body: { item_ids: selected.map(Number) } });
      data.protocol = result.protocol;
      selected.forEach((id) => state.protocolSelection.delete(String(id)));
      data.tasks = [...new Map([...(data.tasks || []), ...(result.created || []), ...(result.already_confirmed || [])].map((task) => [String(task.id), task])).values()];
      renderMeetingContent(); toast('Выбранные поручения подтверждены');
    });
  }, 'primary-button');
  confirm.disabled = !protocol.items?.some((item) => item.kind === 'task' && !item.confirmed);
  actions.append(permit(confirm, 'protocol.confirm'));
  body.append(actions);
  target.append(section);
}

function renderProtocolItem(item) {
  const drafts = state.protocolDrafts;
  const draft = drafts[item.id] || {};
  const card = node('article', `protocol-item ${item.confirmed ? 'confirmed' : ''}`.trim());
  card.dataset.itemId = item.id;
  const head = node('div', 'protocol-item-head');
  const title = node('span', 'protocol-kind', item.kind === 'decision' ? 'Решение' : item.kind === 'proposal' ? 'Предложение' : item.kind === 'task' ? 'Поручение' : item.kind === 'risk' ? 'Риск' : 'Открытый вопрос');
  head.append(title);
  const outcomeValue = protocolPayload(item, draft).outcome;
  const outcomeBadge = node('span', 'outcome-badge');
  function updateOutcome() {
    const value = protocolPayload(item, drafts[item.id]).outcome;
    outcomeBadge.className = `outcome-badge outcome-${value || 'discussed'}`;
    outcomeBadge.textContent = { rejected: 'Отклонено', accepted: 'Принято', discussed: 'Обсуждалось' }[value] || 'Исход не указан';
  }
  if (item.kind === 'proposal') { updateOutcome(); head.append(outcomeBadge); }
  if (item.kind === 'task' && !item.confirmed && ui.can('protocol.confirm')) {
    const selection = node('label', 'protocol-select-label');
    const checkbox = node('input', 'protocol-item-select');
    checkbox.type = 'checkbox'; checkbox.value = item.id;
    checkbox.checked = state.protocolSelection.has(String(item.id));
    checkbox.addEventListener('change', () => { if (checkbox.checked) state.protocolSelection.add(String(item.id)); else state.protocolSelection.delete(String(item.id)); });
    selection.append(checkbox, node('span', '', 'Выбрать'));
    head.append(selection);
  }
  card.append(head);
  const text = makeTextarea({ label: 'Формулировка', value: draft.text ?? item.text ?? '', rows: 2 });
  text.input.required = true; text.input.maxLength = 1000;
  text.input.disabled = Boolean(item.confirmed) || !ui.can('protocol.edit');
  text.input.addEventListener('input', () => { drafts[item.id] = { ...(drafts[item.id] || {}), text: text.input.value }; });
  card.append(text.wrap);
  if (item.kind === 'proposal') {
    const outcomeWrap = node('label', 'meeting-field outcome-field');
    outcomeWrap.append(node('span', 'field-label', 'Исход предложения'));
    const outcomeSelect = makeSelect([
      { value: '', label: 'Не указан' }, { value: 'accepted', label: 'Принято' },
      { value: 'rejected', label: 'Отклонено' }, { value: 'discussed', label: 'Обсуждалось' },
    ], outcomeValue || '');
    outcomeSelect.disabled = Boolean(item.confirmed) || !ui.can('protocol.edit');
    outcomeSelect.addEventListener('change', () => { drafts[item.id] = { ...(drafts[item.id] || {}), outcome: outcomeSelect.value || null }; updateOutcome(); });
    outcomeWrap.append(outcomeSelect);
    card.append(outcomeWrap);
  }
  const fields = node('div', 'protocol-edit-fields');
  const assignee = makeInput({ label: 'Ответственный', value: draft.assignee ?? item.assignee ?? '', placeholder: 'Имя участника' });
  assignee.input.maxLength = 120;
  assignee.input.disabled = Boolean(item.confirmed) || !ui.can('protocol.edit');
  assignee.input.addEventListener('input', () => { drafts[item.id] = { ...(drafts[item.id] || {}), assignee: assignee.input.value }; });
  const due = makeInput({ label: 'Срок', type: 'date', value: draft.due ?? item.due ?? '' });
  due.input.disabled = Boolean(item.confirmed) || !ui.can('protocol.edit');
  due.input.addEventListener('input', () => {
    const next = { ...(drafts[item.id] || {}), due: due.input.value };
    if (due.input.value !== (item.due || '') && (!Object.hasOwn(next, 'dueText') || next.dueText === (item.due_text || ''))) {
      next.dueText = ''; dueText.input.value = '';
    }
    drafts[item.id] = next;
  });
  const dueText = makeInput({ label: 'Срок словами', value: draft.dueText ?? item.due_text ?? '', placeholder: 'Например, в течение недели' });
  dueText.input.maxLength = 120;
  dueText.input.disabled = Boolean(item.confirmed) || !ui.can('protocol.edit');
  dueText.input.addEventListener('input', () => { drafts[item.id] = { ...(drafts[item.id] || {}), dueText: dueText.input.value }; });
  fields.append(assignee.wrap, due.wrap, dueText.wrap);
  if (item.kind === 'task') card.append(fields);
  if (item.kind === 'task') {
    const warning = node('div', 'protocol-warning-badges');
    const deadline = node('p', 'task-meta');
    function updateWarnings() {
      const effective = protocolPayload(item, drafts[item.id]);
      warning.replaceChildren();
      if (!effective.assignee) warning.append(node('span', 'warning-badge red', 'Ответственный не назван'));
      if (!effective.due && !effective.due_text) warning.append(node('span', 'warning-badge amber', 'Срок не назван'));
      deadline.hidden = Boolean(effective.due || !effective.due_text);
      deadline.textContent = effective.due_text ? `Срок: ${effective.due_text} (дата не распознана)` : '';
    }
    card.addEventListener('input', updateWarnings);
    updateWarnings(); card.append(deadline, warning);
  }
  if ((item.quotes || []).length) {
    const quotes = node('div', 'quote-list');
    item.quotes.forEach((quote) => quotes.append(citationButton(quote.utterance_id, quote.text, 'utterance')));
    card.append(quotes);
  }
  card.append(ui.feedback('protocol_item', item.id, state.meetingData.meeting.id));
  if (item.confirmed) {
    card.append(node('p', 'confirmed-stamp', `Подтверждено: ${item.confirmed_by || 'пользователь'} · ${dateLabel(item.confirmed_at)}`));
  }
  return card;
}

function validateProtocolText(items) {
  const invalid = (items || []).find((item) => !protocolPayload(item, state.protocolDrafts[item.id]).text);
  if (!invalid) return true;
  showNotice('Заполните формулировку каждого пункта протокола.');
  const card = $$('.protocol-item').find((element) => element.dataset.itemId === String(invalid.id));
  $('textarea', card || document)?.focus();
  return false;
}

async function saveProtocolEdits(data = state.meetingData) {
  const protocol = data.protocol;
  if (!protocol) return;
  const sentDrafts = new Map((protocol.items || []).map((item) => [item.id, state.protocolDrafts[item.id]]));
  const sentFields = new Map(dirtyFields);
  if (!validateProtocolText(protocol.items)) throw new ApiError('Заполните формулировку каждого пункта протокола.', 422, 'invalid_protocol');
  const items = (protocol.items || []).map((item) => protocolPayload(item, state.protocolDrafts[item.id]));
  const result = await request(`/meetings/${encodeURIComponent(data.meeting.id)}/protocol`, { method: 'PUT', body: { items } });
  data.protocol = result.protocol;
  if (String(state.meetingData?.meeting?.id) === String(data.meeting.id)) state.meetingData.protocol = result.protocol;
  for (const item of protocol.items || []) if (state.protocolDrafts[item.id] === sentDrafts.get(item.id)) delete state.protocolDrafts[item.id];
  for (const key of dirtyFields.keys()) {
    const parts = key.split('|');
    if (parts[1] === 'meeting' && parts[2] === String(data.meeting.id) && parts[3] === 'protocol' && !parts[4].startsWith('feedback-') && dirtyFields.get(key) === sentFields.get(key)) dirtyFields.delete(key);
  }
}

function renderMeetingTasks(target) {
  const tasks = state.meetingData.tasks || [];
  const header = node('section', 'panel meeting-tasks-heading');
  header.append(node('p', 'eyebrow', 'ЗАДАЧИ ПО ВСТРЕЧЕ'));
  header.append(node('h2', '', 'Поручения и следующие шаги'));
  const next = makeButton('Повестка следующей встречи', async () => {
    const meetingId = state.meetingData.meeting.id;
    const success = await runAction(next, async () => {
      const result = await request(`/meetings/${encodeURIComponent(meetingId)}/next-agenda`, { method: 'POST', body: { create_meeting: false } });
      if (String(state.meetingData?.meeting?.id) !== String(meetingId)) return;
      state.nextAgenda = result;
      renderMeetingContent();
    });
  }, 'primary-button');
  header.append(next);
  target.append(header);
  if (state.nextAgenda) renderNextAgenda(target, state.nextAgenda);
  renderTaskBoard(target, tasks, true);
}

function renderNextAgenda(parent, result) {
  const panel = node('section', 'panel next-agenda-panel');
  panel.append(node('h3', '', 'Повестка следующей встречи'));
  if (result.meeting) {
    panel.append(node('p', '', 'Создана встреча со следующей повесткой.'));
    panel.append(makeButton(`Открыть «${result.meeting.title}»`, () => void openMeeting(result.meeting.id), 'text-button'));
  }
  if (!(result.agenda || []).length) panel.append(node('p', 'empty-copy', 'Открытых поручений для повестки нет.'));
  const list = node('ol', 'next-agenda-list');
  (result.agenda || []).forEach((item) => {
    const row = node('li', '');
    row.append(node('b', '', item.text || 'Пункт повестки'));
    const meta = [item.assignee, item.due].filter(Boolean).join(' · ');
    if (meta) row.append(node('small', '', meta));
    list.append(row);
  });
  panel.append(list);
  if (!result.meeting && result.agenda?.length && ui.can('meetings.create')) {
    panel.append(makeButton('Создать следующую встречу', () => {
      const preview = node('div');
      preview.append(node('p', '', 'Будет создана новая встреча с открытыми поручениями:'));
      for (const item of result.agenda) preview.append(node('p', '', item.text));
      const meetingId = state.meetingData.meeting.id;
      ui.dialog('Создать встречу по поручениям', preview, async () => {
        const created = await request(`/meetings/${encodeURIComponent(meetingId)}/next-agenda`, { method: 'POST', body: { create_meeting: true } });
        state.nextAgenda = created; renderMeetingContent();
        const epoch = state.epoch;
        try { await refreshMeetings(); }
        catch (e) {
          if (state.epoch === epoch && state.user) showNotice('Встреча создана. Не удалось обновить список встреч; повторите загрузку.', () => runAction(null, async () => { await refreshMeetings(); render(); }));
        }
      });
    }));
  }
  parent.append(panel);
}

function renderTaskBoard(parent, tasks, meetingOnly) {
  const board = node('section', `task-board ${meetingOnly ? 'meeting-task-board' : ''}`.trim());
  if (!meetingOnly) {
    const intro = node('div', 'meetings-heading');
    const copy = node('div', '');
    copy.append(node('p', 'eyebrow', 'КОНТРОЛЬ ПОРУЧЕНИЙ'));
    copy.append(node('h1', '', 'Задачи'));
    copy.append(node('p', 'muted-copy', 'Задачи собраны из подтверждённых протоколов доступных встреч.'));
    intro.append(copy);
    parent.append(intro);
  }
  if (!meetingOnly && state.tasksStatus === 'loading') {
    board.append(node('p', '', 'Загружаю задачи…')); parent.append(board); return;
  }
  if (!meetingOnly && state.tasksStatus === 'error') {
    board.append(node('p', 'inline-error', state.tasksError), makeButton('Повторить', () => void openTasks())); parent.append(board); return;
  }
  if (!tasks.length) {
    board.append(emptyState('Задач пока нет', 'Подтверждённые поручения появятся здесь.'));
    parent.append(board);
    return;
  }
  const columns = [
    ['open', 'Открытые'], ['in_progress', 'В работе'], ['done', 'Готово'],
  ];
  const grid = node('div', 'task-columns');
  columns.forEach(([status, title]) => {
    const column = node('section', `task-column task-${status}`);
    const group = tasks.filter((task) => task.status === status);
    const heading = node('div', 'task-column-heading');
    heading.append(node('h2', '', title), node('span', 'small-chip', String(group.length)));
    column.append(heading);
    if (!group.length) column.append(node('p', 'empty-copy', 'Нет задач'));
    group.forEach((task) => column.append(renderTaskCard(task, tasks, meetingOnly)));
    grid.append(column);
  });
  board.append(grid);
  parent.append(board);
}

function renderTaskCard(task, collection, meetingOnly) {
  const card = node('article', 'task-card panel');
  card.id = `task-${task.id}`; card.tabIndex = -1;
  card.append(node('p', 'task-card-text', task.text || 'Без описания'));
  if (task.assignee) card.append(node('p', 'task-meta', `Ответственный: ${task.assignee}`));
  else if (task.assignee_status === 'unknown') card.append(node('p', 'warning-badge red', 'Ответственный не назван'));
  if (task.due) card.append(node('p', 'task-meta', `Срок: ${dateLabel(task.due)}`));
  else if (task.due_text) card.append(node('p', 'task-meta', `Срок: ${task.due_text} (дата не распознана)`));
  else if (task.due_status === 'unknown') card.append(node('p', 'warning-badge amber', 'Срок не назван'));
  const link = makeButton(task.meeting_title ? `Встреча: ${task.meeting_title}` : 'Открыть встречу', () => void openMeeting(task.meeting_id), 'task-meeting-link');
  card.append(link);
  if (task.source_quote?.utterance_id) card.append(citationButton(task.source_quote.utterance_id, task.source_quote.text, 'utterance', 'Открыть цитату'));
  if (ui.can('tasks.change')) card.append(makeButton('Изменить задачу', () => ui.editTask(task, collection, meetingOnly)));
  card.append(ui.feedback('task', task.id, task.meeting_id));
  return card;
}

async function openTasks() {
  if (!state.user) { render(); return; }
  if (state.tasksStatus === 'loading') { setPage('tasks'); return; }
  if (state.voiceCapture?.recording) await stopVoiceCapture();
  state.tasks = []; state.tasksStatus = 'loading'; setPage('tasks');
  try {
    const result = await request('/tasks');
    state.tasks = result.tasks || []; state.tasksStatus = 'ready';
    if (state.page === 'tasks') render();
  } catch (error) {
    if (error.code === 'stale_session' || error.status === 401) return;
    state.tasksStatus = 'error'; state.tasksError = error.message;
    if (state.page === 'tasks') render();
  }
}

async function loadSearch(query) {
  clearNotice();
  state.searchQuery = query; state.searchResults = []; state.searchError = ''; state.searchStatus = 'loading';
  setPage('search');
  const sequence = ++searchSequence;
  try {
    const result = await request(`/search?q=${encodeURIComponent(query)}`);
    if (sequence !== searchSequence) return;
    state.searchResults = result.results || []; state.searchStatus = 'ready';
  } catch (error) {
    if (sequence !== searchSequence || error.code === 'stale_session') return;
    state.searchStatus = 'error'; state.searchError = error.message;
  }
  if (state.page === 'search') render();
}

function renderSearchResults(app) {
  const intro = node('section', 'meetings-heading');
  const copy = node('div', '');
  copy.append(node('p', 'eyebrow', 'ПОИСК ПО ДОКУМЕНТАМ'));
  copy.append(node('h1', '', `Результаты: ${state.searchQuery}`));
  copy.append(node('p', 'muted-copy', 'Цитата открывается в исходном фрагменте документа.'));
  intro.append(copy, makeButton('К встречам', () => setPage('meetings'), 'back-button'));
  app.append(intro);
  if (state.searchStatus === 'loading') { app.append(node('p', 'muted-copy', 'Ищу в доступных документах…')); return; }
  if (state.searchStatus === 'error') { app.append(node('p', 'inline-error', state.searchError), makeButton('Повторить поиск', () => void loadSearch(state.searchQuery))); return; }
  if (!state.searchResults.length) {
    app.append(emptyState('Ничего не найдено', 'Попробуйте изменить формулировку запроса.'));
    return;
  }
  const list = node('div', 'search-results');
  state.searchResults.forEach((result) => {
    const card = node('article', 'search-result panel');
    card.append(node('h2', '', result.document_title || result.title || 'Документ'));
    card.append(node('p', 'source-location', result.location || 'Фрагмент документа'));
    card.append(node('p', '', result.snippet || result.text || ''));
    card.append(citationButton(result.id, result.snippet || result.text, 'fragment', 'Открыть фрагмент'));
    list.append(card);
  });
  app.append(list);
}

$$('[data-action="show-meetings"]').forEach((button) => button.addEventListener('click', () => setPage('meetings')));
$$('[data-action="show-tasks"]').forEach((button) => button.addEventListener('click', () => void openTasks()));
$$('[data-action="show-overview"]').forEach((button) => button.addEventListener('click', () => setPage('overview')));
$$('[data-action="show-knowledge"]').forEach((button) => button.addEventListener('click', () => ui.openKnowledge()));
$('[data-action="close-source"]').addEventListener('click', closeSource);
$('#source-panel').addEventListener('close', () => { if (!$('#source-panel').open) closeSource(); });
document.addEventListener('input', (event) => {
  const control = event.target;
  if (!control.matches('input, textarea, select')) return;
  const key = draftKey(control);
  if (key) dirtyFields.set(key, control.value);
});
window.addEventListener('beforeunload', (event) => {
  if (dirtyFields.size || state.voiceCapture?.recording) { event.preventDefault(); event.returnValue = ''; }
});
window.addEventListener('pagehide', () => { if (state.voiceCapture) void stopVoiceCapture(); });
window.addEventListener('focus', () => {
  if (!state.user) return;
  void request('/me').then((me) => {
    const changed = String(me.user.id) !== String(state.user?.id) || JSON.stringify(me.capabilities || me.user.capabilities || []) !== JSON.stringify(state.capabilities);
    if (changed) { clearIdentity({ keepDrafts: true }); acceptIdentity(me); void loadSignedInData().then(render).catch(() => {}); }
  }).catch(() => {});
});
void loginBootstrap();
