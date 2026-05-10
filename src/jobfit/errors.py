from __future__ import annotations

from types import TracebackType
from typing import Self

from pydantic import BaseModel


class StageFailure(BaseModel):
    stage: str
    user_message: str
    debug_detail: str | None = None


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

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return self._handle(exc_type, exc)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return self._handle(exc_type, exc)

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
                user_message=str(exc) or type(exc).__name__,
                debug_detail=repr(exc),
            )
            # T02: wire to obs.emit("error", stage=self.stage_name, exc=repr(exc))
            return True
        return False
