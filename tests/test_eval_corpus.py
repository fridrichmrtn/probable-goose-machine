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


def test_summarize_growth_ok_degraded_failed() -> None:
    from types import SimpleNamespace

    from gander.errors import StageFailure

    growth_events: list[dict[str, object]] = [
        {"stage": "growth", "event": "growth_action_dropped", "reason": "unverified_anchor"},
        {"stage": "growth", "event": "growth_action_dropped", "reason": "unverified_anchor"},
        {"stage": "growth", "event": "growth_action_dropped", "reason": "ban_phrase"},
        {"stage": "growth", "event": "growth_retry", "reason": "insufficient_verified_actions"},
        {"stage": "growth", "event": "growth_degraded", "count": 1},
    ]

    ok = eval_corpus._summarize_growth(SimpleNamespace(growth=["a", "b", "c"]), [])
    assert ok.status == "ok"
    assert ok.drops_by_reason == {}
    assert ok.retries == 0
    assert eval_corpus._format_growth_drops(ok) == "-"

    degraded = eval_corpus._summarize_growth(SimpleNamespace(growth=["a"]), growth_events)
    assert degraded.status == "degraded"
    assert degraded.drops_by_reason == {"unverified_anchor": 2, "ban_phrase": 1}
    assert degraded.retries == 1
    assert eval_corpus._format_growth_drops(degraded) == "ban_phrase:1, unverified_anchor:2"

    failure = StageFailure(stage="growth", user_message="Could not generate this section reliably")
    failed = eval_corpus._summarize_growth(SimpleNamespace(growth=failure), growth_events)
    assert failed.status == "failed"

    missing = eval_corpus._summarize_growth(SimpleNamespace(growth=None), [])
    assert missing.status == "failed"


def test_growth_failure_exit_threshold() -> None:
    # Exactly at the 25% threshold is acceptable; only strictly above fails.
    assert eval_corpus._growth_failure_rate_exceeded(["ok", "ok", "ok", "failed"]) is False
    assert eval_corpus._growth_failure_rate_exceeded(["ok", "ok", "failed", "failed"]) is True
    # Degraded partial lists are not failures (PRD §4.5).
    assert eval_corpus._growth_failure_rate_exceeded(["degraded"] * 4) is False
    assert eval_corpus._growth_failure_rate_exceeded([]) is False
