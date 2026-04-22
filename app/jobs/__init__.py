"""Daily job-agent entrypoints and orchestration.

- `preferences`: load/validate `data/preferences.yaml`.
- `runner`:      orchestrate scrape -> rank -> tailor -> store -> notify.
- `daily_run`:   thin CLI wrapper around `runner.run_daily()`.
"""
