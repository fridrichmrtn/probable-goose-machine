from __future__ import annotations

from contextvars import Token
from types import TracebackType
from typing import Self

from pydantic import BaseModel

from gander import obs


class StageFailure(BaseModel):
    stage: str
    # Reviewer-facing copy. Do not put raw exception strings or CV content here;
    # implementation detail belongs in debug_detail or structured obs fields.
    user_message: str
    debug_detail: str | None = None


_GENERIC_STAGE_MESSAGE = "Could not complete this stage reliably"
_STAGE_USER_MESSAGES = {
    "ingest": "Unable to read this file. Please upload a valid PDF or DOCX.",
    "redact": "Could not process this file safely.",
    "extract": "Could not generate this section reliably",
    "score": "Could not generate this section reliably",
    "salary": "Insufficient market data for this profile",
    "confidence": "Could not generate this section reliably",
    "growth": "Could not generate this section reliably",
}


def _boundary_user_message(stage_name: str) -> str:
    return _STAGE_USER_MESSAGES.get(stage_name, _GENERIC_STAGE_MESSAGE)


class stage_boundary:
    """Context manager (sync + async) that converts stage exceptions into a StageFailure.

    Usage:
        with stage_boundary("score") as cm:
            ...                       # may raise
        if cm.failure:
            report.score = cm.failure

    KeyboardInterrupt and SystemExit are re-raised. All other Exception subclasses
    are swallowed and recorded as `cm.failure`.
    """

    def __init__(self, stage_name: str) -> None:
        self.stage_name = stage_name
        self.failure: StageFailure | None = None
        self._stage_token: Token[str | None] | None = None

    def __enter__(self) -> Self:
        self._stage_token = obs.current_stage.set(self.stage_name)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            return self._handle(exc_type, exc)
        finally:
            if self._stage_token is not None:
                obs.current_stage.reset(self._stage_token)
                self._stage_token = None

    async def __aenter__(self) -> Self:
        self._stage_token = obs.current_stage.set(self.stage_name)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            return self._handle(exc_type, exc)
        finally:
            if self._stage_token is not None:
                obs.current_stage.reset(self._stage_token)
                self._stage_token = None

    def _handle(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
    ) -> bool:
        if exc is None:
            return False
        if isinstance(exc, KeyboardInterrupt | SystemExit):
            return False
        if isinstance(exc, Exception):
            self.failure = StageFailure(
                stage=self.stage_name,
                user_message=_boundary_user_message(self.stage_name),
                debug_detail=repr(exc),
            )
            obs.emit(
                self.stage_name,
                "error",
                exc_type=type(exc).__name__,
            )
            return True
        return False
