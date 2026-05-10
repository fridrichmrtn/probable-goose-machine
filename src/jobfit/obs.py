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
_logger = structlog.get_logger("jobfit")


def emit(stage: str | None, event: str, **kv: Any) -> None:
    record: dict[str, Any] = {"stage": stage, "event": event, **kv}
    _logger.info(event, stage=stage, **kv)
    for callback in _subscribers.get():
        callback(record)


@contextmanager
def subscribe(callback: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    token = _subscribers.set((*_subscribers.get(), callback))
    try:
        yield
    finally:
        _subscribers.reset(token)
