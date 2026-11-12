import { icon, fillIcons } from "./icons.mjs";
import { SEED_AGENTS, escapeHTML as esc, safeSource } from "./adapter.mjs";
import { LocalVoiceSession } from "./local-voice.mjs";
import { controlsLocked } from "./voice-controls.mjs";
import { cabinetTarget } from "../cabinet-links.mjs";
// Public concept page only. The one real owner workspace lives at "/" (see cabinet-links.mjs);
// this file keeps the fixed public demo, the about dialog and old #cabinet deep-link redirects.
// It never reads or writes the browser's old draft storage.
const $ = (selector) => document.querySelector(selector);
const modal = $("#modal");
let voice = null,
  voiceJob = 0,
  toastTimer;
const btn = (label, action, extra = "", type = "btn-white") =>
  `<button class="btn ${type}" data-action="${action}" ${extra}>${label}</button>`;
// A missing or unreachable server is shown as an error; the page never substitutes a canned answer.
const NETWORK = /failed to fetch|networkerror|load failed|network request failed/i;
function explain(error, fallback = "Не удалось выполнить действие.") {
  const message = String(error?.message || "");
  if (error?.name === "TypeError" || NETWORK.test(message))
    return "Сервер Фокус недоступен, ответ не получен. Запустите локальный сервер и повторите. Заготовленных ответов здесь нет.";
  return message || fallback;
}
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("#toast").hidden = true), 4000);
}
function showModal(title, body, footer = "", subtitle = "", className = "") {
  modal.className = className;
  $("#modalContent").innerHTML =
    `<div class="modal-head"><div><h2 id="modalTitle">${esc(title)}</h2>${subtitle ? `<small>${esc(subtitle)}</small>` : ""}</div><button class="icon-btn" data-action="close" aria-label="Закрыть окно">${icon("close")}</button></div>${body}${footer ? `<div class="modal-footer">${footer}</div>` : ""}`;
  fillIcons(modal);
  if (!modal.open) modal.showModal();
}
function closeModal() {
  if (voice) stopVoice(false);
  modal.close();
}
modal.addEventListener("cancel", () => {
  if (voice) stopVoice(false);
});
modal.addEventListener("close", () => {
  if (voice) stopVoice(false);
});
function route() {
  const hash = location.hash || "#home";
  const destination = cabinetTarget(hash);
  if (destination) {
    location.replace(destination);
    return;
  }
  if (hash === "#main") {
    $("#main").focus();
    return;
  }
  const parts = hash.slice(1).split("/");
  if (parts[0] !== "home" && parts[0]) {
    location.hash = "home";
    return;
  }
  document.title = "Фокус — голосовой помощник · Прототип";
  const section = ["demo", "how", "faq"].includes(parts[1]) ? parts[1] : "";
  requestAnimationFrame(() =>
    section
      ? document.getElementById(section).scrollIntoView()
      : window.scrollTo({ top: 0 }),
  );
}
window.addEventListener("hashchange", () => {
  if (modal.open) closeModal();
  try {
    route();
  } catch (error) {
    toast(explain(error));
  }
});
const waveform = () =>
  `<div class="small-sphere"><div class="waveform" aria-hidden="true">${"<i></i>".repeat(7)}</div></div>`;
function messageHTML(m) {
  const source = safeSource(m.source);
  return `<div class="bubble ${m.role === "user" ? "user" : m.role === "system" ? "system" : ""}"><small>${m.role === "user" ? "Вы" : m.role === "system" ? "О прототипе" : "Фокус · демо"}</small>${esc(m.text)}${source ? `<br><a href="${esc(source)}" target="_blank" rel="noopener noreferrer">Официальная справка МТС ↗</a>` : ""}</div>`;
}
async function openVoice(agentId = "mts-support", topic) {
  if (voice) stopVoice();
  // The public demo uses a fixed sample; old drafts require owner review in the real cabinet.
  const agent = structuredClone(SEED_AGENTS.find(a => a.id === agentId) || SEED_AGENTS[0]);
  voice = {
    agent,
    messages: [],
    state: "connecting",
    started: Date.now(),
    saved: false,
  };
  voiceJob++;
  showModal(
    "Разговор с локальным AI",
    `<div class="voice-layout state-connecting" id="voiceLayout"><div class="voice-stage">${waveform()}<h3>${esc(agent.name)}</h3><span class="voice-state" id="voiceState" role="status" aria-live="polite">Подключаю локальный AI…</span><button class="round-mic" data-action="voice-mic" aria-label="Микрофон разговора" aria-pressed="false" disabled>${icon("mic")}</button><span class="voice-timer">Автоматическое прослушивание · пауза 1 секунда</span>${btn(`${icon("voice")} Повторить ответ`, "voice-repeat", "", "btn-white btn-sm")}${btn(`${icon("stop")} Завершить`, "voice-end", "", "btn-white btn-sm")}</div><div class="chat-area"><div class="transcript" id="transcript" role="log" aria-live="polite"></div><form class="chat-form" id="chatForm"><input name="message" aria-label="Тестовый вопрос" placeholder="Или напишите вопрос…" maxlength="500" required autocomplete="off" disabled><button type="submit" aria-label="Отправить тестовый вопрос" disabled>${icon("send")}</button></form><div class="question-chips">${agent.qa
      .slice(0, 3)
      .map(
        (q) =>
          `<button data-action="voice-question" data-qid="${esc(q.id)}">${esc(q.question)}</button>`,
      )
      .join(
        "",
      )}</div></div></div><div class="voice-warning">После согласия и разрешения браузера микрофон включается автоматически. Говорите после приветствия; секунда тишины отправит фразу. После ответа AI прослушивание возобновится само. Кнопка микрофона отключает/возобновляет звук. Аудио обрабатывается локально, не отправляется МТС. Используйте вымышленные данные.</div>`,
    "",
    "Локальная Qwen · работает на вашем компьютере · без телефонии",
    "voice-modal",
  );
  const current = voice;
  current.controller = new LocalVoiceSession(agent, {
    state: (state, detail) => {
      if (voice === current) {
        setVoiceState(state, detail);
      }
    },
    message: (message) => {
      if (voice === current) appendMessage(message);
    },
    error: (message) => {
      if (voice === current) {
        if (current.controller.closed)
          setVoiceState(
            "ended",
            "Разговор завершён. Сохранение не подтверждено.",
          );
        const shown = explain({ message });
        appendMessage({ role: "system", text: shown });
        toast(shown);
      }
    },
    ended: async (result) => {
      if (voice !== current) return;
      if (result) {
        setVoiceState("ended", "Разговор завершён. Диалог сохранён локально.");
        current.saved = true; // The server owns history; no duplicate browser repository.
        if (voice !== current) return;
        appendMessage({
          role: "system",
          text:
            "Диалог сохранён на локальном сервере Фокус. " +
            (result.result || ""),
        });

      }
    },
  });
  setVoiceState("connecting");
  await current.controller.start();
  if (voice !== current) return;
  if (topic) {
    const question = agent.qa.find((q) => q.id === topic);
    if (question) $('#chatForm input').placeholder=question.question;
  }
}
function setVoiceState(state, detail = "") {
  if (!voice) return;
  voice.state = state;
  const labels = {
    connecting: "Подключаю локальный AI…",
    ready: "Готов. Прослушивание возобновится автоматически; можно написать вопрос.",
    listening: "Слушаю · пауза 1 секунда завершит фразу",
    transcribing: "Распознаю вашу речь локально…",
    thinking: "Локальная Qwen готовит ответ…",
    speaking: "Говорю · локальная озвучка Silero",
    ended: "Разговор завершён",
    completed: "Разговор остановлен. Новые действия недоступны.",
    error: "Ошибка. Можно повторить или продолжить текстом.",
  };
  const actualModel = voice.controller?.health?.model;
  if (actualModel) {
    const subtitle = $("#modalTitle")?.parentElement.querySelector("small");
    if (subtitle) subtitle.textContent = `${actualModel} · работает на вашем компьютере · без телефонии`;
    labels.thinking = `${actualModel} готовит ответ…`;
  }
  $("#voiceLayout").className = "voice-layout state-" + state;
  $("#voiceState").textContent = detail || labels[state];
  const locked = controlsLocked(state, voice.controller);
  $("#chatForm input").disabled = locked;
  $("#chatForm button").disabled = locked;
  document
    .querySelectorAll(
      '[data-action="voice-question"]',
    )
    .forEach((b) => (b.disabled = locked));
  const mic = $('[data-action="voice-mic"]');
  mic.disabled=!voice.controller?.privacyReady || voice.controller?.closed || voice.controller?.completed || voice.controller?.micPending;
  mic.setAttribute("aria-pressed", String(Boolean(voice.controller?.autoListen)));
  mic.setAttribute(
    "aria-label",
    voice.controller?.autoListen ? "Выключить микрофон" : "Возобновить разговор голосом",
  );
  $('[data-action="voice-repeat"]').disabled = locked || state === "listening";
  $('[data-action="voice-end"]').disabled = state === "ended";
}
function appendMessage(message) {
  voice.messages.push(message);
  $("#transcript").insertAdjacentHTML("beforeend", messageHTML(message));
  $("#transcript").scrollTop = $("#transcript").scrollHeight;
}
async function sendQuestion(text) {
  if (!voice?.controller || !text.trim()) return;
  $("#chatForm input").value = "";
  await voice.controller.send(text.trim().slice(0, 500));
}
async function finishVoice() {
  if (voice?.controller) await voice.controller.end();
}
function stopVoice() {
  voiceJob++;
  const controller = voice?.controller;
  voice = null;
  controller?.end();
}
function about() {
  showModal(
    "О прототипе Фокус",
    `<div class="modal-body about-copy"><p>Неофициальный прототип в стиле МТС Беларусь. Он не связан с личным кабинетом оператора и не подключает услуги.</p><p>Разговор работает с локальными Qwen, T-one, GigaAM и Silero. После согласия микрофон запрашивается автоматически; после каждого ответа помощник снова слушает. Фраза завершается после паузы в речи. Аудио не отправляется в облачный AI или МТС.</p><p>Личный кабинет открывает рабочее пространство Фокус с серверными помощниками и подтверждением настроек. Старые браузерные черновики переносятся явно через мастер. Телефония, вход через МТС ID и внешняя доставка не подключены.</p><p>Это контекст Q&A, а не fine-tuning модели. Полная база знаний МТС ещё не подготовлена. Используйте вымышленные данные.</p></div>`,
    `<small>Локальный голосовой тест</small>${btn("Понятно", "close", "", "btn-red")}`,
  );
}
document.addEventListener("click", async (event) => {
  const trigger = event.target.closest("[data-action]");
  if (!trigger || trigger.disabled) return;
  const { action, topic, qid } = trigger.dataset;
  try {
    if (action === "close") closeModal();
    else if (action === "about") about();
    else if (action === "create") location.assign("/#quick");
    else if (action === "demo" || action === "demo-topic")
      await openVoice("mts-support", topic);
    else if (action === "voice-mic") {
      await voice?.controller?.toggleMic();
    } else if (action === "voice-repeat") await voice?.controller?.repeat();
    else if (action === "voice-question") {
      const question = voice?.agent.qa.find((q) => q.id === qid);
      if (question) await sendQuestion(question.question);
    } else if (action === "voice-end") await finishVoice();
  } catch (error) {
    toast(explain(error));
  }
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.id !== "chatForm") return;
  event.preventDefault();
  const submit = form.querySelector('[type="submit"]');
  if (submit) submit.disabled = true;
  try {
    await sendQuestion(String(new FormData(form).get("message") || ""));
  } catch (error) {
    toast(explain(error, "Не удалось отправить вопрос."));
  } finally {
    if (submit?.isConnected) submit.disabled = voice?.state === "ended";
  }
});
fillIcons();
window.addEventListener("pagehide", () => voice?.controller?.end());
try {
  route();
} catch (error) {
  toast(explain(error));
}
