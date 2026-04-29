# Resume Agent

Local-first job-hunt assistant: scrape or paste listings, classify against **archetypes**, tailor **resume + cover letter + screening answers** from `data/master_truth_model.json`, optional **web outreach** (recruiter / hiring-manager discovery), and **meeting-advisor** hooks for outreach prep.

Outputs land under `outputs/`; Playwright profiles under `.playwright/` (both gitignored).

## What’s in the repo

- Source resumes in `data/source_resumes/` and archetypes in `data/archetypes/`
- `data/master_truth_model.json` — single source of truth for generated claims
- Story / answer banks and classification training data under `data/`
- **FastAPI** app: review UI, manual intake, jobs queue, REST API
- **Daily runner** — `python -m app.jobs.daily_run` (scrapers + tailor + optional email digest)
- **Playwright** scrapers (LinkedIn, Jobright, etc.) with human-paced throttling (`data/preferences.yaml`)

## Stack

- Python 3.12, FastAPI, Pydantic  
- OpenAI API (polish / classifier-adjacent flows when `OPENAI_API_KEY` is set)  
- Playwright for job-site sessions  

## Quick start

**You do not need AWS to develop.** For production cutover, see [docs/CUTOVER_CHECKLIST.md](docs/CUTOVER_CHECKLIST.md).

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
# Playwright (if using scrapers): .\.venv\Scripts\playwright install chromium
.\scripts\run_local.ps1
```

**Daily pipeline (no email by default):**

```powershell
.\scripts\run_daily_local.ps1
# Or: python -m app.jobs.daily_run --no-email --verbose
# Smoke / offline scrapers: add --fake
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### URLs

| Page | URL |
|------|-----|
| Review (full draft + meeting advisor) | http://127.0.0.1:8000/ |
| Manual intake (tailored package to today’s queue) | http://127.0.0.1:8000/tailor |
| Jobs today | http://127.0.0.1:8000/jobs/today |
| OpenAPI | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/api/health |

### Tests

```bash
pytest -v
```

**LLM regression** (recorded golden outputs): [tests/llm_regression/README.md](tests/llm_regression/README.md). Refresh with `python scripts/record_llm_regression.py` (needs `OPENAI_API_KEY`).

## Configuration (`.env`)

Copy from [`.env.example`](.env.example). Commonly used:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM polish, posting-people extraction, outreach enrichment |
| `MODEL_NAME` | Chat model id (default in `.env.example`) |
| `MEETING_ADVISOR_URL` | Base URL for `POST …/api/v1/advise` (e.g. `http://127.0.0.1:8000` if the advisor is mounted on the same app) |
| `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX` | Web search for outreach (optional; can use Bing instead) |
| `BING_SEARCH_KEY` | Alternative/additional web search |
| `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` | Daily digest SMTP (optional) |
| `DASHBOARD_BASE_URL` | Links in the digest (e.g. `http://127.0.0.1:8000`) |
| `PLAYWRIGHT_*` | Channel + per-site profile dirs — see `.env.example` |

**Outreach** is controlled in `data/preferences.yaml` under `outreach_for_job` (including `posting_people` and `fetch_apply_page` for named-contact extraction + extra searches). Requires search API keys above.

## API highlights

- `POST /api/classify` — archetype from JD  
- `POST /api/fit-score` — fit score + reasons  
- `POST /api/draft-resume` — in-memory draft  
- `POST /api/full-draft` — classify + draft + fit + optional question + optional **meeting advisor** (`meeting_advisor`, `advisor_subject_name`)  
- `POST /api/generate-resume` — tailored `.docx` download  
- `POST /api/manual-tailor` — full package (same as daily tailor) + optional advisor JSON in response  
- `POST /api/outreach/enrich` — enrich search hits (advisor + optional LLM)  

## Important guardrails

- Do not invent metrics, tools, dates, or scope.  
- Claims should trace to `data/master_truth_model.json`.  
- LinkedIn and other sites may restrict automation; scrapers are best-effort and **use at your own risk**.
