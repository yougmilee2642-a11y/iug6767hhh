from builder.catalog import SCENARIOS

DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def preview(config):
    return {"name": config.name, "business_name": config.business.name, "role": config.role.name,
        "abilities": [SCENARIOS[s.id].description for s in config.scenarios],
        "fields": [{"label": f.label, "question": f.question, "required": f.required} for f in config.fields if f.data_kind == "user"],
        "human_request": "Немедленно сохранить запрос человека" if "human_handoff" in config.business.capabilities else "Перевод сотруднику не подключён",
        "escalation_reasons": list(config.escalation.agent_initiated), "timezone": config.business.timezone,
        "hours": [DAYS[d] + ": " + (", ".join(w["start"] + "–" + w["end"] for w in config.business.schedule.get(str(d), [])) or "Выходной") for d in range(7)],
        "services": config.business.knowledge.get("services", []), "employees": config.business.knowledge.get("employees", [])}
