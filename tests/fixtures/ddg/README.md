# DDG Salary Cassettes

Live acceptance tests replay these snippets by default so salary and growth
failures represent model/pipeline regressions rather than DDG transport
weather.

Set `GANDER_LIVE_DDG=1` when you intentionally want real DDG traffic for
manual regeneration or drift checks.

To verify PRD §5(6) source reachability against fresh DDG results, run:

```bash
GANDER_LIVE_DDG=1 GANDER_CHECK_SALARY_URLS=1 GANDER_LLM_PROVIDER=openrouter OPENROUTER_API_KEY=... uv run pytest tests/test_acceptance.py::test_salary_source_urls_reachable -m live -q
```
