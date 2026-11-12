// Functional organization forms; reuse existing controls and preview dialogs.
export function administrationUI(h) {
  const { node, makeButton: button, makeInput: input, request, runAction: run, state, dateLabel } = h;
  const current = (identity, epoch) => state.user?.id === identity && state.epoch === epoch;
  const panel = (app, title) => {
    const section = node('section', 'panel v2-functional-panel'); section.append(node('h1', '', title)); app.append(section); return section;
  };
  function review(parent, preview, confirmPath, onDone) {
    const dialog = node('dialog', 'panel');
    dialog.append(node('h2', '', 'Предпросмотр'), node('pre', '', JSON.stringify(preview.preview, null, 2)));
    const confirm = button('Подтвердить', () => void run(confirm, async () => {
      await request(confirmPath, { method: 'POST', body: { confirmation_id: preview.confirmation_id, idempotency_key: crypto.randomUUID() } });
      dialog.close(); dialog.remove(); onDone();
    }), 'primary-button');
    const cancel = button('Отменить', () => void run(cancel, async () => {
      await request(`/confirmations/${preview.confirmation_id}/cancel`, { method: 'POST' }); dialog.close(); dialog.remove();
    }));
    dialog.addEventListener('cancel', (event) => { event.preventDefault(); cancel.click(); });
    dialog.append(confirm, cancel); parent.append(dialog); dialog.showModal(); cancel.focus();
  }
  async function renderAdministration(app) {
    const identity = state.user.id, epoch = state.epoch;
    const section = panel(app, 'Администрирование · Пользователи');
    section.append(node('p', 'muted-copy', 'Изменения полномочий сохраняются после предпросмотра и подтверждения. Содержимое встреч администратору недоступно.'));
    try {
      const data = await request('/admin/users');
      if (!current(identity, epoch) || !section.isConnected) return;
      const table = node('table', '');
      const head = node('tr', ''); for (const text of ['Пользователь','Уровень','Отдел','Активен','Действие']) head.append(node('th', '', text)); table.append(head);
      for (const person of data.users) {
        if (!person.level) continue;
        const row = node('tr', ''); row.append(node('td', '', person.name));
        const role = node('select', ''); role.setAttribute('aria-label', `Уровень ${person.login}`);
        for (const key of ['director','head','lead','employee','contractor','admin','auditor']) {
          const option = node('option', '', key); option.value = key; role.append(option);
        }
        role.value = person.level;
        const department = node('select', ''); department.setAttribute('aria-label', `Отдел ${person.login}`);
        for (const dep of data.departments) { const option = node('option', '', dep.name); option.value = dep.id; department.append(option); }
        department.value = person.department_id;
        const active = node('input', ''); active.type = 'checkbox'; active.checked = Boolean(person.active); active.setAttribute('aria-label', `Активен ${person.login}`);
        for (const control of [role, department, active]) { const cell = node('td', ''); cell.append(control); row.append(cell); }
        const save = button('Предпросмотр', () => void run(save, async () => {
          const preview = await request('/admin/users', { method: 'POST', body: { user_id: person.id, level: role.value, department_id: Number(department.value), active: active.checked } });
          if (current(identity, epoch) && section.isConnected) review(section, preview, '/admin/users/confirm', () => { section.remove(); void renderAdministration(app); });
        }));
        save.disabled = person.id === identity;
        const cell = node('td', ''); cell.append(save); row.append(cell); table.append(row);
      }
      section.append(table);
    } catch (error) { if (current(identity, epoch) && section.isConnected) section.append(node('p', 'notice', error.message)); }
  }
  async function renderDelegation(app) {
    const identity = state.user.id, epoch = state.epoch;
    const section = panel(app, 'Делегировать полномочия');
    section.append(node('p', 'muted-copy', 'Временные права отдела действуют только в заданный период. Закрытые документы и право переделегирования не передаются.'));
    const form = node('form', 'create-meeting-form');
    const deputy = node('select', ''); deputy.setAttribute('aria-label', 'Заместитель');
    for (const person of state.users.filter((p) => p.id !== identity && ['head','lead','employee'].includes(p.level) && p.active)) {
      const option = node('option', '', person.name); option.value = person.id; deputy.append(option);
    }
    const department = input({ label: 'ID отдела', type: 'number', value: state.user.department?.id || '', required: true });
    const start = input({ label: 'Начало · ISO 8601 с часовым поясом', required: true, value: new Date().toISOString() });
    const end = input({ label: 'Окончание · ISO 8601 с часовым поясом', required: true });
    const reason = input({ label: 'Причина', required: true });
    const submit = button('Предпросмотр делегирования', null, 'primary-button', 'submit');
    form.append(deputy, department.wrap, start.wrap, end.wrap, reason.wrap, submit);
    form.addEventListener('submit', (event) => { event.preventDefault(); void run(submit, async () => {
      const preview = await request('/delegations', { method: 'POST', body: { to_user: Number(deputy.value), department_id: Number(department.input.value), starts_at: start.input.value, ends_at: end.input.value, reason: reason.input.value } });
      if (current(identity, epoch) && section.isConnected) review(section, preview, '/delegations/confirm', () => section.append(node('p', '', 'Делегирование сохранено.')));
    }); });
    section.append(form);
  }
  async function renderAudit(app) {
    const identity = state.user.id, epoch = state.epoch;
    const section = panel(app, 'Журнал действий');
    try {
      const data = await request('/audit?limit=200');
      if (!current(identity, epoch) || !section.isConnected) return;
      const table = node('table', '');
      const head = node('tr', ''); for (const label of ['Когда','Пользователь','Действие','Объект','Результат']) head.append(node('th', '', label)); table.append(head);
      for (const event of data.events) {
        const row = node('tr', '');
        for (const value of [dateLabel(event.at), event.user_id ?? '—', event.action, `${event.object_type || ''}:${event.object_id || ''}`, event.result]) row.append(node('td', '', String(value)));
        table.append(row);
      }
      section.append(table);
    } catch (error) { if (current(identity, epoch) && section.isConnected) section.append(node('p', 'notice', error.message)); }
  }
  return { renderAdministration, renderDelegation, renderAudit };
}
