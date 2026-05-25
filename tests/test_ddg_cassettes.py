from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import gander.salary as salary_mod

pytestmark = pytest.mark.fast

_CONFTEST_PATH = Path(__file__).with_name("conftest.py")
_SPEC = importlib.util.spec_from_file_location("ddg_conftest_under_test", _CONFTEST_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
ddg_hooks = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ddg_hooks)


class _LiveItem:
    def get_closest_marker(self, name: str) -> object | None:
        return object() if name == "live" else None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("head of data science manager salary Praha CZK 2026", "senior_manager_prague"),
        ("data scientist manager salary Prague CZK 2026", "senior_manager_prague"),
        ("junior data analyst salary Praha site:platy.cz", "junior_data_analyst_prague"),
        ("staff machine learning engineer salary Praha site:platy.cz", "staff_mle_prague"),
        ("data scientist salary Prague site:platy.cz", "data_scientist_prague"),
    ],
)
def test_ddg_cassette_key_routes_specific_cz_queries(query: str, expected: str) -> None:
    assert ddg_hooks._ddg_cassette_key(query) == expected


def test_ddg_cassette_key_rejects_non_cz_queries_without_cassette() -> None:
    with pytest.raises(RuntimeError, match="No DDG cassette"):
        ddg_hooks._ddg_cassette_key("staff machine learning engineer salary Tokyo JPY 2026")


def test_live_ddg_hook_restores_original_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    original = salary_mod._ddg_text
    item = _LiveItem()
    monkeypatch.delenv("GANDER_LIVE_DDG", raising=False)
    monkeypatch.setattr(ddg_hooks, "_ORIGINAL_DDG_TEXT", None)

    ddg_hooks.pytest_runtest_setup(item)  # type: ignore[arg-type]
    assert salary_mod._ddg_text is ddg_hooks._replay_ddg_text

    ddg_hooks.pytest_runtest_teardown(item, None)  # type: ignore[arg-type]
    assert salary_mod._ddg_text is original
