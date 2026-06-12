from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog

_CONFIGURED = False

_subscribers: ContextVar[tuple[Callable[[dict[str, Any]], None], ...]] = ContextVar(
    "subscribers", default=()
)
current_stage: ContextVar[str | None] = ContextVar("current_stage", default=None)
# Correlates every event from one pipeline run. Set once at pipeline entry; a
# uuid4, so it carries no CV content and is safe to log (see test_privacy_obs).
current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)


def _configure_once() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


_configure_once()
_logger = structlog.get_logger("gander")


def emit(stage: str | None, event: str, **kv: Any) -> None:
    run_id = current_run_id.get()
    record: dict[str, Any] = {"stage": stage, "event": event, "run_id": run_id, **kv}
    _logger.info(event, stage=stage, run_id=run_id, **kv)
    for callback in _subscribers.get():
        try:
            callback(record)
        except Exception as cb_err:
            # A broken UI/progress subscriber must not turn a handled stage
            # failure into an unhandled exception.
            _logger.warning(
                "subscriber_error",
                stage=stage,
                origin_event=event,
                error=repr(cb_err),
            )


@contextmanager
def run_scope(run_id: str) -> Iterator[None]:
    """Bind `run_id` to the current context for the duration of one pipeline run.

    Reset in finally so a cancelled or GC'd async generator can't leak the id
    into a later run reusing the same task/context.
    """
    token = current_run_id.set(run_id)
    try:
        yield
    finally:
        current_run_id.reset(token)


@contextmanager
def subscribe(callback: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    token = _subscribers.set((*_subscribers.get(), callback))
    try:
        yield
    finally:
        _subscribers.reset(token)
