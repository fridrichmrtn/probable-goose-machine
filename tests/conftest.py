from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

_DDG_CASSETTE_PATH = Path(__file__).parent / "fixtures" / "ddg" / "market_cassettes.json"
_ORIGINAL_DDG_TEXT: object | None = None
_NON_CZ_MARKERS = (
    "san francisco",
    "united states",
    "usa",
    "berlin",
    "germany",
    "deutschland",
    "tokyo",
    "japan",
)


def _load_ddg_cassettes() -> dict[str, list[dict[str, str]]]:
    with _DDG_CASSETTE_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid DDG cassette shape in {_DDG_CASSETTE_PATH}")
    return data


def _ddg_cassette_key(query: str) -> str:
    lowered = query.casefold()
    if any(marker in lowered for marker in _NON_CZ_MARKERS):
        raise RuntimeError(
            "No DDG cassette is available for this non-CZ salary query. "
            "Set GANDER_LIVE_DDG=1 to exercise real search, or add a country-keyed cassette."
        )
    if "manager" in lowered or "head of" in lowered or "vedouc" in lowered:
        return "senior_manager_prague"
    if "junior" in lowered or "data analyst" in lowered:
        return "junior_data_analyst_prague"
    if "staff machine learning engineer" in lowered or "machine learning engineer" in lowered:
        return "staff_mle_prague"
    if "data scientist" in lowered:
        return "data_scientist_prague"
    return "generic_cz_data"


def _replay_ddg_text(query: str) -> list[dict[str, Any]]:
    cassettes = _load_ddg_cassettes()
    key = _ddg_cassette_key(query)
    rows = cassettes.get(key) or cassettes["generic_cz_data"]
    # Return copies so callers can mutate without poisoning later live tests.
    return [dict(row) for row in rows]


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Replay salary-search snippets for live tests unless explicitly disabled.

    T37 removes DDG transport weather from the live acceptance/salary suites
    while keeping the LLM salary estimator in the loop. Set `GANDER_LIVE_DDG=1`
    to opt back into real DDG traffic for manual regeneration/debugging.
    """
    global _ORIGINAL_DDG_TEXT

    if not item.get_closest_marker("live"):
        return

    import gander.salary as salary_mod

    if _ORIGINAL_DDG_TEXT is None:
        _ORIGINAL_DDG_TEXT = salary_mod._ddg_text

    if os.environ.get("GANDER_LIVE_DDG") == "1":
        salary_mod._ddg_text = _ORIGINAL_DDG_TEXT  # type: ignore[assignment]
        return

    salary_mod._ddg_text = _replay_ddg_text  # type: ignore[assignment]


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    """Restore the DDG transport after each live test item."""
    if not item.get_closest_marker("live") or _ORIGINAL_DDG_TEXT is None:
        return

    import gander.salary as salary_mod

    salary_mod._ddg_text = _ORIGINAL_DDG_TEXT  # type: ignore[assignment]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Leave salary search unpatched even if a live test aborts mid-item."""
    if _ORIGINAL_DDG_TEXT is None:
        return

    import gander.salary as salary_mod

    salary_mod._ddg_text = _ORIGINAL_DDG_TEXT  # type: ignore[assignment]
