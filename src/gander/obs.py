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
    # `event` is structlog's positional message, so it must NOT also appear in
    # the spread kwargs (that raises "multiple values for 'event'"). Spreading
    # one `fields` dict — instead of explicit stage=/run_id= kwargs alongside
    # **kv — also means a caller that forwards a record via **kv (which already
    # carries stage/run_id) can't trigger a duplicate-keyword TypeError: the
    # later key just wins. The subscriber record adds `event` back for callers.
    fields: dict[str, Any] = {"stage": stage, "run_id": run_id, **kv}
    record: dict[str, Any] = {"event": event, **fields}
    _logger.info(event, **fields)
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
        try:
            current_run_id.reset(token)
        except ValueError:
            # The generator was GC-finalized in a *different* asyncio Context
            # (browser disconnect / server timeout), so `token` belongs to a
            # foreign Context and reset() raises. Clear to the default in
            # whatever Context the finalizer runs in, instead of letting the
            # ValueError escape and leak `run_id` into a later run that reuses
            # this task. The clean cancel path (CancelledError) resets in-context
            # and never hits this branch. See test_run_scope_resets_on_gc_*.
            current_run_id.set(None)


@contextmanager
def subscribe(callback: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    token = _subscribers.set((*_subscribers.get(), callback))
    try:
        yield
    finally:
        try:
            _subscribers.reset(token)
        except ValueError:
            # Same foreign-Context GC guard as run_scope: rather than leak a
            # zombie subscriber (which would double-count a later run's cost),
            # drop subscribers to the empty default in the finalizer's Context.
            _subscribers.set(())
