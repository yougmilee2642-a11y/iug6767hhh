"""Mock handoff: persist context, never claim a live connection."""
import json
from datetime import datetime, timezone
from providers.language import is_explicit_handoff
import storage
from tools.base import BusinessTool, ToolResult


def handoff_tool():
    def transfer(arguments, context):
        policy = context.config.escalation
        last_request = next((m["content"] for m in reversed(context.transcript) if m["role"] == "user"), "")
        explicit = (policy.explicit_human_request == "immediate" and
                    is_explicit_handoff(last_request, policy.explicit_request_patterns))
        reason_type = "explicit_user_request" if explicit else arguments.get("reason_type", "")
        if not explicit and policy.agent_initiated.get(reason_type) != "allowed":
            raise ValueError("Этот тип escalation не разрешён policy; выбор мастера не является запросом человека.")
        if reason_type == "tool_failure" and sum("error" in e["result"] for e in context.tool_events[-4:]) < 2:
            raise ValueError("Повторные ошибки инструмента не зафиксированы")
        summary = "\n".join(f"{m['role']}: {m['content']}" for m in context.transcript)[-6000:]
        event = {"reason": reason_type, "reason_type": reason_type, "agent_id": context.config.id,
                 "summary": summary, "customer_data": dict(context.structured_data),
                 "collected_fields": dict(context.collected_fields),
                 "created_at": datetime.now(timezone.utc).isoformat()}
        event["customer_data"]["transcript"] = context.transcript
        with storage.connect() as db:
            db.execute("""INSERT OR IGNORE INTO escalations
                (interaction_id, reason, summary, customer_data, created_at, reason_type, agent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (context.interaction_id, event["reason"], event["summary"],
                 json.dumps({**event["customer_data"], "collected_fields": event["collected_fields"]}, ensure_ascii=False),
                 event["created_at"], reason_type, context.config.id))
        return ToolResult({"escalation": event, "intent": "Запрос сотрудника"}, "escalated", policy.acknowledgement)
    return BusinessTool("transfer_to_human",
        "Зафиксировать запрос сотруднику без реального соединения. Явная просьба: explicit_user_request. "
        "Agent-initiated reason_type должен быть разрешён escalation policy. Не удерживай клиента.",
        {"type": "object", "properties": {"reason": {"type": "string"}, "summary": {"type": "string"},
                                         "reason_type": {"type": "string"}},
         "required": ["reason", "summary"], "additionalProperties": False}, transfer,
        read_only=False, risk_level="medium", kind="escalation", required_capabilities=("human_handoff",))
