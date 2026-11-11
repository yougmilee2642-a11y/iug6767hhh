"""Provider-neutral orchestration; trusted evidence and consent are server-owned."""
import hashlib
import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from jsonschema import validate, ValidationError
from agents.models import AgentConfig
from agents.prompts import build_system_prompt
from agents.fields import collect_user, verify_action, confirmation
from agents.validation import require_valid
from services.call_summary import intake_summary
from providers.base import LLMProvider, ToolCall, ConversationMessage
from providers.language import is_confirmation, is_explicit_handoff
from tools.base import ToolContext, ToolInputError, FieldEvidenceRequired
from tools.registry import ToolRegistry
from services import customer_safety
from services.review_requests import enqueue as enqueue_review
from agents.booking_dialogue import booking_fallback, booking_interruption, update_booking_flow
from agents.quick_dialogue import quick_interruption, CALLBACK_DECLINED


def new_interaction(config: AgentConfig):
    state = {"id": str(uuid.uuid4()), "agent_id": config.id, "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active", "customer_name": None, "phone": None, "intent": None, "summary": "",
            "result": "", "structured_data": {}, "collected_fields": {},
            "transcript": [{"role": "assistant", "content": config.greeting}],
            "escalation": None, "tool_events": [],
            "llm_history": [asdict(ConversationMessage("assistant", config.greeting))],
            "pending_action": None, "pending_collection": None, "runtime_version": 2,
            "agent_config": config.model_dump(), "email_sent": False, "email_error": None}
    for field in config.fields:
        if 'user' in field.allowed_sources and config.greeting.endswith(field.question):
            state['pending_collection'] = {'field_id': field.id, 'question_index': 0}
            break
    customer_safety.initialize(state, config)
    update_booking_flow(state, config)
    return state


def fingerprint(name, arguments):
    return hashlib.sha256(json.dumps([name, arguments], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AgentRuntime:
    def __init__(self, config: AgentConfig, provider: LLMProvider, tools, registry=None):
        registry = registry or ToolRegistry.from_tools(tools)
        require_valid(config, registry)
        self.config, self.provider = config, provider
        allowed = {policy.name for policy in config.tools}
        self.tools = {tool.name: tool for tool in tools if tool.name in allowed}
        if allowed - self.tools.keys():
            raise ValueError("В конфигурации есть неизвестные инструменты")

    def context(self, state):
        return ToolContext(state["id"], self.config, state["transcript"], state["structured_data"],
                           state["tool_events"], state.setdefault("collected_fields", {}), state.get("action_provenance", {}))

    def apply(self, state, result):
        state["structured_data"].update(result.data.get("structured_data", {}))
        # Legacy summary projection only, not evidence or action validation.
        state["customer_name"] = state["structured_data"].get("customer_name")
        state["phone"] = state["structured_data"].get("phone")
        state["intent"] = result.data.get("intent", state["intent"])
        if result.data.get("escalation"):
            state["escalation"] = result.data["escalation"]
        if result.data.get("booking"):
            state["structured_data"]["booking_id"] = result.data["booking"]["id"]
        if result.data.get("action_result"):
            state["action_result"] = result.data["action_result"]
        if result.status:
            state["status"] = result.status
            state["result"] = result.text
            if result.status in {"completed", "escalated", "stopped"}:
                state.update(pending_action=None, pending_collection=None)

    def append_history(self, state, message):
        state["llm_history"].append(asdict(message))

    def dispatch(self, call, state, confirmed=False):
        if not customer_safety.accepted(state):
            return {'error': 'Нет согласия на обработку разговора. Действие запрещено.'}, ''
        tool = self.tools.get(call.name)
        data, text = {}, ""
        if state.get('declined_actions', {}).get(call.name):
            data = {'error': 'Клиент отказался от этого действия. Нужен новый явный запрос.'}
            text = ('Запись не создана. Если захотите оформить новую, скажите об этом.'
                    if call.name == 'create_booking' else CALLBACK_DECLINED)
            state['tool_events'].append({'id': call.id, 'name': call.name, 'arguments': call.arguments,
                                        'result': data, 'confirmed': False,
                                        'created_at': datetime.now(timezone.utc).isoformat()})
            return data, text
        if not tool:
            data = {"error": "Инструмент не разрешён"}
        else:
            policy = next(p for p in self.config.tools if p.name == call.name)
            requires = (policy.requires_confirmation or tool.requires_confirmation or
                        tool.always_requires_confirmation or (not tool.read_only and tool.kind != "escalation"))
            try:
                if requires:
                    if tool.prepare is None:
                        raise ValueError("У действия нет безопасной подготовки подтверждения")
                    if confirmed:
                        pending = state.get("pending_action")
                        if not pending or pending.get("digest") != fingerprint(call.name, call.arguments):
                            raise ValueError("Нет подтверждения конкретного предложения")
                        index = pending.get("consent_turn", -1)
                        if (not isinstance(index, int) or index != len(state["transcript"]) - 1 or
                            index != pending["question_index"] + 1 or
                            state["transcript"][pending["question_index"]]["content"] != pending["text"] or
                            not is_confirmation(state["transcript"][index]["content"], self.config.language)):
                            raise ValueError("Нет явного согласия на последнее предложение")
                        verify_action(state, self.config, dict(call.arguments))
                        for key in call.arguments:
                            if key in state["collected_fields"]:
                                state["collected_fields"][key]["confirmed"] = True
                            if key in state.get("action_provenance", {}):
                                state["action_provenance"][key]["confirmed"] = True
                        result = tool.execute(call.arguments, self.context(state))
                        state["pending_action"] = None
                        self.apply(state, result)
                        data, text = result.data, result.text
                    else:
                        validate(call.arguments, tool.parameters)
                        # Rebuild declarations only from authoritative user turns (also supports restored state).
                        for index, message in enumerate(state["transcript"]):
                            if message["role"] == "user":
                                collect_user(state, self.config, message["content"], index, bind=False)
                        result = tool.prepare(call.arguments, self.context(state))
                        values = verify_action(state, self.config, dict(result.data))
                        state["action_provenance"] = {
                            key: state["collected_fields"].get(key) or {"field_id": key, "value": value,
                                **result.provenance.get(key, {"source": "system", "evidence": {"producer": tool.name + ".prepare"}}),
                                "confirmed": False} for key, value in values.items()}
                        state["action_labels"] = {key: prop.get("title", key) for key, prop in tool.parameters.get("properties", {}).items()}
                        text = confirmation(self.config, tool, values)
                        state["pending_action"] = {"name": call.name, "arguments": values, "text": text,
                            "digest": fingerprint(call.name, values), "question_index": len(state["transcript"])}
                        state["status"] = "awaiting_confirmation"
                        self.apply(state, type(result)({"structured_data": values}))
                        data = {"confirmation_required": True, "proposal": values}
                else:
                    validate(call.arguments, tool.parameters)
                    result = tool.execute(call.arguments, self.context(state))
                    self.apply(state, result)
                    data, text = result.data, result.text
            except FieldEvidenceRequired as error:
                state["pending_action"] = None
                state["status"] = "active"
                state["pending_collection"] = {"field_id": error.field_id, "question_index": len(state["transcript"])}
                data, text = {"error": str(error), "field_id": error.field_id}, error.question
            except ToolInputError as error:
                data, text = {"error": str(error)}, error.question
            except ValidationError:
                data = {"error": "Аргументы инструмента не соответствуют JSON Schema"}
            except (ValueError, KeyError, TypeError) as error:
                data = {"error": str(error)}
        state["tool_events"].append({"id": call.id, "name": call.name, "arguments": call.arguments,
            "result": data, "confirmed": confirmed and "error" not in data,
            "created_at": datetime.now(timezone.utc).isoformat()})
        return data, text

    def respond(self, state, text):
        if not text.strip():
            raise ValueError("AI вернул пустой ответ")
        state["transcript"].append({"role": "assistant", "content": text})
        self.append_history(state, ConversationMessage("assistant", text))
        # An exact schema question creates a collection binding even when proposed by the model.
        for field in self.config.fields:
            if text.strip().endswith(field.question.strip()) and "user" in field.allowed_sources:
                state["pending_collection"] = {"field_id": field.id, "question_index": len(state["transcript"]) - 1}
        state["summary"] = "\n".join(f"{m['role']}: {m['content']}" for m in state["transcript"])[-6000:]
        brief = intake_summary(state)
        if brief is not None:
            state['brief_summary'] = brief
        update_booking_flow(state,self.config)
        return {"text": text, "complete": state["status"] in {"completed", "escalated", "stopped"}, "status": state["status"]}

    def turn(self, state, text):
        if state["status"] in {"completed", "escalated", "stopped"}:
            return {"text": state["result"], "complete": True, "status": state["status"]}
        if state.get("runtime_version") != 2:
            raise ValueError("Начните новый разговор: старое предложение не содержит проверяемого provenance")
        safe_text, direct, terminal, review = customer_safety.preflight(state, self.config, text)
        if direct:
            if not customer_safety.accepted(state):
                return {'text': direct, 'complete': terminal, 'status': state['status']}
            if safe_text:
                state['transcript'].append({'role': 'user', 'content': safe_text})
                self.append_history(state, ConversationMessage('user', safe_text))
            if review:
                state['review_request'] = enqueue_review(state, review)
            if terminal: state.update(status='stopped', result=direct)
            return self.respond(state, direct)
        text = safe_text
        state["transcript"].append({"role": "user", "content": text})
        self.append_history(state, ConversationMessage("user", text))
        if re.search(r'\b(?:до свидания|закончим разговор|завершить разговор|отказываюсь от (?:вашей )?услуги)\b', text, re.I):
            state.update(status='stopped', pending_action=None, pending_collection=None,
                         result='Разговор завершён. Неподтверждённые действия не выполнены.')
            return self.respond(state, state['result'])
        explicit = (self.config.escalation.explicit_human_request == "immediate" and
                    is_explicit_handoff(text, self.config.escalation.explicit_request_patterns))
        if explicit:
            state.update(pending_action=None, pending_collection=None)
            data, answer = self.dispatch(ToolCall(str(uuid.uuid4()), self.config.escalation.tool,
                {"reason": "explicit_user_request", "summary": "Explicit human request",
                 "reason_type": "explicit_user_request"}), state)
            if "error" in data:
                raise ValueError(data["error"])
            return self.respond(state, answer)
        direct = quick_interruption(self, state, text)
        if direct is not None:
            state['pending_collection'] = None
            return self.respond(state, direct)
        pending = state.get("pending_action")
        if pending and is_confirmation(text, self.config.language):
            pending["consent_turn"] = len(state["transcript"]) - 1
            data, answer = self.dispatch(ToolCall(str(uuid.uuid4()), pending["name"], pending["arguments"]), state, True)
            if "error" not in data:
                return self.respond(state, answer)
            state["pending_action"] = None
            if pending['name']=='create_booking':state['booking_calendar_refresh']=True
            self.append_history(state, ConversationMessage("system", f"Действие НЕ выполнено: {data['error']}"))
        else:
            state["pending_action"] = None
        state["status"] = "active"
        # Collect explicit declarations before a multi-fact booking is routed.
        # Never bind the whole interruption as an answer to a contact question.
        collect_user(state, self.config, text, len(state['transcript']) - 1, bind=False)
        direct = booking_interruption(self, state, text)
        if direct is not None:
            state['pending_collection'] = None
            # Explicit declarations in an interruption remain valid evidence.
            collect_user(state, self.config, text, len(state['transcript']) - 1, bind=False)
            return self.respond(state, direct)
        try:
            collect_user(state, self.config, text, len(state["transcript"]) - 1)
        except ToolInputError as error:
            return self.respond(state, error.question)
        if state.get('booking_preferences'):
            answer = booking_fallback(self, state, text)
            if answer is not None:
                return self.respond(state, answer)
        schemas = [tool.schema() for tool in self.tools.values()]
        for _ in range(6):
            messages = [ConversationMessage("system", build_system_prompt(self.config))]
            for item in state["llm_history"]:
                message = ConversationMessage(**item)
                message.calls = [ToolCall(**c) for c in message.calls]
                messages.append(message)
            known = {key: {"value": item["value"], "source": item["source"], "confirmed": item["confirmed"]}
                     for key, item in state["collected_fields"].items()}
            messages.append(ConversationMessage("system", "Проверенные собранные поля: " +
                            json.dumps(known, ensure_ascii=False)))
            if self.config.business.knowledge.get('track1_quick') is True:
                missing = next((field for field in self.config.fields
                                if field.required and 'user' in field.allowed_sources and field.id not in known), None)
                if missing:
                    messages.append(ConversationMessage('system',
                        'Текущий шаг приёма обращения: не повторяй собранные поля. '
                        'Если клиент отвечает на сбор данных, верни только следующий вопрос без добавлений: '
                        + missing.question + ' Не спрашивай дату или время: это обратный звонок, не запись.'))
                else:
                    messages.append(ConversationMessage('system',
                        'Все обязательные поля обращения проверены. Сейчас вызови инструмент save_callback_request '
                        'со значениями проверенных полей без изменений. Не задавай новые вопросы. '
                        'Это только подготовка предложения: сервер отдельно запросит согласие перед сохранением.'))
            reply = self.provider.complete(messages, schemas)
            if not reply.tool_calls:
                # Preserve useful schema questions after a real availability check.
                if (any(e['name'] == 'check_slots' and 'slots' in e['result'] for e in state['tool_events'])
                        and any(reply.text.strip() == f.question.strip() and 'user' in f.allowed_sources
                                and f.id not in state['collected_fields'] for f in self.config.fields)):
                    return self.respond(state, reply.text)
                if re.search(r'услуг\w*.{0,30}не могу|не могу.{0,30}услуг', reply.text, re.I):
                    return self.respond(state, reply.text)
                answer = booking_fallback(self, state, text)
                return self.respond(state, answer if answer is not None else reply.text)
            self.append_history(state, ConversationMessage("assistant", reply.text, reply.tool_calls))
            answer = ""
            for call in reply.tool_calls:
                if state["status"] in {"awaiting_confirmation", "completed", "escalated"} or answer:
                    data = {"error": "Дополнительное действие в этом ответе не разрешено"}
                else:
                    data, tool_text = self.dispatch(call, state)
                    answer = tool_text or answer
                self.append_history(state, ConversationMessage("tool", call_id=call.id, result=data))
            if answer or state["status"] in {"awaiting_confirmation", "completed", "escalated"}:
                return self.respond(state, answer)
        raise ValueError("AI превысил лимит действий за одну реплику. Попробуйте уточнить запрос.")
