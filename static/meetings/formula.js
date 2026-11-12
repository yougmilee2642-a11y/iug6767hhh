// Человеческое описание расчёта показателя. Точная формула с сервера остаётся
// доказательством: она показывается во всплывающей подсказке и в источнике.
const PLAIN = {
  open_tasks: 'все задачи, кроме готовых и отменённых',
  overdue_tasks: 'открытые задачи, срок которых уже прошёл',
  missing_assignee: 'открытые задачи без ответственного',
  missing_due: 'открытые задачи без даты срока',
  open_decisions: 'решения на контроле в статусе «открыто»',
  overdue_decisions: 'открытые решения с прошедшим сроком',
  on_time_orders: 'доля заказов, завершённых в обещанный срок',
  defect_rate: 'доля бракованных единиц от произведённых',
  capacity_utilization: 'занятые часы оборудования от доступных',
  support_sla: 'доля обращений с первым ответом в пределах SLA',
  mary_resolution: 'доля обращений, закрытых ассистентом Mary',
  moderation_queue: 'заказы, ожидающие модерации макета',
  unclaimed_pickup: 'заказы, не забранные из пункта выдачи',
  late_order_causes: 'завершённые заказы, выданные позже обещанного',
  capacity_forecast_peak: 'самая высокая прогнозная загрузка на ближайшие недели',
};

function count(value) {
  return new Intl.NumberFormat('ru-RU').format(value);
}

export function plainFormula(metric) {
  const raw = String(metric?.formula || '');
  let text = PLAIN[metric?.key];
  if (!text) {
    if (/^sum\(|×\s*100/.test(raw)) text = 'отношение двух показателей за период, в процентах';
    else if (/^count\(/.test(raw)) text = 'количество записей в текущем реестре';
    else text = raw ? 'расчёт по данным витрины' : 'не предоставлен';
  }
  const top = metric?.numerator, bottom = metric?.denominator;
  if (typeof top === 'number' && typeof bottom === 'number') text += ` · ${count(top)} из ${count(bottom)}`;
  return text;
}

// «Формула: …» с понятным текстом; исходное выражение — в title.
export function formulaLine(node, metric, className = 'task-meta kpi-formula') {
  const line = node('p', className, `Формула: ${plainFormula(metric)}`);
  if (metric?.formula) line.title = `Точный расчёт: ${metric.formula}`;
  return line;
}
