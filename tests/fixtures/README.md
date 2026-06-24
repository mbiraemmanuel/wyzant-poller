# Test Fixtures

Place real Wyzant page captures here after running `wyzant-poller inspect`:

- `jobs_page.html` — raw HTML from the jobs board (run `wyzant-poller inspect` without `JOBS_JSON_ENDPOINT`)
- `jobs_api.json` — raw JSON response (run with `JOBS_JSON_ENDPOINT` set)

Once you have the real markup, update the selectors in `src/wyzant_poller/fetch.py`
and add a fixture-backed test to `tests/test_fetch.py`.
