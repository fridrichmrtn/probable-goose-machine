from __future__ import annotations

import pytest

from gander.config import env_float, env_int

pytestmark = pytest.mark.fast


def test_env_int_clamps_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GANDER_TEST_INT", "99")
    assert env_int("GANDER_TEST_INT", 4, min_value=1, max_value=8) == 8

    monkeypatch.setenv("GANDER_TEST_INT", "0")
    assert env_int("GANDER_TEST_INT", 4, min_value=1, max_value=8) == 1

    monkeypatch.setenv("GANDER_TEST_INT", "not-an-int")
    assert env_int("GANDER_TEST_INT", 4, min_value=1, max_value=8) == 4


def test_env_float_clamps_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GANDER_TEST_FLOAT", "99.5")
    assert env_float("GANDER_TEST_FLOAT", 4.0, min_value=0.1, max_value=8.0) == 8.0

    monkeypatch.setenv("GANDER_TEST_FLOAT", "0")
    assert env_float("GANDER_TEST_FLOAT", 4.0, min_value=0.1, max_value=8.0) == 0.1

    monkeypatch.setenv("GANDER_TEST_FLOAT", "not-a-float")
    assert env_float("GANDER_TEST_FLOAT", 4.0, min_value=0.1, max_value=8.0) == 4.0
