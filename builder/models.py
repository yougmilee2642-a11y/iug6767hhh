from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import Field, model_validator, ConfigDict
from agents.models import StrictModel
from services.business_hours import validate_schedule


class BuilderModel(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ServiceInput(BuilderModel):
    name: str = Field(min_length=1, max_length=100)
    price: float = Field(ge=0, allow_inf_nan=False)
    currency: str = Field(default="BYN", pattern=r"^[A-Z]{3}$")
    duration_minutes: int = Field(ge=1, le=1440)
    employees: list[str] = Field(default_factory=list, max_length=30,
        description="Ссылки по имени на общий каталог BusinessInput.employees; пустой список означает всех сотрудников.")


class BusinessInput(BuilderModel):
    business_name: str = Field(min_length=2, max_length=100)
    business_type: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=2000)
    website: str = Field(default="", max_length=500)
    city: str = Field(min_length=2, max_length=100)
    timezone: str = Field(default="Europe/Minsk", max_length=100)
    schedule: dict[str, list[dict[str, str]]]
    services: list[ServiceInput] = Field(default_factory=list, max_length=50)
    employees: list[str] = Field(default_factory=list, max_length=30,
        description="Единый каталог сотрудников бизнеса. Услуги не создают сотрудников.")
    desired_role: str = Field(default="Администратор", min_length=2, max_length=100)
    tasks: list[str] = Field(min_length=1, max_length=20)
    escalation_preferences: list[Literal["complaint", "unsupported", "tool_failure"]] = Field(default_factory=lambda: ["complaint", "unsupported", "tool_failure"])
    notes: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def valid_business(self):
        try:
            ZoneInfo(self.timezone)
            validate_schedule(self.schedule)
            if len(self.schedule) > 7 or sum(len(w) for w in self.schedule.values()) > 28:
                raise ValueError("Слишком много рабочих интервалов")
        except Exception:
            raise ValueError("Проверьте IANA timezone и недельное расписание (дни 0–6, start/end)")
        if any(not t.strip() or len(t) > 500 for t in self.tasks):
            raise ValueError("Задачи должны быть непустыми и не длиннее 500 символов")
        if any(not e.strip() or len(e) > 100 for e in self.employees):
            raise ValueError("Проверьте имена сотрудников")
        return self


FieldType = Literal["person_name", "phone", "email", "free_text", "number", "address", "choice"]


class DraftField(BuilderModel):
    label: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=3, max_length=240)
    type: FieldType
    required: bool
    choices: list[str] = Field(max_length=20)


class BuilderDraft(BuilderModel):
    agent_name: str = Field(min_length=2, max_length=120)
    role_name: str = Field(min_length=2, max_length=100)
    business_summary: str = Field(max_length=1000)
    scenarios: list[str] = Field(min_length=1, max_length=5)
    tools: list[str] = Field(max_length=3)
    fields: list[DraftField] = Field(max_length=12)
    conversation_style: Literal["brief", "friendly", "formal"]
    escalation_reasons: list[Literal["complaint", "unsupported", "tool_failure"]]
    unsupported_requirements: list[str] = Field(max_length=20)
