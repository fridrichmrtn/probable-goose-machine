from __future__ import annotations

import os


def env_int(
    name: str,
    default: int,
    *,
    min_value: int = 1,
    max_value: int | None = None,
) -> int:
    raw = os.environ.get(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def env_float(
    name: str,
    default: float,
    *,
    min_value: float = 0.1,
    max_value: float | None = None,
) -> float:
    raw = os.environ.get(name)
    if raw is None:
        value = float(default)
    else:
        try:
            value = float(raw)
        except ValueError:
            value = float(default)
    value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value
