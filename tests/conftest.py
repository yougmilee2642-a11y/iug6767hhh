"""Tests must never poll the user's real Telegram bot or inherit owner access."""
import pytest


@pytest.fixture(autouse=True)
def isolate_optional_integrations(monkeypatch):
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','false')
    monkeypatch.setenv('AI_PROVIDER','groq')
    monkeypatch.setenv('TELEGRAM_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','')
    monkeypatch.setenv('TELEGRAM_MINIAPP_URL','')
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','')
    monkeypatch.setenv('CALLWISE_CLOUD_INTEGRATIONS_ENABLED','false')
    monkeypatch.setenv('CALLWISE_INTEGRATIONS_FILE','')
    # Legacy fixtures intentionally exercise the pre-consent runtime in isolation.
    # Customer-safety tests explicitly enable the default live policy and test both paths.
    monkeypatch.setenv('CALLWISE_CONVERSATION_SAFETY','false')
