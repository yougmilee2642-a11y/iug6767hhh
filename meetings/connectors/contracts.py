"""Normalized CRM boundary; no credentials, URLs or provider response bodies."""
from typing import Any, Protocol, TypedDict
from integrations.contracts import IntegrationError


class SourceValue(TypedDict):
    source_id: str
    fetched_at: str
    as_of: str
    stale: bool


class ExternalRef(SourceValue):
    ref: str


class CRMConnector(Protocol):
    name: str

    def get_employee(self, external_id: str) -> dict | None: ...
    def list_departments(self) -> list[dict]: ...
    def get_customer(self, customer_id: str) -> dict | None: ...
    def get_order(self, order_no: str) -> dict | None: ...
    def find_interactions(self, *, order_no: str | None = None, customer_id: str | None = None) -> list[dict]: ...
    def create_task(self, draft: dict[str, Any], idempotency_key: str) -> ExternalRef: ...
    def get_task_status(self, ref: str) -> dict | None: ...
    def attach_protocol(self, entity_ref: str, protocol: dict, idempotency_key: str) -> ExternalRef: ...


__all__ = ['CRMConnector', 'ExternalRef', 'SourceValue', 'IntegrationError']
