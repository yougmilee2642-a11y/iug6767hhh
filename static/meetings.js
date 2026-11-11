const API = '/api/meet';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  user: null,
  users: [],
  meetings: [],
  documents: [],
  tasks: [],
  meetingData: null,
  page: 'meetings',
  tab: 'prep',
  showCreateMeeting: false,
  searchQuery: '',
  searchResults: [],
  transcriptDrafts: Object.create(null),
  protocolDrafts: Object.create(null),
  voiceDrafts: Object.create(null),
  voiceCapture: null,
  nextAgenda: null,
};

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
  const requestHeaders = { ...headers };
  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    requestHeaders['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const response = await fetch(path.startsWith('/api/') ? path : `${API}${path}`, {
    method,
    headers: requestHeaders,
    body: payload,
    credentials: 'same-origin',
  });
  let data = null;
  try {
    data = response.status === 204 ? null : await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new ApiError(data?.detail || `Ошибка запроса (${response.status}).`, response.status, data?.code);
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
    const message = error?.message || 'Не удалось выполнить действие.';
    if (model && isModelError(error)) {
      showNotice(`${message} Данные встречи сохранены. Можно повторить попытку.`, () => runAction(button, task, { model, label }));
    } else {
      showNotice(message);
    }
    return false;
  } finally {
    if (button) {
      button.disabled = false;
      button.classList.remove('is-busy');
      button.removeAttribute('aria-busy');
      if (oldLabel !== undefined) button.textContent = oldLabel;
    }
  }
}

function dateLabel(value) {
  if (!value) return 'Дата не указана';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
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
  if (state.voiceCapture?.recording) void stopVoiceCapture();
  state.page = page;
  render();
}

function updateNavigation() {
  $$('[data-action="show-meetings"], [data-action="show-tasks"]').forEach((button) => {
    const active = (state.page === 'meetings' || state.page === 'meeting')
      ? button.dataset.action === 'show-meetings'
      : state.page === 'tasks' && button.dataset.action === 'show-tasks';
    button.classList.toggle('nav-current', active);
  });
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
  else if (state.page === 'tasks') renderTaskBoard(app, state.tasks, false);
  else if (state.page === 'search') renderSearchResults(app);
  else renderMeetings(app);
  renderGlobalSearch();
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
      if (state.voiceCapture?.recording) void stopVoiceCapture();
      state.searchQuery = query;
      state.page = 'search';
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
  form.append(login.wrap, password.wrap, submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = { login: login.input.value.trim(), password: password.input.value };
    await runAction(submit, async () => {
      await request('/login', { method: 'POST', body: payload });
      await loadSignedInData();
      state.page = 'meetings';
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
  demo.append(irina, petr);
  shell.append(demo);
  app.append(shell);
}

async function loadSignedInData() {
  const [me, users, meetings, documents] = await Promise.all([
    request('/me'), request('/users'), request('/meetings'), request('/documents'),
  ]);
  state.user = me.user;
  state.users = users.users || [];
  state.meetings = meetings.meetings || [];
  state.documents = documents.documents || [];
}

async function loginBootstrap() {
  try {
    const me = await request('/me');
    state.user = me.user;
    const [users, meetings, documents] = await Promise.all([
      request('/users'), request('/meetings'), request('/documents'),
    ]);
    state.users = users.users || [];
    state.meetings = meetings.meetings || [];
    state.documents = documents.documents || [];
    render();
  } catch (error) {
    if (error.status === 401) {
      state.user = null;
      render();
    } else {
      render();
      showNotice(error.message);
    }
  }
}

async function logout() {
  try {
    await request('/logout', { method: 'POST' });
  } catch (error) {
    if (error.status !== 401) showNotice(error.message);
  }
  if (state.voiceCapture) await stopVoiceCapture();
  state.user = null;
  state.meetingData = null;
  state.meetings = [];
  state.documents = [];
  state.tasks = [];
  state.users = [];
  state.transcriptDrafts = Object.create(null);
  state.protocolDrafts = Object.create(null);
  state.voiceDrafts = Object.create(null);
  state.searchResults = [];
  state.searchQuery = '';
  state.page = 'meetings';
  render();
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
  intro.append(copy, createToggle);
  app.append(intro);
  if (state.showCreateMeeting) app.append(renderCreateMeetingForm());
  const list = node('section', 'meeting-list');
  list.append(node('h2', '', 'Мои встречи'));
  if (!state.meetings.length) {
    list.append(emptyState('Пока нет встреч', 'Создайте первую встречу, чтобы добавить документы и материалы.'));
  } else {
    const cards = node('div', 'meeting-card-grid');
    state.meetings.forEach((meeting) => {
      const card = node('article', 'meeting-card panel');
      card.append(node('span', 'meeting-date-chip', dateLabel(meeting.scheduled_at)));
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
  const participants = makeTextarea({ label: 'Участники', rows: 3, placeholder: 'По одному имени в строке' });
  form.append(title.wrap, topic.wrap, scheduled.wrap, participants.wrap);
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
    if (scheduled.input.value) payload.scheduled_at = scheduled.input.value;
    const success = await runAction(submit, async () => {
      const result = await request('/meetings', { method: 'POST', body: payload });
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

async function openMeeting(id) {
  if (state.voiceCapture?.recording) await stopVoiceCapture();
  clearNotice();
  try {
    const detail = await request(`/meetings/${encodeURIComponent(id)}`);
    state.meetingData = detail;
    state.page = 'meeting';
    state.tab = 'prep';
    state.nextAgenda = null;
    render();
  } catch (error) {
    showNotice(error.message);
  }
}

function renderMeeting(app) {
  const data = state.meetingData;
  const meeting = data.meeting || {};
  const head = node('section', 'meeting-detail-heading');
  head.append(makeButton('← Все встречи', () => setPage('meetings'), 'back-button'));
  const copy = node('div', 'meeting-detail-copy');
  copy.append(node('p', 'eyebrow', dateLabel(meeting.scheduled_at)));
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
}

function renderPreparation(target) {
  const data = state.meetingData;
  const meeting = data.meeting;
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
  docs.append(upload);
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
  docs.append(attach);
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
    row.append(detach);
    attached.append(row);
  });
  docs.append(attached);
  left.append(docs);

  const prep = node('section', 'panel prep-result');
  const heading = node('div', 'section-heading');
  const headingCopy = node('div', '');
  headingCopy.append(node('p', 'eyebrow', 'ПОДГОТОВКА'));
  headingCopy.append(node('h2', '', 'Справка к встрече'));
  const generate = makeButton('Сформировать справку', null, 'primary-button');
  generate.disabled = !(data.documents || []).length;
  generate.addEventListener('click', () => void runAction(generate, async () => {
    const result = await request(`/meetings/${encodeURIComponent(meeting.id)}/prepare`, { method: 'POST' });
    data.prep = result.prep;
    renderMeetingContent();
  }, { model: true }));
  heading.append(headingCopy, generate);
  prep.append(heading);
  const result = data.prep;
  if (!result) prep.append(emptyState('Справки пока нет', 'Сначала прикрепите документы, затем сформируйте краткую справку.'));
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

async function refreshMeeting() {
  if (!state.meetingData?.meeting?.id) return;
  state.meetingData = await request(`/meetings/${encodeURIComponent(state.meetingData.meeting.id)}`);
  renderMeetingContent();
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
      state.meetingData.utterances = result.utterances || [];
      state.transcriptDrafts[meetingId] = '';
      renderUtteranceList();
      renderSpeakerMapping();
      toast('Стенограмма сохранена');
    });
  });
  transcript.append(form);

  const voice = node('section', 'panel voice-capture-panel');
  voice.append(node('p', 'eyebrow', 'ГОЛОСОВОЙ РЕЖИМ'));
  voice.append(node('h2', '', 'Записать встречу'));
  voice.append(node('p', 'muted-copy', 'Речь распознаётся короткими фрагментами. Каждый фрагмент можно исправить перед добавлением.'));
  const voiceState = node('div', 'voice-capture-status');
  voiceState.id = 'voice-capture-status';
  voiceState.textContent = state.voiceCapture?.recording ? 'Идёт запись · фрагменты до 15 секунд'
    : state.voiceCapture ? 'Завершается распознавание фрагментов…' : 'Микрофон выключен';
  voice.append(voiceState);
  const voiceButton = makeButton(state.voiceCapture?.recording ? 'Остановить запись' : state.voiceCapture ? 'Распознавание…' : 'Начать запись', null,
    state.voiceCapture?.recording ? 'stop-recording-button' : 'primary-button');
  voiceButton.disabled = Boolean(state.voiceCapture && !state.voiceCapture.recording);
  voiceButton.id = 'voice-capture-toggle';
  voiceButton.addEventListener('click', () => {
    if (state.voiceCapture?.recording) void stopVoiceCapture();
    else void startVoiceCapture(meetingId, voiceButton);
  });
  voice.append(voiceButton);
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
  uh.append(node('span', 'small-chip', `${(data.utterances || []).length} шт.`));
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
  const utterances = state.meetingData.utterances || [];
  if (!utterances.length) {
    list.append(node('p', 'empty-copy', 'Пока нет реплик. Вставьте стенограмму или включите запись.'));
    return;
  }
  utterances.forEach((utterance) => {
    const card = node('article', 'utterance-card');
    const top = node('div', 'utterance-card-head');
    top.append(node('span', 'speaker-badge', utterance.speaker || utterance.speaker_label || 'Говорящий ?'));
    top.append(node('span', 'utterance-meta', `Реплика ${utterance.idx ?? ''}${utterance.source ? ` · ${utterance.source === 'voice' ? 'голос' : 'текст'}` : ''}`));
    card.append(top);
    const speaker = makeInput({ label: 'Метка говорящего', value: utterance.speaker_label || 'Говорящий ?' });
    const words = makeTextarea({ label: 'Текст реплики', value: utterance.text || '', rows: Math.max(2, Math.min(5, Math.ceil((utterance.text || '').length / 100))) });
    card.append(speaker.wrap, words.wrap);
    if (utterance.edited) card.append(node('small', 'edited-note', `Исходный текст: ${utterance.original_text || ''}`));
    const actions = node('div', 'inline-actions');
    const save = makeButton('Сохранить правку', async () => {
      const success = await runAction(save, async () => {
        const result = await request(`/utterances/${encodeURIComponent(utterance.id)}`, {
          method: 'PATCH', body: { text: words.input.value, speaker_label: speaker.input.value.trim() || 'Говорящий ?' },
        });
        state.meetingData.utterances = utterances.map((item) => String(item.id) === String(utterance.id) ? result.utterance : item);
        renderUtteranceList();
        renderSpeakerMapping();
      });
      if (success) toast('Правка сохранена');
    });
    const remove = makeButton('Удалить', async () => {
      const success = await runAction(remove, async () => {
        await request(`/utterances/${encodeURIComponent(utterance.id)}`, { method: 'DELETE' });
        state.meetingData.utterances = utterances.filter((item) => String(item.id) !== String(utterance.id));
        renderUtteranceList();
        renderSpeakerMapping();
      });
      if (success) toast('Реплика удалена');
    }, 'remove-button');
    actions.append(save, remove, citationButton(utterance.id, utterance.text, 'utterance', 'Открыть источник'));
    card.append(actions);
    list.append(card);
  });
}

function renderSpeakerMapping() {
  const target = $('#speaker-mapping');
  if (!target || !state.meetingData) return;
  target.replaceChildren();
  const utterances = state.meetingData.utterances || [];
  const labels = [...new Set(utterances.map((item) => item.speaker_label).filter(Boolean))];
  if (!labels.length) return;
  target.append(node('h3', '', 'Сопоставить говорящих'));
  const meeting = state.meetingData.meeting;
  const map = { ...(meeting.speaker_map || {}) };
  labels.forEach((label) => {
    const row = node('label', 'speaker-map-row');
    row.append(node('span', 'speaker-label', label));
    const options = [
      { value: '', label: 'Выберите участника' },
      ...(meeting.participants || []).map((name) => ({ value: name, label: name })),
      { value: '__custom__', label: 'Другое имя…' },
    ];
    const initial = map[label] && !(meeting.participants || []).includes(map[label]) ? '__custom__' : (map[label] || '');
    const select = makeSelect(options, initial);
    const custom = node('input', 'custom-speaker-name');
    custom.placeholder = 'Имя участника';
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
      state.meetingData.meeting = result.meeting;
      state.meetingData.utterances = result.utterances || [];
      renderUtteranceList();
      renderSpeakerMapping();
    });
    if (success) toast('Говорящие сопоставлены');
  });
  target.append(save);
}

function renderVoiceDraft(record) {
  const card = node('article', `voice-draft-card${record.loading ? ' is-loading' : ''}`);
  record.node = card;
  const header = node('div', 'voice-draft-head');
  header.append(node('b', '', `Голосовой фрагмент · ${Math.round(record.startMs / 1000)} сек.`));
  header.append(node('span', 'voice-draft-status', record.status || 'Ожидает распознавания'));
  card.append(header);
  const speaker = makeInput({ label: 'Метка говорящего', value: record.speakerLabel || 'Говорящий ?' });
  speaker.input.addEventListener('input', () => { record.speakerLabel = speaker.input.value; });
  const transcript = makeTextarea({ label: 'Распознанный текст', value: record.text || '', rows: 3, placeholder: 'Результат появится здесь. Его можно исправить.' });
  transcript.input.addEventListener('input', () => { record.text = transcript.input.value; });
  card.append(speaker.wrap, transcript.wrap);
  const actions = node('div', 'inline-actions');
  if (!record.transcribed) {
    const retry = makeButton(record.loading ? 'Распознаётся…' : record.error ? 'Повторить' : 'Распознать фрагмент', () => void recognizeVoiceDraft(record), 'secondary-button');
    retry.disabled = Boolean(record.loading);
    actions.append(retry);
  } else {
    const save = makeButton('Добавить в материалы', async () => {
      const success = await runAction(save, async () => {
        const result = await request(`/meetings/${encodeURIComponent(record.meetingId)}/utterances`, {
          method: 'POST',
          body: { text: transcript.input.value.trim(), speaker_label: speaker.input.value.trim() || 'Говорящий ?', source: 'voice', start_ms: record.startMs },
        });
        record.saved = true;
        state.meetingData.utterances = [...(state.meetingData.utterances || []), result.utterance];
        state.voiceDrafts[record.meetingId] = (state.voiceDrafts[record.meetingId] || []).filter((item) => item !== record);
        card.remove();
        renderUtteranceList();
        renderSpeakerMapping();
      });
      if (success) toast('Реплика добавлена');
    }, 'primary-button');
    save.disabled = !record.text?.trim();
    actions.append(save);
  }
  if (record.error) card.append(node('p', 'inline-error', record.error));
  card.append(actions);
  return card;
}

function addVoiceDraft(meetingId, blob, startMs) {
  const record = { id: crypto.randomUUID(), meetingId, blob, startMs, speakerLabel: 'Говорящий ?', text: '', status: 'Готов к распознаванию', transcribed: false, loading: false };
  state.voiceDrafts[meetingId] ||= [];
  state.voiceDrafts[meetingId].push(record);
  const list = $('#voice-drafts');
  if (list) list.prepend(renderVoiceDraft(record));
  return recognizeVoiceDraft(record);
}

async function recognizeVoiceDraft(record) {
  if (record.loading || record.transcribed) return;
  record.loading = true;
  record.error = '';
  record.status = 'Распознаётся…';
  if (record.node) {
    const newNode = renderVoiceDraft(record);
    record.node.replaceWith(newNode);
  }
  try {
    const form = new FormData();
    form.append('file', record.blob, 'meeting-voice.wav');
    form.append('mode', 'final');
    form.append('speaker_mode', 'all');
    const result = await request('/api/transcribe', { method: 'POST', body: form });
    const segments = Array.isArray(result.segments) ? result.segments.filter((segment) => segment.text?.trim()) : [];
    if (segments.length) {
      const drafts = state.voiceDrafts[record.meetingId] || [];
      const index = drafts.indexOf(record);
      const replacements = segments.map((segment) => ({
        id: crypto.randomUUID(), meetingId: record.meetingId, blob: record.blob,
        startMs: record.startMs + (Number(segment.start_ms) || 0), speakerLabel: segment.speaker_label || 'Говорящий ?',
        text: segment.text.trim(), status: 'Распознано · проверьте перед сохранением', transcribed: true, loading: false,
      }));
      drafts.splice(Math.max(0, index), index < 0 ? 0 : 1, ...replacements);
      const list = $('#voice-drafts');
      if (list) {
        record.node?.remove();
    [...replacements].reverse().forEach((item) => list.prepend(renderVoiceDraft(item)));
      }
      return;
    }
    record.text = String(result.raw_text || result.text || '').trim();
    record.transcribed = true;
    record.status = record.text ? 'Распознано · проверьте перед сохранением' : 'Речь не распознана';
    if (!record.text) record.error = 'Попробуйте записать фрагмент ещё раз или добавьте текст вручную.';
  } catch (error) {
    record.status = 'Не удалось распознать';
    record.error = isModelError(error) ? `${error.message} Запись сохранена в браузере; можно повторить.` : error.message;
  } finally {
    record.loading = false;
    if (record.node?.isConnected) {
      const replacement = renderVoiceDraft(record);
      record.node.replaceWith(replacement);
    }
  }
}

async function startVoiceCapture(meetingId, button) {
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
      const source = context.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(context, 'callwise-pcm');
      const gain = context.createGain();
      gain.gain.value = 0;
      source.connect(worklet);
      worklet.connect(gain);
      gain.connect(context.destination);
      const capture = {
        meetingId, stream, context, source, worklet, gain, recording: true,
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
  if (capture.closed) return;
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
    if (!capture.recording && !frames.length) return;
    return addVoiceDraft(capture.meetingId, wav, startMs);
  });
}

async function stopVoiceCapture() {
  const capture = state.voiceCapture;
  if (!capture) return;
  capture.recording = false;
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
  toast('Запись остановлена');
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

async function openSource(kind, id, quote) {
  const panel = $('#source-panel');
  const content = $('#source-content');
  const title = $('#source-title');
  panel.hidden = false;
  content.replaceChildren(node('p', 'muted-copy', 'Загружаю источник…'));
  try {
    if (kind === 'fragment') {
      const result = await request(`/fragments/${encodeURIComponent(id)}`);
      const fragment = result.fragment;
      title.textContent = fragment.document_title || 'Фрагмент документа';
      content.replaceChildren();
      content.append(node('p', 'source-location', fragment.location || `Фрагмент ${fragment.idx ?? ''}`));
      appendHighlighted(content, fragment.text, quote);
      content.append(downloadLink({ id: fragment.document_id, filename: fragment.document_title || 'Документ' }));
    } else {
      const result = await request(`/utterances/${encodeURIComponent(id)}`);
      const utterance = result.utterance;
      title.textContent = result.meeting_title || 'Реплика встречи';
      content.replaceChildren();
      content.append(node('p', 'source-location', `${utterance.speaker || utterance.speaker_label || 'Говорящий ?'} · реплика ${utterance.idx ?? ''}`));
      appendHighlighted(content, utterance.text, quote);
      const meeting = String(utterance.meeting_id) === String(state.meetingData?.meeting?.id)
        ? state.meetingData
        : await request(`/meetings/${encodeURIComponent(utterance.meeting_id)}`).catch(() => null);
      if ((meeting?.documents || []).length) {
        content.append(node('h3', '', 'Документы встречи'));
        (meeting.documents || []).forEach((documentItem) => content.append(downloadLink(documentItem)));
      }
    }
  } catch (error) {
    content.replaceChildren(node('p', 'inline-error', error.message));
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
  const draft = makeButton(protocol ? 'Обновить черновик' : 'Создать черновик', null, 'primary-button');
  draft.addEventListener('click', () => void runAction(draft, async () => {
    if (protocol) await saveProtocolEdits();
    const result = await request(`/meetings/${encodeURIComponent(data.meeting.id)}/protocol/draft`, { method: 'POST' });
    data.protocol = result.protocol;
    state.protocolDrafts = Object.create(null);
    renderMeetingContent();
  }, { model: true }));
  heading.append(copy, draft);
  section.append(heading);
  if (!protocol) {
    section.append(emptyState('Протокол ещё не подготовлен', 'Сохраните стенограмму, затем создайте черновик протокола.'));
    target.append(section);
    return;
  }
  if ((protocol.warnings || []).length) renderStringList(section, 'Нужно проверить', protocol.warnings);
  const groupOrder = [
    ['decision', 'Решения'], ['proposal', 'Предложения'], ['task', 'Поручения'], ['open_question', 'Открытые вопросы'],
  ];
  for (const [kind, title] of groupOrder) {
    const items = (protocol.items || []).filter((item) => item.kind === kind);
    const group = node('section', 'protocol-group');
    group.append(node('h3', '', title));
    if (!items.length) group.append(node('p', 'empty-copy', 'Нет пунктов.'));
    items.forEach((item) => group.append(renderProtocolItem(item)));
    section.append(group);
  }
  const actions = node('div', 'protocol-actions');
  const save = makeButton('Сохранить правки', async () => {
    const success = await runAction(save, async () => {
      await saveProtocolEdits();
      await refreshMeeting();
      toast('Правки протокола сохранены');
    });
  });
  actions.append(save);
  const confirm = makeButton('Подтвердить выбранные', async () => {
    const selected = $$('.protocol-item-select:checked', section).map((checkbox) => checkbox.value);
    if (!selected.length) { toast('Выберите поручения для подтверждения'); return; }
    const success = await runAction(confirm, async () => {
      await saveProtocolEdits();
      const result = await request(`/meetings/${encodeURIComponent(data.meeting.id)}/protocol/confirm`, { method: 'POST', body: { item_ids: selected } });
      data.protocol = result.protocol;
      if (result.created?.length || result.already_confirmed?.length) {
        data.tasks = [...(data.tasks || []), ...(result.created || []), ...(result.already_confirmed || [])];
      }
      renderMeetingContent();
      toast('Выбранные поручения подтверждены');
    });
  }, 'primary-button');
  confirm.disabled = !protocol.items?.some((item) => item.kind === 'task' && !item.confirmed);
  actions.append(confirm);
  section.append(actions);
  target.append(section);
}

function renderProtocolItem(item) {
  const drafts = state.protocolDrafts;
  const draft = drafts[item.id] || {};
  const card = node('article', `protocol-item ${item.confirmed ? 'confirmed' : ''}`.trim());
  card.dataset.itemId = item.id;
  const head = node('div', 'protocol-item-head');
  const title = node('span', 'protocol-kind', item.kind === 'decision' ? 'Решение' : item.kind === 'proposal' ? 'Предложение' : item.kind === 'task' ? 'Поручение' : 'Открытый вопрос');
  head.append(title);
  const outcomeValue = draft.outcome ?? item.outcome;
  if (item.kind === 'proposal' && outcomeValue) {
    const outcome = { rejected: 'Отклонено', accepted: 'Принято', discussed: 'Обсуждалось' }[outcomeValue] || outcomeValue;
    head.append(node('span', `outcome-badge outcome-${item.outcome}`, outcome));
  }
  if (item.kind === 'task' && !item.confirmed) {
    const selection = node('label', 'protocol-select-label');
    const checkbox = node('input', 'protocol-item-select');
    checkbox.type = 'checkbox'; checkbox.value = item.id;
    selection.append(checkbox, node('span', '', 'Выбрать'));
    head.append(selection);
  }
  card.append(head);
  const text = makeTextarea({ label: 'Формулировка', value: draft.text ?? item.text ?? '', rows: 2 });
  text.input.disabled = Boolean(item.confirmed);
  text.input.addEventListener('input', () => { drafts[item.id] = { ...(drafts[item.id] || {}), text: text.input.value }; });
  card.append(text.wrap);
  if (item.kind === 'proposal') {
    const outcomeWrap = node('label', 'meeting-field outcome-field');
    outcomeWrap.append(node('span', 'field-label', 'Исход предложения'));
    const outcomeSelect = makeSelect([
      { value: '', label: 'Не указан' }, { value: 'accepted', label: 'Принято' },
      { value: 'rejected', label: 'Отклонено' }, { value: 'discussed', label: 'Обсуждалось' },
    ], outcomeValue || '');
    outcomeSelect.disabled = Boolean(item.confirmed);
    outcomeSelect.addEventListener('change', () => { drafts[item.id] = { ...(drafts[item.id] || {}), outcome: outcomeSelect.value || null }; });
    outcomeWrap.append(outcomeSelect);
    card.append(outcomeWrap);
  }
  const fields = node('div', 'protocol-edit-fields');
  const assignee = makeInput({ label: 'Ответственный', value: draft.assignee ?? item.assignee ?? '', placeholder: 'Имя участника' });
  assignee.input.disabled = Boolean(item.confirmed);
  assignee.input.addEventListener('input', () => { drafts[item.id] = { ...(drafts[item.id] || {}), assignee: assignee.input.value }; });
  const due = makeInput({ label: 'Срок', type: 'date', value: draft.due ?? item.due ?? '' });
  due.input.disabled = Boolean(item.confirmed);
  due.input.addEventListener('input', () => { drafts[item.id] = { ...(drafts[item.id] || {}), due: due.input.value }; });
  const dueText = makeInput({ label: 'Срок словами', value: draft.dueText ?? item.due_text ?? '', placeholder: 'Например, в течение недели' });
  dueText.input.disabled = Boolean(item.confirmed);
  dueText.input.addEventListener('input', () => { drafts[item.id] = { ...(drafts[item.id] || {}), dueText: dueText.input.value }; });
  fields.append(assignee.wrap, due.wrap, dueText.wrap);
  card.append(fields);
  if (item.due_text && !due.input.value) card.append(node('p', 'task-meta', `Срок: ${item.due_text} (дата не распознана)`));
  if (item.kind === 'task') {
    const warning = node('div', 'protocol-warning-badges');
    const assigneeUnknown = draft.assignee !== undefined ? !draft.assignee.trim() : item.assignee_status === 'unknown';
    const dueUnknown = draft.due !== undefined
      ? !draft.due && !(draft.dueText ?? item.due_text ?? '').trim()
      : item.due_status === 'unknown' && !item.due_text;
    if (assigneeUnknown) warning.append(node('span', 'warning-badge red', 'Ответственный не назван'));
    if (dueUnknown) warning.append(node('span', 'warning-badge amber', 'Срок не назван'));
    if (warning.childNodes.length) card.append(warning);
  }
  if ((item.quotes || []).length) {
    const quotes = node('div', 'quote-list');
    item.quotes.forEach((quote) => quotes.append(citationButton(quote.utterance_id, `${quote.speaker ? `${quote.speaker}: ` : ''}${quote.text}`, 'utterance')));
    card.append(quotes);
  }
  if (item.confirmed) {
    card.append(node('p', 'confirmed-stamp', `Подтверждено: ${item.confirmed_by || 'пользователь'} · ${dateLabel(item.confirmed_at)}`));
  }
  return card;
}

async function saveProtocolEdits() {
  const protocol = state.meetingData.protocol;
  if (!protocol) return;
  const items = (protocol.items || []).map((item) => {
    if (item.confirmed) return { id: item.id, kind: item.kind, text: item.text, outcome: item.outcome, assignee: item.assignee, due: item.due, due_text: item.due_text };
    const draft = state.protocolDrafts[item.id] || {};
    return {
      id: item.id, kind: item.kind,
      text: draft.text ?? item.text,
      outcome: Object.prototype.hasOwnProperty.call(draft, 'outcome') ? draft.outcome : item.outcome,
      assignee: (draft.assignee ?? item.assignee ?? '').trim() || null,
      due: (draft.due ?? item.due) || null,
      due_text: (draft.dueText ?? (draft.due ? '' : item.due_text) ?? '').trim() || null,
    };
  });
  const result = await request(`/meetings/${encodeURIComponent(state.meetingData.meeting.id)}/protocol`, { method: 'PUT', body: { items } });
  state.meetingData.protocol = result.protocol;
  state.protocolDrafts = Object.create(null);
}

function renderMeetingTasks(target) {
  const tasks = state.meetingData.tasks || [];
  const header = node('section', 'panel meeting-tasks-heading');
  header.append(node('p', 'eyebrow', 'ЗАДАЧИ ПО ВСТРЕЧЕ'));
  header.append(node('h2', '', 'Поручения и следующие шаги'));
  const next = makeButton('Повестка следующей встречи', async () => {
    const success = await runAction(next, async () => {
      const result = await request(`/meetings/${encodeURIComponent(state.meetingData.meeting.id)}/next-agenda`, { method: 'POST', body: { create_meeting: true } });
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
  card.append(node('p', 'task-card-text', task.text || 'Без описания'));
  if (task.assignee) card.append(node('p', 'task-meta', `Ответственный: ${task.assignee}`));
  else if (task.assignee_status === 'unknown') card.append(node('p', 'warning-badge red', 'Ответственный не назван'));
  if (task.due) card.append(node('p', 'task-meta', `Срок: ${dateLabel(task.due)}`));
  else if (task.due_text) card.append(node('p', 'task-meta', `Срок: ${task.due_text} (дата не распознана)`));
  else if (task.due_status === 'unknown') card.append(node('p', 'warning-badge amber', 'Срок не назван'));
  const link = makeButton(task.meeting_title ? `Встреча: ${task.meeting_title}` : 'Открыть встречу', () => void openMeeting(task.meeting_id), 'task-meeting-link');
  card.append(link);
  if (task.source_quote?.utterance_id) card.append(citationButton(task.source_quote.utterance_id, task.source_quote.text, 'utterance', 'Открыть цитату'));
  const status = makeSelect([
    { value: 'open', label: 'Открыта' }, { value: 'in_progress', label: 'В работе' }, { value: 'done', label: 'Готова' },
  ], task.status);
  status.setAttribute('aria-label', 'Статус задачи');
  status.addEventListener('change', async () => {
    const old = task.status;
    status.disabled = true;
    try {
      const result = await request(`/tasks/${encodeURIComponent(task.id)}`, { method: 'PATCH', body: { status: status.value } });
      const index = collection.findIndex((item) => String(item.id) === String(task.id));
      if (index >= 0) collection[index] = result.task;
      if (!meetingOnly) state.tasks = collection;
      render();
    } catch (error) {
      status.value = old;
      status.disabled = false;
      showNotice(error.message);
    }
  });
  card.append(status);
  return card;
}

async function openTasks() {
  if (state.voiceCapture?.recording) await stopVoiceCapture();
  try {
    const result = await request('/tasks');
    state.tasks = result.tasks || [];
    state.page = 'tasks';
    render();
  } catch (error) {
    showNotice(error.message);
  }
}

async function loadSearch(query) {
  clearNotice();
  try {
    const result = await request(`/search?q=${encodeURIComponent(query)}`);
    state.searchResults = result.results || [];
    render();
  } catch (error) {
    showNotice(error.message);
    render();
  }
}

function renderSearchResults(app) {
  const intro = node('section', 'meetings-heading');
  const copy = node('div', '');
  copy.append(node('p', 'eyebrow', 'ПОИСК ПО ДОКУМЕНТАМ'));
  copy.append(node('h1', '', `Результаты: ${state.searchQuery}`));
  copy.append(node('p', 'muted-copy', 'Цитата открывается в исходном фрагменте документа.'));
  intro.append(copy, makeButton('К встречам', () => setPage('meetings'), 'back-button'));
  app.append(intro);
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
$('[data-action="close-source"]').addEventListener('click', () => { $('#source-panel').hidden = true; });
$('#source-panel').addEventListener('click', (event) => {
  if (event.target === $('#source-panel')) $('#source-panel').hidden = true;
});
window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') $('#source-panel').hidden = true;
});
window.addEventListener('pagehide', () => { if (state.voiceCapture) void stopVoiceCapture(); });
void loginBootstrap();
