from __future__ import annotations

import pytest
from scripts import eval_corpus

pytestmark = pytest.mark.fast


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_key in (
        "GANDER_LLM_PROVIDER",
        *eval_corpus.LOGICAL_PROVIDER_ENV_KEYS,
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env_key, raising=False)


def test_provider_key_preflight_defaults_to_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)

    error = eval_corpus._provider_key_error()

    assert error is not None
    assert "OPENROUTER_API_KEY" in error
    assert "GANDER_LLM_PROVIDER=openrouter" in error


def test_provider_key_preflight_accepts_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    assert eval_corpus._provider_key_error() is None


def test_provider_key_preflight_checks_logical_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GANDER_LLM_PROVIDER_EXTRACT", "minimax")

    error = eval_corpus._provider_key_error()

    assert error is not None
    assert "Unknown GANDER_LLM_PROVIDER_EXTRACT='minimax'" in error
    assert "'openrouter'" in error


def test_provider_key_preflight_rejects_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "anthropic")

    error = eval_corpus._provider_key_error()

    assert error is not None
    assert "Unknown GANDER_LLM_PROVIDER='anthropic'" in error
    assert "'openrouter'" in error


def test_provider_upload_requires_explicit_consent() -> None:
    error = eval_corpus._provider_upload_consent_error(False)

    assert error is not None
    assert "--allow-provider-upload" in error
    assert eval_corpus._provider_upload_consent_error(True) is None
