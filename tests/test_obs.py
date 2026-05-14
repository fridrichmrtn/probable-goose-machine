from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest

from gander import obs
from gander.obs import current_stage, emit, subscribe

pytestmark = pytest.mark.fast


def test_subscribe_roundtrip_and_unregister() -> None:
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        emit("stage_a", "tick", k=1)
    assert events == [{"stage": "stage_a", "event": "tick", "k": 1}]

    emit("stage_a", "tick_after", k=2)
    assert len(events) == 1


async def test_subscribe_isolated_across_gather_siblings() -> None:
    a_events: list[dict[str, Any]] = []
    b_events: list[dict[str, Any]] = []

    async def task_a() -> None:
        with subscribe(a_events.append):
            emit("a", "evt1", task="a")
            await asyncio.sleep(0)
            emit("a", "evt2", task="a")

    async def task_b() -> None:
        with subscribe(b_events.append):
            emit("b", "evt1", task="b")
            await asyncio.sleep(0)
            emit("b", "evt2", task="b")

    await asyncio.gather(task_a(), task_b())

    assert all(e["task"] == "a" for e in a_events)
    assert all(e["task"] == "b" for e in b_events)
    assert len(a_events) == 2
    assert len(b_events) == 2


def test_current_stage_round_trip() -> None:
    assert current_stage.get() is None
    tok = current_stage.set("x")
    try:
        assert current_stage.get() == "x"
    finally:
        current_stage.reset(tok)
    assert current_stage.get() is None


def test_idempotent_configure_does_not_crash_on_reload() -> None:
    importlib.reload(obs)
    obs.emit("s", "e")


def test_subscriber_exception_is_swallowed_not_propagated() -> None:
    """A broken UI/progress callback must not break the pipeline.

    Regression: prior version let subscriber exceptions bubble out of emit(),
    which could turn a handled stage_boundary failure into an unhandled crash.
    """
    good_events: list[dict[str, Any]] = []

    def bad_callback(_: dict[str, Any]) -> None:
        raise RuntimeError("subscriber blew up")

    with subscribe(bad_callback), subscribe(good_events.append):
        emit("stage_x", "tick", k=1)

    assert good_events == [{"stage": "stage_x", "event": "tick", "k": 1}]
