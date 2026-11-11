// Fixed public demo data for the concept page. There is no browser repository any more:
// the page never writes to localStorage. STORAGE_KEY is the key the old mock cabinet used;
// it is kept only so the real cabinet's draft importer (static/product.js) and tests agree on it.
export const STORAGE_KEY = "callwise-mts-shell-v1";
export const QA_SEED = [
  {
    id: "balance",
    question: "Как проверить баланс?",
    answer:
      "Посмотреть состояние счёта можно в приложении «Мой МТС». В прототипе я не вижу ваш счёт и не могу сообщить остаток. Подробности — в официальной справке МТС.",
    source: "https://www.mts.by/help/oplata/proverka-balansa/",
  },
  {
    id: "internet",
    question: "Не работает интернет",
    answer:
      "Для проверки подключения откройте официальный раздел настроек интернета МТС. Здесь демонстрируется справочный ответ: я не проверяю вашу SIM-карту или состояние сети.",
    source: "https://www.mts.by/help/internet/nastroiki/",
  },
  {
    id: "human",
    question: "Хочу поговорить с оператором",
    answer:
      "В реальном помощнике здесь появится передача обращения человеку. В этой демке оператор не подключается и обращение никуда не отправляется.",
    source: "",
  },
];
export const SEED_AGENTS = [
  {
    id: "mts-support",
    name: "Помощник МТС",
    company: "МТС · демонстрация",
    role: "Поддержка клиентов",
    description:
      "Отвечает на типовые вопросы о связи и показывает сценарий помощи клиенту.",
    greeting: "Здравствуйте! Я демо-помощник МТС. Чем могу помочь?",
    status: "active",
    tone: "Дружелюбный",
    voice: "Женский",
    speed: "1.2",
    color: "red",
    icon: "spark",
    knowledge:
      "Публичные справочные материалы МТС. Это заготовленные Q&A, не обучение модели.",
    qa: QA_SEED,
  },
  {
    id: "business-intake",
    name: "Приём обращений",
    company: "Демо-компания",
    role: "Сбор обращений",
    description:
      "Знакомится с клиентом и помогает оформить запрос на обратный звонок.",
    greeting:
      "Здравствуйте! Я помощник демо-компании. Как к вам обращаться? Используйте вымышленные данные.",
    status: "active",
    tone: "Деловой",
    voice: "Женский",
    speed: "1.2",
    color: "slate",
    icon: "phone",
    knowledge:
      "Сценарий обратного звонка. Реальные обращения пока не отправляются.",
    qa: [],
  },
  {
    id: "salon-demo",
    name: "Администратор салона",
    company: "Салон · пример",
    role: "Информация об услугах",
    description:
      "Черновик помощника: добавьте услуги, ответы и правила общения.",
    greeting:
      "Здравствуйте! Это демонстрация помощника салона. Что вас интересует?",
    status: "draft",
    tone: "Дружелюбный",
    voice: "Женский",
    speed: "1.2",
    color: "amber",
    icon: "user",
    knowledge: "Информация об услугах ещё не добавлена.",
    qa: [],
  },
];
export function safeSource(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "www.mts.by"
      ? url.href
      : "";
  } catch {
    return "";
  }
}
export function escapeHTML(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
