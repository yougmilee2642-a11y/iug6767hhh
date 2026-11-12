import { operationsUI } from './meetings/operations.js';
import { assistantUI } from './meetings/assistant.js';
import { briefingUI } from './meetings/briefing.js';
import { track3UI } from './meetings/track3.js';
import { protocolPayload } from './meetings/protocol.js';
import { voiceAssistant } from './meetings/voice.js';
import { administrationUI } from './meetings/administration.js';
import { crmUI } from './meetings/crm.js';
import { calendarUI } from './meetings/calendar.js';
import { mediaUI } from './meetings/media.js';
import { callsUI } from './meetings/calls.js';
import { formulaLine } from './meetings/formula.js';

const API = '/api/meet';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  user: null,
  demoProfiles: [],
  capabilities: [],
  timezone: 'Europe/Minsk',
  epoch: 0,
  authTransition: null,
  users: [],
  meetings: [],
  documents: [],
  tasks: [],
  taskFilter: '',
  agendaDrafts: Object.create(null),
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
  navigate: setPage, propose:(proposal)=>{managerAssistant.propose(proposal);setPage('assistant');} });
const managerAssistant = assistantUI({node,makeButton,makeInput,makeTextarea,makeSelect,request,runAction,state,ui,dateLabel,openMeeting,openSource});
const administration = administrationUI({ node, makeButton, makeInput, request, runAction, state, dateLabel });
const crm = crmUI({ node, makeButton, makeInput, request, runAction, state, dateLabel, ui });
const calendarTools = calendarUI({ node, makeButton, makeInput, makeSelect, request, runAction, state, dateLabel, ui, markSaved, openMeeting });
const mediaTools = mediaUI({node,makeButton,makeInput,makeSelect,request,runAction,state,ui,refreshMeeting});
const callTools = callsUI({node,makeButton,makeInput,makeTextarea,makeSelect,request,runAction,state,ui,openMeeting,openSource,
  propose:(proposal)=>{managerAssistant.propose(proposal);setPage('assistant');}});
const assistant = voiceAssistant({ node, makeButton, request, state, openSource, dateLabel, openMeeting, proposeAction:(proposal)=>{managerAssistant.propose(proposal);setPage('assistant');}, navigate: (page) => {

  if (page === 'tasks') void openTasks(); else setPage(page);
} });

const operations = operationsUI({node,makeButton,makeInput,request,runAction,state,ui,dateLabel,openMeeting,navigate:setPage});

const briefing = briefingUI({node,makeButton,makeInput,request,runAction,state,dateLabel,openSource,openMeeting,
  speak:()=>assistant.ask('Брифинг дня')});

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
  state.taskFilter = ''; state.agendaDrafts = Object.create(null);
  state.searchQuery = ''; state.searchStatus = 'idle'; state.searchError = '';
  state.showCreateMeeting = false;
  state.page = 'meetings';
  closeSource(); ui.reset({ keepDrafts }); assistant.reset(); managerAssistant.reset();
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
  const requestHeaders = { 'X-Focus-Request':'1', ...headers };
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

function initials(name) {
  return String(name || '').trim().split(/\s+/).slice(0, 2).map((part) => part[0] || '').join('').toUpperCase() || '·';
}

function updateAccount() {
  const account = $('#account');
  account.replaceChildren();
  const extra = $('#nav-extra');
  extra?.replaceChildren();
  if (!state.user) return;
  // Role pages sit in the main navigation (always visible), not behind a menu.
  const pages = [['overview.read','Брифинг','briefing'], ['qa.ask','Ассистент','assistant'], ['calls.read','Звонки','calls'], ['retention.manage','Хранение данных','retention'], ['users.manage','Пользователи','administration'], ['integrations.manage','Интеграции','integrations'], ['audit.read','Журнал','audit'], ['delegation.grant','Делегировать','delegation']];
  for (const [capability, label, page] of pages) {
    if (!state.capabilities.includes(capability) || !extra) continue;
    const item = makeButton(label, () => setPage(page));
    item.dataset.page = page;
    extra.append(item);
  }
  (extra || account).append(makeButton('Уведомления',()=>setPage('notifications')));
  (extra || account).append(makeButton('Удалить мои данные',()=>{const content=node('p','','Запрос будет передан администратору. Данные удалятся только после его проверки и подтверждения.');ui.dialog('Запросить удаление данных',content,()=>request('/privacy/delete-request',{method:'POST'}),null,'Отправить запрос');}));
  assistant.mount(account);
  const person = node('span', 'account-person');
  const name = state.user.name || state.user.login;
  const role = state.user.level ? `${state.user.level} · ${state.user.department?.code || ''}` : '';
  person.append(node('span', 'account-avatar', initials(name)));
  const names = node('span', 'account-names');
  names.append(node('span', 'account-name', name));
  if (role) names.append(node('span', 'account-role', role));
  person.append(names);
  if (role) person.title = role;
  account.append(person, makeButton('Выйти', () => void logout(), 'logout-button'));
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
  const nav = $('.meetings-nav');
  if (nav) nav.hidden = !state.user;
  for (const button of $$('.meetings-nav [data-action]')) {
    button.disabled = !state.user;
    const page = button.dataset.action.replace('show-', '');
    const active = page === state.page || (page === 'meetings' && state.page === 'meeting');
    button.classList.toggle('nav-current', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  for (const button of $$('#nav-extra [data-page]')) {
    const active = button.dataset.page === state.page;
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
  if (state.page === 'administration') void administration.renderAdministration(app);
  else if (state.page === 'integrations') void crm.renderIntegrations(app);
  else if (state.page === 'delegation') void administration.renderDelegation(app);
  else if (state.page === 'audit') void administration.renderAudit(app);
  else if (state.page === 'meeting' && state.meetingData) renderMeeting(app);
  else if (state.page === 'overview') ui.renderOverview(app);
  else if (state.page === 'briefing') briefing.render(app);
  else if (state.page === 'assistant') managerAssistant.render(app);
  else if (state.page === 'notifications') void runAction(null,()=>operations.notifications(app));
  else if (state.page === 'retention') void runAction(null,()=>operations.retention(app));
  else if (state.page === 'calls') void runAction(null,()=>callTools.render(app));
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
    const button = makeButton('', null, 'search-button', 'submit');
    button.setAttribute('aria-label', 'Найти');
    button.title = 'Найти';
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M15.5 15.5L20 20" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
    form.append(input, button);
    $('.meetings-topbar').insertBefore(form, $('#account'));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const query = new FormData(form).get('q').toString().trim();
      if (!query) { input.focus(); return; }
      void loadSearch(query);
    });
  }
  const field = $('input[name="q"]', form);
  form.hidden = !ui.can('meetings.read');
  if (field && document.activeElement !== field) field.value = state.searchQuery;
}

function renderLogin(app) {
  const shell = node('section', 'login-card');
  shell.append(node('p', 'eyebrow', 'РАБОЧЕЕ ПРОСТРАНСТВО'));
  shell.append(node('h1', '', 'Войти в Фокус'));
  shell.append(node('p', 'login-copy', 'Встречи, знания и решения команды'));
  const form = node('form', 'login-form');
  const login = makeInput({ label: 'Логин', required: true, name: 'login', placeholder: 'Логин' });
  const password = makeInput({ label: 'Пароль', type: 'password', required: true, name: 'password', placeholder: 'Пароль' });
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
      state.page = landingPage();
      clearNotice();
      render();
    });
  });
  shell.append(form);
  const roleNames = { director: 'Директор', head: 'Руководитель отдела', lead: 'Руководитель группы', employee: 'Сотрудник', contractor: 'Подрядчик', admin: 'Администратор', auditor: 'Аудитор' };
  const demo = node('div', 'demo-accounts');
  demo.append(node('span', 'demo-accounts-title', state.demoProfiles.length ? 'Демо-доступ · Фотопринт' : 'Демо-доступ'));
  // With a seeded company (Фотопринт) offer its key roles; otherwise the classic pair.
  const featured = ['director', 'prod_head', 'operator', 'designer'];
  const people = state.demoProfiles.length
    ? featured.map((key) => state.demoProfiles.find((p) => p.login === key)).filter(Boolean).map((p) => [p.login, p.name, roleNames[p.level] || p.level])
    : [['irina', 'Ирина Власова', 'Руководитель проекта'], ['petr', 'Пётр Смирнов', 'Подрядчик, только чтение']];
  for (const [user, name, role] of people) {
    const row = makeButton('', () => {
      login.input.value = user; password.input.value = `${user}-demo`;
      form.requestSubmit();
    }, 'demo-account-button');
    row.setAttribute('aria-label', `Войти как ${name}`);
    const copy = node('span', 'demo-account-copy');
    copy.append(node('b', '', name), node('small', '', `${role} · ${user} / ${user}-demo`));
    row.append(node('span', 'account-avatar', initials(name)), copy, node('span', 'row-arrow', '→'));
    row.disabled = Boolean(state.authTransition);
    demo.append(row);
  }
  shell.append(demo);
  if (state.demoProfiles.length) {
    const label = node('label', 'meeting-field demo-role-picker'); label.append(node('span', 'field-label', 'Другие роли'));
    const select = node('select', ''); select.setAttribute('aria-label', 'Демо-роль');
    select.append(node('option', '', 'Выберите сотрудника'));
    for (const person of state.demoProfiles) { const option = node('option', '', `${person.name} · ${roleNames[person.level] || person.level || 'демо'}`); option.value = person.login; select.append(option); }
    select.addEventListener('change', () => { if (select.value) { login.input.value = select.value; password.input.value = select.value + '-demo'; submit.focus(); } });
    label.append(select); shell.append(label);
  }
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

function landingPage() { return state.user?.level === 'admin' ? (location.hash==='#integrations' ? 'integrations' : 'administration') : state.user?.level === 'auditor' ? 'audit' : 'overview'; }

async function loginBootstrap() {
  updateNavigation();
  $('#app').textContent = 'Загружаю рабочее пространство…';
  try { await loadSignedInData(); state.page = landingPage(); render(); }
  catch (error) {
    if (error.status === 401) {
      try { state.demoProfiles = (await request('/demo-profiles')).users || []; } catch { state.demoProfiles = []; }
    }
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
  copy.append(node('h1', '', 'Встречи'));
  copy.append(node('p', 'muted-copy', 'Подготовьте повестку, сохраните материалы и подтвердите решения.'));
  const createToggle = makeButton(state.showCreateMeeting ? 'Скрыть форму' : 'Новая встреча', () => {
    state.showCreateMeeting = !state.showCreateMeeting;
    render();
  }, 'primary-button accent-button');
  intro.append(copy, permit(createToggle, 'meetings.create'));
  app.append(intro);
  if (state.showCreateMeeting && ui.can('meetings.create')) app.append(renderCreateMeetingForm());
  const list = node('section', 'meeting-list');
  const today = dayKey(new Date(), state.timezone);
  const byTime = (a, b) => String(a.scheduled_at || '9999').localeCompare(String(b.scheduled_at || '9999'));
  const upcoming = state.meetings.filter((m) => !m.scheduled_at || dayKey(m.scheduled_at, m.timezone || state.timezone) >= today).sort(byTime);
  const past = state.meetings.filter((m) => !upcoming.includes(m)).sort(byTime);
  if (!state.meetingsTab) state.meetingsTab = upcoming.length || !past.length ? 'upcoming' : 'past';
  const toolbar = node('div', 'list-toolbar');
  const tabs = node('div', 'underline-tabs');
  tabs.setAttribute('role', 'tablist');
  for (const [key, label, count] of [['upcoming', 'Предстоящие', upcoming.length], ['past', 'Прошедшие', past.length]]) {
    const tab = makeButton(`${label} · ${count}`, () => { state.meetingsTab = key; render(); }, `underline-tab${state.meetingsTab === key ? ' active' : ''}`);
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-selected', String(state.meetingsTab === key));
    tabs.append(tab);
  }
  const filter = node('label', 'toolbar-search');
  const filterInput = node('input', '');
  filterInput.type = 'search';
  filterInput.placeholder = 'Поиск по встречам';
  filterInput.setAttribute('aria-label', 'Поиск по встречам');
  filterInput.value = state.meetingsFilter || '';
  filter.append(filterInput);
  toolbar.append(tabs, filter);
  list.append(toolbar);
  const groups = node('div', 'meeting-groups');
  const drawGroups = () => {
    groups.replaceChildren();
    const needle = (state.meetingsFilter || '').toLocaleLowerCase('ru');
    const chosen = (state.meetingsTab === 'past' ? [...past].reverse() : upcoming).filter((m) =>
      !needle || `${m.title} ${m.topic} ${(m.participants || []).join(' ')}`.toLocaleLowerCase('ru').includes(needle));
    if (!state.meetings.length) {
      groups.append(emptyState('Пока нет встреч', 'Создайте первую встречу, чтобы добавить документы и материалы.'));
      return;
    }
    if (!chosen.length) { groups.append(node('p', 'empty-copy', needle ? 'Ничего не найдено.' : 'Встреч в этом разделе нет.')); return; }
    let current = null; let rows = null;
    for (const meeting of chosen) {
      const zone = meeting.timezone || state.timezone;
      const key = meeting.scheduled_at ? dayKey(meeting.scheduled_at, zone) : '';
      if (key !== current) {
        current = key;
        const group = node('section', 'meeting-day');
        group.append(node('h2', '', dayHeading(key, today)));
        rows = node('div', 'meeting-rows');
        group.append(rows); groups.append(group);
      }
      rows.append(meetingRow(meeting, zone));
    }
  };
  filterInput.addEventListener('input', () => { state.meetingsFilter = filterInput.value; drawGroups(); });
  drawGroups();
  list.append(groups);
  app.append(list);
  calendarTools.panel(app);
}

function dayKey(value, timeZone = 'Europe/Moscow') {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  try { return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date); }
  catch { return date.toISOString().slice(0, 10); }
}

function dayHeading(key, today) {
  if (!key) return 'Без даты';
  const day = (offset) => { const d = new Date(`${today}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + offset); return d.toISOString().slice(0, 10); };
  if (key === today) return 'Сегодня';
  if (key === day(1)) return 'Завтра';
  if (key === day(-1)) return 'Вчера';
  const label = new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${key}T12:00:00Z`));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function timeLabel(value, timeZone) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  try { return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone }).format(date); }
  catch { return '—'; }
}

function plural(count, one, few, many) {
  const n = Math.abs(count) % 100; const d = n % 10;
  return n > 10 && n < 20 ? many : d === 1 ? one : d >= 2 && d <= 4 ? few : many;
}

function meetingRow(meeting, zone) {
  const row = node('article', 'meeting-row');
  row.append(node('span', 'meeting-row-time', timeLabel(meeting.scheduled_at, zone)));
  const main = node('div', 'meeting-row-main');
  main.append(node('h3', '', meeting.title || 'Без названия'));
  if (meeting.topic && meeting.topic.trim() !== (meeting.title || '').trim()) main.append(node('p', '', meeting.topic));
  const people = (meeting.participants || []).length;
  row.append(main, node('span', 'meeting-row-meta', people ? `${people} ${plural(people, 'участник', 'участника', 'участников')}` : 'Участники не указаны'));
  const open = makeButton('Открыть встречу', () => void openMeeting(meeting.id), 'row-open');
  open.title = meeting.title || 'Открыть встречу';
  row.append(open);
  row.addEventListener('click', (event) => { if (!event.target.closest('button')) void openMeeting(meeting.id); });
  return row;
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
  fileLabel.append(node('span', 'field-label', 'Загрузить TXT, DOCX, PDF, XLSX, CSV, PPTX, MD, HTML или EML'));
  const file = node('input', '');
  file.type = 'file';
  file.accept = '.txt,.docx,.pdf,.xlsx,.csv,.pptx,.md,.html,.eml';
  file.required = true;
  fileLabel.append(file);
  upload.append(fileLabel);
  const submit = makeButton('Загрузить и прикрепить', null, 'secondary-button', 'submit');
  const classification = makeSelect([
    {value:'public', label:'Вся компания'}, {value:'internal', label:'Сотрудники'},
    {value:'department', label:'Свой отдел'}, {value:'confidential', label:'Явный доступ'},
    {value:'secret', label:'Закрыто для ассистента'},
  ], state.user?.level === 'employee' ? 'department' : 'confidential');
  const classificationLabel = node('label', 'meeting-field');
  classificationLabel.append(node('span', 'field-label', 'Конфиденциальность'), classification);
  upload.append(classificationLabel, submit);
  upload.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!file.files?.[0]) return;
    const payload = new FormData();
    payload.append('file', file.files[0]);
    payload.append('confidentiality', classification.value);
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
    (result.warnings || []).forEach(w=>prep.append(node('p','access-limited-note',w.message)));
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
    prep.append(node('h3', '', followup.kpi_context ? 'Открытые задачи отдела и связанных встреч' : 'Открытые задачи предыдущих встреч'));
    if (!tasks.length) prep.append(node('p', 'empty-copy', 'Открытых задач предыдущих встреч нет.'));
    for (const task of tasks) prep.append(renderTaskCard(task, tasks, true));
    for (const q of followup.task_questions || []) {
      prep.append(node('p', '', q.text));
      for (const source of q.sources || []) prep.append(ui.sourceButton({ ...source, id: String(source.id).replace(/^T/, '') }));
    }
    if (result) prep.append(ui.feedback('prep', meeting.id, meeting.id));
  }
  if (followup?.kpi_context || followup?.previous_questions?.length) {
    const addDraft = (text, sources = []) => {
      const key = String(meeting.id); const items = state.agendaDrafts[key] ||= [];
      if (!items.some(item => item.text === text)) items.push({text, sources});
      render(); toast('Добавлено в локальный проект повестки. На сервере ничего не изменено.');
    };
    prep.append(node('h3', '', 'Вопросы и показатели отдела'));
    for (const question of followup.previous_questions || []) {
      prep.append(node('p', '', question.text));
      for (const source of question.sources || []) prep.append(ui.sourceButton(source));
      prep.append(makeButton('Добавить вопрос в проект повестки', () => addDraft(question.text,question.sources)));
    }
    const context = followup.kpi_context;
    if (context) {
      prep.append(node('p','task-meta',`Показатели отдела · данные ${dateLabel(context.as_of)}`));
      for (const metric of context.metrics || []) {
        const text = `${metric.label}: ${metric.value ?? 'не рассчитано'} ${metric.unit}`;
        prep.append(node('p','',text), formulaLine(node, metric));
        for (const source of metric.sources || []) prep.append(ui.sourceButton(source));
        prep.append(makeButton('Добавить показатель в проект повестки', () => addDraft(text,metric.sources)));
      }
      for (const warning of context.warnings || []) prep.append(node('p','muted-copy',warning));
    }
    for (const task of followup.open_tasks || []) prep.append(makeButton(`В повестку: ${task.text}`, () => addDraft(task.text,[task.source])));
  }
  const draftAgenda = state.agendaDrafts[String(meeting.id)] || [];
  if(followup?.document_insights_partial)prep.append(node('p','access-limited-note','Анализ документов неполный: достигнут лимит. Откройте реестр источников.'));
  for(const conflict of followup?.document_conflicts || []){
    const card=node('article','panel');card.append(node('h3','','Возможное противоречие'),node('p','',conflict.text));
    for(const source of conflict.sources)card.append(ui.sourceButton(source));
    card.append(makeButton('Добавить противоречие в проект повестки',()=>{
      const items=state.agendaDrafts[String(meeting.id)] ||= [];if(!items.some(i=>i.text===conflict.text))items.push({text:conflict.text,sources:conflict.sources});render();
    }));prep.append(card);
  }
  for(const promise of followup?.commitments || []){
    const card=node('article','panel');card.append(node('p','',`Обязательство: ${promise.what}`));for(const source of promise.sources)card.append(ui.sourceButton(source));
    if(can('protocol.confirm'))card.append(makeButton('Подготовить задачу по обязательству',()=>{managerAssistant.propose(promise.proposed_action);setPage('assistant');}));prep.append(card);
  }
  if (draftAgenda.length) {
    prep.append(node('h3','','Локальный проект повестки'), node('p','muted-copy','Не сохранён на сервере; исчезнет после выхода или закрытия вкладки.'));
    for (const item of draftAgenda) {
      prep.append(node('p','',item.text));
      for (const source of item.sources || []) if (source) prep.append(ui.sourceButton({...source, id:source.kind==='task' ? String(source.id).replace(/^T/,'') : source.id}));
    }
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
  voiceState.textContent = state.voiceCapture?.recording ? 'Идёт запись, все уведомлены · фрагменты до 15 секунд'
    : state.voiceCapture ? 'Завершается распознавание фрагментов…' : 'Микрофон выключен';
  voice.append(voiceState);
  const consentLabel = node('label', 'record-consent');
  const consent = node('input', '');
  consent.type = 'checkbox';
  consentLabel.append(consent, node('span', '', 'Я подтвердил(а), что все участники согласны на запись и расшифровку встречи.'));
  consentLabel.hidden = Boolean(state.voiceCapture?.recording);
  voice.append(permit(consentLabel, 'transcript.edit'));
  voice.append(node('p','muted-copy','Автоостановка после двух минут тишины. Уже записанные фрагменты сохраняются.'));
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
  mediaTools.mount(target,data.meeting);
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
        silenceSamples:0,
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
    if (status) status.textContent = 'Идёт запись, все уведомлены · фрагменты до 15 секунд';
    const control = $('#voice-capture-toggle');
    if (control) { control.textContent = 'Остановить запись'; control.className = 'stop-recording-button'; }
    toast('Запись началась');
  }
}

function acceptVoiceFrame(capture, frame) {
  if (capture.closed || capture.cancelled || capture.epoch !== state.epoch) return;
  capture.frames.push(frame);
  capture.sampleCount += frame.length;
  let energy=0;for(const value of frame)energy+=value*value;
  capture.silenceSamples=Math.sqrt(energy/Math.max(1,frame.length))<0.008 ? capture.silenceSamples+frame.length : 0;
  if(capture.recording && capture.silenceSamples>=16000*120){
    showNotice('Запись остановлена после двух минут тишины. Фрагменты сохранены для проверки.');
    void stopVoiceCapture();return;
  }
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
      await mediaTools.source(content,utterance,()=>panel.open && sequence===sourceSequence && epoch===state.epoch);
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
      for (const decision of data?.decisions || []) {
        const row = node('article','claim-item');
        row.append(node('p','',decision.text),node('p','task-meta',`Ответственный: ${decision.owner_name || 'не уточнён'} · срок: ${dateLabel(decision.due)}`));
        row.append(makeButton('Открыть решение в протоколе',()=>{ closeSource(); void openMeeting(decision.meeting_id,'protocol'); },'task-meeting-link'));
        content.append(row);
      }
      for (const claim of data?.claims || []) {
        content.append(node('p','',claim.text));
        for (const source of claim.native_sources || []) content.append(makeButton(source.title || 'Источник',()=>void openSource(source.kind==='document'?'fragment':source.kind,source.id,source.quote,source),'citation-chip'));
      }
      for (const warning of data?.warnings || []) content.append(node('p','access-limited-note',warning));
      if (data?.meeting) content.append(node('p','',data.meeting.title),node('p','task-meta',dateLabel(data.meeting.scheduled_at)),makeButton('Открыть встречу-источник',()=>{closeSource();void openMeeting(data.meeting.id);},'secondary-button'));
      if (data?.metric) content.append(node('p','',`${data.metric.label}: ${data.metric.value ?? 'Нет данных'} ${data.metric.unit || ''}`),formulaLine(node, data.metric));
      if(kind==='metric' && data?.metric) {
        const basis={kind:'metric',id:String(id)};
        const propose=(type)=>{closeSource();managerAssistant.propose({kind:type,text:`Проверить показатель «${data.metric.label}»`,basis});setPage('assistant');};
        if(state.capabilities.includes('meetings.create'))content.append(makeButton('Обсудить показатель на новой встрече',()=>propose('meeting')));
        if(state.capabilities.includes('protocol.confirm'))content.append(makeButton('Предложить поручение по показателю',()=>propose('task')));
      }
      const labels = { numerator: 'Числитель', denominator: 'Знаменатель', completed_orders: 'Завершённые заказы', on_time_orders: 'Заказы в срок', produced_units: 'Произведено единиц', defective_units: 'Бракованных единиц', occupied_capacity: 'Занятая мощность', available_capacity: 'Доступная мощность', order_no:'Заказ', status:'Статус', promised_at:'Обещанный срок', completed_at:'Завершён', first_response_seconds:'Первый ответ, секунд', sla_seconds:'SLA, секунд', closed_by:'Закрыто кем', occupied_hours:'Занятые часы', available_hours:'Доступные часы', section:'Участок', forecast:'Прогноз (0/1)' };
      const snapshots = data?.snapshots || [data];
      for (const snapshot of [data, ...snapshots.filter((item) => item !== data)]) {
        if (!snapshot) continue;
        if (snapshot.source_id) content.append(node('h3', '', `Снимок ${snapshot.source_id}`));
        if (snapshot.period_start) content.append(node('p', 'task-meta', `Период: ${dateLabel(snapshot.period_start)} — ${dateLabel(snapshot.period_end)}`));
        if (snapshot.as_of) content.append(node('p', 'task-meta', `Актуальность: ${dateLabel(snapshot.as_of)}`));
        for (const [key, label] of Object.entries(labels)) if (Object.hasOwn(snapshot, key)) {
          const value = key.endsWith('_at') && snapshot[key] ? dateLabel(snapshot[key]) : snapshot[key];
          content.append(node('p', '', `${label}: ${value ?? 'Нет данных'}`));
        }
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
  if (protocol) {
    const exports=node('div','inline-actions');
    for(const [format,label] of [['md','Скачать протокол MD'],['html','Версия для печати']]){
      const link=node('a','download-link',label);link.href=`${API}/meetings/${data.meeting.id}/protocol/export?format=${format}`;link.setAttribute('download','');exports.append(link);
    }
    if(ui.can('calendar.invite'))exports.append(makeButton('Разослать протокол участникам',()=>void runAction(null,async()=>{
      const preview=await request(`/meetings/${data.meeting.id}/protocol/mail/preview`,{method:'POST',body:{recipient_ids:[]}});
      const content=node('div');content.append(node('p','',preview.preview.notice),node('p','',`Получателей: ${preview.preview.recipients.length}`),node('pre','',preview.preview.body));
      const key=crypto.randomUUID();
      ui.dialog('Подтвердить рассылку протокола',content,async()=>{
        const result=await request(`/meetings/${data.meeting.id}/protocol/mail/confirm`,{method:'POST',body:{confirmation_id:preview.confirmation_id,idempotency_key:key}});
        for(const id of result.outbox_ids){const link=node('a','download-link',`Письмо ${id}`);link.href=`${API}/protocol-outbox/${id}/download.eml`;link.setAttribute('download','');exports.append(link);}
        toast('Протокол помещён в локальную очередь');
      },()=>request(`/confirmations/${preview.confirmation_id}/cancel`,{method:'POST'}));
    }),'secondary-button'));
    section.append(exports);
  }
  if (!protocol) {
    section.append(emptyState('Протокол ещё не подготовлен', 'Сохраните стенограмму, затем создайте черновик протокола.'));
    target.append(section);
    return;
  }
  if (ui.can('crm.write')) section.append(makeButton('Прикрепить протокол к CRM · mock',()=>void runAction(null,()=>crm.attachProtocol(data.meeting,()=>refreshMeeting(data.meeting.id)))));
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
  card.dataset.itemId = item.id; card.tabIndex = -1;
  for (const entity of item.linked_entities || []) if(entity.kind==='order') card.append(makeButton(`Заказ ${entity.id}`,()=>void runAction(null,()=>crm.openOrder(entity.id)),'task-meeting-link'));
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
  if (item.kind === 'decision' && ui.can('protocol.confirm')) card.append(makeButton('Контроль решения',()=>void ui.controlDecision(item,state.meetingData.meeting.id)));
  if (item.confirmed) {
    card.append(node('p', 'confirmed-stamp', `Подтверждено: ${item.confirmed_by || 'пользователь'} · ${dateLabel(item.confirmed_at)}`));
    if (item.task_id) card.append(makeButton('Открыть связанную задачу', async () => {
      await openMeeting(state.meetingData.meeting.id,'tasks'); document.getElementById(`task-${item.task_id}`)?.focus();
    },'task-meeting-link'));
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
  if(result.context) {
    panel.append(node('p','muted-copy',result.context.notice));
    for(const warning of result.context.warnings || [])panel.append(node('p','gap-state',warning));
    for(const item of result.context.items || []) {
      panel.append(node('p','',item.text));
      for(const source of item.sources || [])panel.append(ui.sourceButton(source));
      const meetingId=state.meetingData.meeting.id;
      panel.append(makeButton('Добавить в проект повестки',()=>{
        const drafts=state.agendaDrafts[String(meetingId)] ||= [];
        if(!drafts.some(d=>d.text===item.text))drafts.push({text:item.text,sources:item.sources});
        toast('Добавлено в локальный проект повестки подготовки.');
      }));
    }
  }
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
  const view = state.taskView || 'list';
  const viewToggle = node('div', 'view-toggle');
  for (const [key, label] of [['list', 'Списком'], ['board', 'Доской']]) {
    const option = makeButton('', () => { state.taskView = key; render(); }, `view-toggle-button view-${key}${view === key ? ' active' : ''}`);
    option.setAttribute('aria-label', `Показать задачи ${label.toLowerCase()}`);
    option.setAttribute('aria-pressed', String(view === key));
    option.title = label;
    viewToggle.append(option);
  }
  if (!meetingOnly) {
    const intro = node('div', 'meetings-heading');
    const copy = node('div', '');
    copy.append(node('h1', '', 'Задачи'));
    const open = tasks.filter((task) => !['done', 'cancelled'].includes(task.status));
    const overdue = open.filter(isOverdue).length;
    copy.append(node('p', 'muted-copy', state.tasksStatus === 'ready'
      ? `${open.length} ${plural(open.length, 'открытая', 'открытых', 'открытых')} · ${overdue} ${plural(overdue, 'просрочена', 'просрочены', 'просрочено')}`
      : 'Задачи собраны из подтверждённых протоколов доступных встреч.'));
    intro.append(copy);
    if (tasks.length) intro.append(viewToggle);
    parent.append(intro);
  } else if (tasks.length) board.append(viewToggle);
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
  const activeTasks = tasks.filter(task => !['done','cancelled'].includes(task.status));
  const missingOwner = activeTasks.filter(task => !task.assignee).length;
  const missingDue = activeTasks.filter(task => !task.due).length;
  const filter = makeSelect([{value:'',label:'Все задачи'}, {value:'assignee',label:`Без владельца · ${missingOwner}`},
    {value:'due',label:`Без срока · ${missingDue}`}, {value:'either',label:'Без владельца или срока'}], state.taskFilter);
  const filterLabel = node('label', 'meeting-field'); filterLabel.append(node('span','field-label','Требуют уточнения'), filter);
  filter.addEventListener('change', () => { state.taskFilter = filter.value; render(); }); board.append(filterLabel);
  if (state.taskFilter) tasks = activeTasks.filter(task => state.taskFilter === 'assignee' ? !task.assignee : state.taskFilter === 'due' ? !task.due : !task.assignee || !task.due);
  if (view === 'list') {
    const table = node('div', 'task-table');
    table.setAttribute('role', 'table');
    table.setAttribute('aria-label', 'Задачи');
    const head = node('div', 'task-table-head');
    head.setAttribute('role', 'row');
    for (const title of ['Задача', 'Встреча', 'Срок', 'Статус']) { const cell = node('span', '', title); cell.setAttribute('role', 'columnheader'); head.append(cell); }
    table.append(head);
    const order = { open: 0, in_progress: 1, blocked: 2, done: 3, cancelled: 4 };
    const sorted = [...tasks].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || String(a.due || '9999').localeCompare(String(b.due || '9999')));
    if (!sorted.length) table.append(node('p', 'empty-copy', 'Нет задач'));
    sorted.forEach((task) => table.append(renderTaskRow(task, tasks, meetingOnly)));
    board.append(table);
    board.append(node('p', 'task-table-foot', `${sorted.length} ${plural(sorted.length, 'задача', 'задачи', 'задач')}`));
    parent.append(board);
    return;
  }
  const columns = [
    ['open', 'Открытые'], ['in_progress', 'В работе'], ['blocked', 'Заблокированы'], ['done', 'Готово'], ['cancelled', 'Отменены'],
  ];
  const grid = node('div', 'task-columns');
  columns.forEach(([status, title]) => {
    const column = node('section', `task-column task-${status}`);
    const group = tasks.filter((task) => task.status === status);
    const heading = node('div', 'task-column-heading');
    heading.append(node('h2', '', title), node('span', 'small-chip', String(group.length)));
    column.append(heading);
    if(ui.can('tasks.change')){
      column.addEventListener('dragover',event=>event.preventDefault());
      column.addEventListener('drop',event=>{event.preventDefault();const id=Number(event.dataTransfer.getData('text/plain'));const task=tasks.find(t=>Number(t.id)===id);if(!task || task.status===status)return;void runAction(null,async()=>{
        const preview=await request(`/tasks/${id}/preview`,{method:'POST',body:{changes:{status}}});const content=node('p','',`Переместить поручение «${task.text}» в «${title}»?`);const key=crypto.randomUUID();
        ui.dialog('Подтвердить смену статуса',content,async()=>{const result=await request(`/tasks/${id}/confirm`,{method:'POST',body:{confirmation_id:preview.confirmation_id,idempotency_key:key}});Object.assign(task,result.task);render();},()=>request(`/confirmations/${preview.confirmation_id}/cancel`,{method:'POST'}));
      });});
    }
    if (!group.length) column.append(node('p', 'empty-copy', 'Нет задач'));
    group.forEach((task) => column.append(renderTaskCard(task, tasks, meetingOnly)));
    grid.append(column);
  });
  board.append(grid);
  parent.append(board);
}

const TASK_STATUS = { open: 'Открыта', in_progress: 'В работе', blocked: 'Заблокирована', done: 'Готова', cancelled: 'Отменена' };

function isOverdue(task) {
  if (!task.due || ['done', 'cancelled'].includes(task.status)) return false;
  return String(task.due).slice(0, 10) < dayKey(new Date(), state.timezone);
}

function shortDate(value) {
  const date = new Date(`${String(value).slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(date);
}

function renderTaskRow(task, collection, meetingOnly) {
  const row = node('article', `task-row status-${task.status}`);
  row.id = `task-${task.id}`; row.tabIndex = -1;
  row.setAttribute('role', 'row');
  const main = node('div', 'task-row-main');
  main.setAttribute('role', 'cell');
  main.append(node('p', 'task-card-text', task.text || 'Без описания'));
  if (task.assignee) main.append(node('p', 'task-meta', `Ответственный: ${task.assignee}`));
  else if (task.assignee_status === 'unknown') main.append(node('p', 'warning-badge red', 'Ответственный не назван'));
  if (task.assignee_suggestion) main.append(node('p','task-meta',`Предположение: ${task.assignee_suggestion.name} · ${task.assignee_suggestion.reason}. Ответственный не назначен.`));
  const priorities = {low:'Низкий', normal:'Обычный', high:'Высокий', urgent:'Срочный'};
  const extra = [];
  if (task.priority && task.priority !== 'normal') extra.push(`Приоритет: ${priorities[task.priority] || task.priority}`);
  if (task.external_ref) extra.push(`CRM: ${task.external_ref}`);
  if (extra.length) main.append(node('p', 'task-meta', extra.join(' · ')));
  const actions = node('div', 'task-row-actions');
  for (const entity of task.linked_entities || []) {
    if (entity.kind==='order') actions.append(makeButton(`Заказ ${entity.id}`,()=>void runAction(null,()=>crm.openOrder(entity.id)),'task-meeting-link'));
    else main.append(node('p','task-meta', `${{customer:'Клиент', document:'Документ'}[entity.kind] || 'Связь'}: ${entity.id}`));
  }
  if (task.protocol_item_id) actions.append(makeButton('Основание в протоколе', async () => {
    await openMeeting(task.meeting_id,'protocol'); $$('.protocol-item').find(item => String(item.dataset.itemId) === String(task.protocol_item_id))?.focus();
  },'task-meeting-link'));
  if (task.source_quote?.utterance_id) actions.append(citationButton(task.source_quote.utterance_id, task.source_quote.text, 'utterance', 'Открыть цитату'));
  if (ui.can('tasks.change')) actions.append(makeButton('Изменить задачу', () => ui.editTask(task, collection, meetingOnly), 'task-meeting-link'));
  if (ui.can('crm.write')) {
    if (!task.crm_status && !['done','cancelled'].includes(task.status)) actions.append(makeButton('Отправить в Битрикс24 · mock',()=>void runAction(null,()=>crm.exportTask(task,async()=>{ if(meetingOnly) await refreshMeeting(task.meeting_id); else await openTasks(); })),'task-meeting-link'));
    actions.append(makeButton('Статус CRM · mock',()=>void runAction(null,()=>crm.status(task)),'task-meeting-link'));
  }
  actions.append(ui.feedback('task', task.id, task.meeting_id));
  main.append(actions);
  const meeting = node('div', 'task-row-meeting');
  meeting.setAttribute('role', 'cell');
  meeting.append(makeButton(task.meeting_title || 'Открыть встречу', () => void openMeeting(task.meeting_id), 'task-meeting-link'));
  const due = node('div', `task-row-due${isOverdue(task) ? ' overdue' : ''}`);
  due.setAttribute('role', 'cell');
  if (task.due) due.append(node('span', '', shortDate(task.due)));
  else if (task.due_text) due.append(node('span', '', `${task.due_text} (дата не распознана)`));
  else if (task.due_status === 'unknown') due.append(node('span', 'warning-badge amber', 'Срок не назван'));
  else due.append(node('span', 'empty-copy', '—'));
  const status = node('div', 'task-row-status', isOverdue(task) ? 'Просрочено' : (TASK_STATUS[task.status] || task.status));
  status.setAttribute('role', 'cell');
  row.append(main, meeting, due, status);
  return row;
}

function renderTaskCard(task, collection, meetingOnly) {
  const card = node('article', 'task-card panel');
  card.id = `task-${task.id}`; card.tabIndex = -1;
  if(ui.can('tasks.change')){card.draggable=true;card.addEventListener('dragstart',event=>event.dataTransfer.setData('text/plain',String(task.id)));}
  card.append(node('p', 'task-card-text', task.text || 'Без описания'));
  const priorities = {low:'Низкий', normal:'Обычный', high:'Высокий', urgent:'Срочный'};
  if (task.priority) card.append(node('p','task-meta',`Приоритет: ${priorities[task.priority] || task.priority}`));
  for (const entity of task.linked_entities || []) {
    if (entity.kind==='order') card.append(makeButton(`Заказ ${entity.id}`,()=>void runAction(null,()=>crm.openOrder(entity.id)),'task-meeting-link'));
    else card.append(node('p','task-meta', `${{customer:'Клиент', document:'Документ'}[entity.kind] || 'Связь'}: ${entity.id}`));
  }
  if (task.external_ref) card.append(node('p','task-meta',`CRM: ${task.external_ref}`));
  if (task.assignee) card.append(node('p', 'task-meta', `Ответственный: ${task.assignee}`));
  else if (task.assignee_status === 'unknown') card.append(node('p', 'warning-badge red', 'Ответственный не назван'));
  if (task.assignee_suggestion) card.append(node('p','task-meta',`Предположение: ${task.assignee_suggestion.name} · ${task.assignee_suggestion.reason}. Ответственный не назначен.`));
  if (task.due) card.append(node('p', 'task-meta', `Срок: ${dateLabel(task.due)}`));
  else if (task.due_text) card.append(node('p', 'task-meta', `Срок: ${task.due_text} (дата не распознана)`));
  else if (task.due_status === 'unknown') card.append(node('p', 'warning-badge amber', 'Срок не назван'));
  const link = makeButton(task.meeting_title ? `Встреча: ${task.meeting_title}` : 'Открыть встречу', () => void openMeeting(task.meeting_id), 'task-meeting-link');
  card.append(link);
  if (task.protocol_item_id) card.append(makeButton('Основание в протоколе', async () => {
    await openMeeting(task.meeting_id,'protocol'); $$('.protocol-item').find(item => String(item.dataset.itemId) === String(task.protocol_item_id))?.focus();
  },'task-meeting-link'));
  if (task.source_quote?.kind==='manual_request') card.append(node('p','task-meta','Ручное поручение, подтверждённое пользователем; это не реплика записи.'));
  if (task.source_quote?.utterance_id) card.append(citationButton(task.source_quote.utterance_id, task.source_quote.text, 'utterance', 'Открыть цитату'));
  card.append(makeButton('Комментарии и история',()=>void runAction(null,()=>operations.comments(card,task.id)),'secondary-button'));
  if (task.escalated) card.append(node('p','warning-badge red','Эскалировано руководителю'));
  if (ui.can('tasks.change')) card.append(makeButton('Изменить задачу', () => ui.editTask(task, collection, meetingOnly)));
  if (ui.can('crm.write')) {
    if (!task.crm_status && !['done','cancelled'].includes(task.status)) card.append(makeButton('Отправить в Битрикс24 · mock',()=>void runAction(null,()=>crm.exportTask(task,async()=>{ if(meetingOnly) await refreshMeeting(task.meeting_id); else await openTasks(); }))));
    card.append(makeButton('Статус CRM · mock',()=>void runAction(null,()=>crm.status(task))));
  }
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
    if (result.stale) card.append(node('p','access-limited-note','Источник устарел. Проверьте версию и срок действия.'));
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
window.addEventListener('hashchange',()=>{ if(location.hash==='#integrations' && state.capabilities.includes('integrations.manage')) setPage('integrations'); });
window.addEventListener('focus', () => {
  if (!state.user) return;
  void request('/me').then((me) => {
    const changed = String(me.user.id) !== String(state.user?.id) || JSON.stringify(me.capabilities || me.user.capabilities || []) !== JSON.stringify(state.capabilities);
    if (changed) { clearIdentity({ keepDrafts: true }); acceptIdentity(me); void loadSignedInData().then(render).catch(() => {}); }
  }).catch(() => {});
});
void loginBootstrap();
