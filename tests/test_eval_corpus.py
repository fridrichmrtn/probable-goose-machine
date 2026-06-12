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
    assert ok.attempt_errors == {}
    assert ok.failure_reason is None
    assert eval_corpus._format_growth_drops(ok) == "-"

    degraded = eval_corpus._summarize_growth(SimpleNamespace(growth=["a"]), growth_events)
    assert degraded.status == "degraded"
    assert degraded.drops_by_reason == {"unverified_anchor": 2, "ban_phrase": 1}
    assert degraded.retries == 1
    assert (
        eval_corpus._format_growth_drops(degraded) == "ban_phrase:1, unverified_anchor:2, retries:1"
    )

    failure = StageFailure(stage="growth", user_message="Could not generate this section reliably")
    failed = eval_corpus._summarize_growth(SimpleNamespace(growth=failure), growth_events)
    assert failed.status == "failed"

    missing = eval_corpus._summarize_growth(SimpleNamespace(growth=None), [])
    assert missing.status == "failed"


def _pipeline_growth_cascade_messages() -> list[str]:
    from gander import pipeline

    return [
        pipeline._CASCADE_PROFILE_FAILED["growth"],
        pipeline._GROWTH_NO_BASELINE,
        pipeline._GROWTH_NEEDS_SCORE,
        pipeline._GROWTH_NEEDS_SALARY,
    ]


@pytest.mark.parametrize("message", _pipeline_growth_cascade_messages())
def test_summarize_growth_marks_upstream_cascade_as_skipped(message: str) -> None:
    from types import SimpleNamespace

    from gander.errors import StageFailure

    cascade = StageFailure(stage="growth", user_message=message)
    stats = eval_corpus._summarize_growth(SimpleNamespace(growth=cascade), [])
    assert stats.status == "skipped"


def test_summarize_growth_marks_ingest_cascade_as_skipped() -> None:
    # Ingest/redact cascades carry no growth-cascade prefix, but profile also
    # failed — growth provably never ran, so the row must not blame growth.
    from types import SimpleNamespace

    from gander.errors import StageFailure

    report = SimpleNamespace(
        growth=StageFailure(stage="growth", user_message="Cannot run without successful ingest."),
        profile=StageFailure(stage="extract", user_message="Could not parse this CV"),
    )
    stats = eval_corpus._summarize_growth(report, [])
    assert stats.status == "skipped"


def test_summarize_growth_genuine_failure_with_profile_ok_stays_failed() -> None:
    from types import SimpleNamespace

    from gander.errors import StageFailure

    report = SimpleNamespace(
        growth=StageFailure(
            stage="growth", user_message="Could not generate this section reliably"
        ),
        profile=SimpleNamespace(experience=[]),
    )
    stats = eval_corpus._summarize_growth(report, [])
    assert stats.status == "failed"


def test_summarize_growth_captures_attempt_errors_and_failure_reason() -> None:
    from types import SimpleNamespace

    from gander.errors import StageFailure

    growth_events: list[dict[str, object]] = [
        {"stage": "growth", "event": "growth_attempt_error", "reason": "llm_error"},
        {"stage": "growth", "event": "growth_attempt_error", "reason": "llm_error"},
        {
            "stage": "growth",
            "event": "stage_failure",
            "reason": "insufficient_verified_actions",
        },
    ]
    failure = StageFailure(stage="growth", user_message="Could not generate this section reliably")
    stats = eval_corpus._summarize_growth(SimpleNamespace(growth=failure), growth_events)

    assert stats.status == "failed"
    assert stats.attempt_errors == {"llm_error": 2}
    assert stats.failure_reason == "insufficient_verified_actions"
    assert (
        eval_corpus._format_growth_drops(stats)
        == "attempt_error[llm_error]:2, failure:insufficient_verified_actions"
    )


def test_format_growth_drops_includes_retries() -> None:
    stats = eval_corpus.GrowthStats(
        status="degraded",
        drops_by_reason={"unverified_anchor": 1},
        retries=1,
        attempt_errors={},
    )
    assert eval_corpus._format_growth_drops(stats) == "unverified_anchor:1, retries:1"


def test_growth_failure_exit_threshold() -> None:
    # Exactly at the 25% threshold is acceptable; only strictly above fails.
    assert eval_corpus._growth_failure_rate_exceeded(["ok", "ok", "ok", "failed"]) is False
    assert eval_corpus._growth_failure_rate_exceeded(["ok", "ok", "failed", "failed"]) is True
    # Degraded partial lists are not failures (PRD §4.5).
    assert eval_corpus._growth_failure_rate_exceeded(["degraded"] * 4) is False
    assert eval_corpus._growth_failure_rate_exceeded([]) is False


def test_growth_failure_exit_threshold_excludes_skipped() -> None:
    # Upstream cascade skips leave both numerator and denominator: a corpus
    # where salary failed upstream must not fail CI blaming growth.
    assert eval_corpus._growth_failure_rate_exceeded(["ok", "skipped", "skipped"]) is False
    assert eval_corpus._growth_failure_rate_exceeded(["failed", "skipped", "skipped", "ok"]) is True
    assert eval_corpus._growth_failure_rate_exceeded(["skipped"] * 3) is False
