// One representation is shared by the editable draft, preview, and save request.
export function protocolPayload(item, draft = {}) {
  if (item.confirmed) draft = {};
  const due = (draft.due ?? item.due) || null;
  const dateChanged = Object.hasOwn(draft, 'due') && due !== (item.due || null);
  const dueText = Object.hasOwn(draft, 'dueText') ? draft.dueText : dateChanged && due ? '' : item.due_text;
  return {
    id: item.id,
    kind: item.kind,
    text: String(draft.text ?? item.text ?? '').trim(),
    outcome: Object.hasOwn(draft, 'outcome') ? draft.outcome : item.outcome,
    assignee: String(draft.assignee ?? item.assignee ?? '').trim() || null,
    due,
    due_text: String(dueText ?? '').trim() || null,
  };
}
