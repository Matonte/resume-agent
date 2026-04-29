# LLM regression tests

## Offline (default CI)

- **`cases/*.json`** — each file defines `handler`, `kwargs`, `llm_mock_return` (the JSON object `complete_json` would parse), and `expect` (final outputs after guardrails).
- **`test_regression_offline.py`** — patches `complete_json` and `is_available`, then asserts stable pipeline behavior.

These tests **do not call OpenAI** and run with the rest of `pytest`.

## Refreshing fixtures after prompt / guardrail changes

1. Export `OPENAI_API_KEY`.
2. Run:

   ```bash
   python scripts/record_llm_regression.py
   ```

   Or one case: `python scripts/record_llm_regression.py --case rewrite_bullets_identity`

3. Review diffs in `cases/*.json`, then commit.

## Live smoke (optional)

Non-deterministic; only checks shape and length.

```bash
set RUN_LLM_LIVE=1
set OPENAI_API_KEY=...
pytest tests/llm_regression/test_regression_live.py -m llm_live
```

## Adding a case

1. Copy an existing JSON file in `cases/`.
2. Set a new `id`, `handler` (`rewrite_bullets`, `rewrite_summary`, `rewrite_cover_letter`), and `kwargs`.
3. Run the recorder, or hand-author `llm_mock_return` + `expect` for tight control.
