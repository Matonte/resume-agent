# Resume Agent Starter

This is a Cursor-ready starter project for your resume/application agent.

It includes:
- your 4 source resumes in `data/source_resumes/`
- a structured master truth model in `data/master_truth_model.json`
- archetype definitions in `data/archetypes/`
- a story bank and application answer bank
- training examples for classification and bullet rewriting
- prompt templates
- a FastAPI scaffold for local development

## Recommended stack
- Python 3.12
- FastAPI
- Pydantic
- Playwright (later, for browser assist)
- OpenAI API

## Quick start

**You do not need AWS or billing to develop.** Data lives in `outputs/` and `.playwright/` (gitignored). When you add a payment method on AWS, use [docs/CUTOVER_CHECKLIST.md](docs/CUTOVER_CHECKLIST.md) to deploy in one pass.

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
# Install Playwright browser once: .\.venv\Scripts\playwright install chromium
.\scripts\run_local.ps1
```

Daily job locally (optional): `.\scripts\run_daily_local.ps1` (defaults to `--no-email --verbose`; pass your own args to override).

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Then open:
- Review UI:  http://127.0.0.1:8000/
- API docs:   http://127.0.0.1:8000/docs
- Health:     http://127.0.0.1:8000/api/health

Run the test suite:

```bash
pytest -v
```

Key endpoints:
- `POST /api/classify`        — classify a job description to an archetype
- `POST /api/fit-score`       — 0-10 fit score with reasons
- `POST /api/draft-resume`    — generate an in-memory resume draft (summary + bullets + notes)
- `POST /api/answer`          — answer a single application question
- `POST /api/full-draft`      — classify + draft + fit + (optional) answer in one call
- `POST /api/generate-resume` — download a tailored .docx that matches the chosen archetype's source resume layout, with the summary and per-role bullets rewritten for the job

The review UI at `/` exposes both the full-draft preview and a "Download tailored .docx" button that streams the file to the browser.

## Suggested build order
1. Verify the truth model and archetype mappings
2. Improve the bullet rewrite prompts with 10-20 real job descriptions
3. Add a small review UI
4. Add Playwright-assisted question extraction and form filling
5. Add persistence and job tracking

## Important guardrails
- Never invent metrics, tools, dates, or scope
- Every generated claim must trace back to `master_truth_model.json`
- Keep tone senior, concrete, and defensible in interviews
