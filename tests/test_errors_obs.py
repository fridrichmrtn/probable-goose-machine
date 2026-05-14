from __future__ import annotations

from typing import Any

import pytest

from gander.errors import StageFailure, stage_boundary
from gander.obs import current_stage, subscribe

pytestmark = pytest.mark.fast


def test_sync_error_emits_event_with_stage_attribution() -> None:
    events: list[dict[str, Any]] = []
    with subscribe(events.append), stage_boundary("test_stage") as cm:
        raise RuntimeError("boom")
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    e = error_events[0]
    assert e["stage"] == "test_stage"
    assert e["exc_type"] == "RuntimeError"
    assert e["exc_message"] == "boom"
    assert isinstance(cm.failure, StageFailure)
    assert cm.failure.stage == "test_stage"


def test_current_stage_set_inside_block_and_reset_after_clean_exit() -> None:
    assert current_stage.get() is None
    with stage_boundary("test_stage"):
        assert current_stage.get() == "test_stage"
    assert current_stage.get() is None


def test_current_stage_reset_after_exception() -> None:
    with stage_boundary("s"):
        raise RuntimeError("boom")
    assert current_stage.get() is None


async def test_async_error_emits_event() -> None:
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        async with stage_boundary("test_stage_async") as cm:
            raise RuntimeError("async-boom")
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    e = error_events[0]
    assert e["stage"] == "test_stage_async"
    assert e["exc_type"] == "RuntimeError"
    assert e["exc_message"] == "async-boom"
    assert isinstance(cm.failure, StageFailure)


def test_stage_failure_shape_preserved() -> None:
    with stage_boundary("score") as cm:
        raise ValueError("nope")
    assert cm.failure is not None
    assert cm.failure.stage == "score"
    assert cm.failure.user_message == "nope"
    assert cm.failure.debug_detail is not None
    assert "ValueError" in cm.failure.debug_detail


def test_keyboard_interrupt_propagates() -> None:
    with pytest.raises(KeyboardInterrupt), stage_boundary("s"):
        raise KeyboardInterrupt
    assert current_stage.get() is None
