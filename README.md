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

### Getting a new teammate set up

Use this checklist when onboarding someone to the repo (local-only is enough).

| Step | What to do |
|------|------------|
| 1 | **Python 3.12** and Git installed. |
| 2 | Clone the repo, create a venv, install deps (same commands as **Quick start** above for your OS). |
| 3 | Copy **`.env.example` → `.env`**. At minimum set **`SESSION_SECRET`** to a long random string if anyone will use **Register / Log in** (otherwise session cookies are insecure). |
| 4 | Start the app: **`.\scripts\run_local.ps1`** (Windows) or **`uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`**. If port 8000 is stuck: **`powershell -ExecutionPolicy Bypass -File .\scripts\kill_port.ps1 8000`**. |
| 5 | Sanity check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health) should return `200` and JSON `status: ok`. |
| 6 | **Two ways to work:** (A) **Don’t log in** — you use the default workspace and the bundled **`data/`** truth model (good for trying the UI). (B) **Register** at **`/account`** — you get an isolated profile under **`outputs/user_profiles/`** and must complete **`/onboarding`** once: upload at least one résumé (`.docx` or `.txt`) and paste **three** job descriptions. Finishing runs an LLM step to build **`master_truth_model.json`** / **`story_bank.json`** in your profile when **`OPENAI_API_KEY`** is set. For local dev without OpenAI, set **`ONBOARDING_ALLOW_FINISH_WITHOUT_LLM=1`** in `.env` to save raw uploads and still unlock the app (see `.env.example`). |
| After | Optional: **Contact Advisor** (Meeting Advisor stack) — see [**Contact Advisor + Meeting Advisor**](#contact-advisor--meeting-advisor-optional) below and repo **[github.com/Matonte/contact-advisor](https://github.com/Matonte/contact-advisor)**; search keys for outreach, Playwright **`login_once`** for scrapers — see **Configuration** and **`docs/CUTOVER_CHECKLIST.md`**. |

### URLs

| Page | URL |
|------|-----|
| Review (full draft + meeting advisor) | http://127.0.0.1:8000/ |
| Manual intake (tailored package to today’s queue) | http://127.0.0.1:8000/tailor |
| Jobs today | http://127.0.0.1:8000/jobs/today |
| Account (register / login) | http://127.0.0.1:8000/account |
| First-time setup (résumé + job samples) | http://127.0.0.1:8000/onboarding |
| Meeting advisor (prep UI; set `MEETING_ADVISOR_URL` so Run advisor can POST to your advisor app) | http://127.0.0.1:8000/meeting-advisor |
| Contact Advisor (sibling repo — WhoIsWhat, people-intel, Meeting Advisor processes) | [github.com/Matonte/contact-advisor](https://github.com/Matonte/contact-advisor) |
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
| `SESSION_SECRET` | Signs browser sessions; use a long random value in any shared or deployed environment |
| `DEFAULT_USER_ID` | Workspace used when not logged in (default `1`, repo `data/`) |
| `ONBOARDING_MIN_RESUMES` / `ONBOARDING_MIN_JOB_SAMPLES` | First-time wizard thresholds (defaults in `.env.example`) |
| `ONBOARDING_ALLOW_FINISH_WITHOUT_LLM` | Set `1` for local dev to finish onboarding without generating profile JSON |
| `OPENAI_API_KEY` | LLM polish, posting-people extraction, onboarding profile generation, outreach enrichment |
| `MODEL_NAME` | Chat model id (default in `.env.example`) |
| `CONTACT_ADVISOR_SERVICE_URL` | Base URL of **Contact Advisor** (WhoIsWhat + `POST /api/v1/people-intel`), e.g. `http://127.0.0.1:5000`. Alias: `WHOISWHAT_SERVICE_URL`. Unlocks people-intel in outreach and embedded advisor flows when set |
| `MEETING_ADVISOR_URL` | Base URL of the **advisor app** only (default POST path `/api/v1/advise`). Use the advisor process, e.g. `http://127.0.0.1:5003` — **not** resume-agent’s URL unless that stack serves the advise route |
| `MEETING_ADVISOR_UI_URL` | Optional; if set, GET `/meeting-advisor` redirects the browser here instead of the embedded page. API POSTs still use `MEETING_ADVISOR_URL` |
| `MEETING_ADVISOR_ADVISE_PATH` | Optional; default `/api/v1/advise` if your advisor uses a different path |
| `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX` | Web search for outreach (optional; can use Bing instead) |
| `BING_SEARCH_KEY` | Alternative/additional web search |
| `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` | Daily digest SMTP (optional) |
| `DASHBOARD_BASE_URL` | Links in the digest (e.g. `http://127.0.0.1:8000`) |
| `PLAYWRIGHT_*` | Channel + per-site profile dirs — see `.env.example` |

**Outreach** is controlled in `data/preferences.yaml` under `outreach_for_job` (including `posting_people` and `fetch_apply_page` for named-contact extraction + extra searches). Requires search API keys above.

## Contact Advisor + Meeting Advisor (optional)

Prep features in Resume Agent (**`/meeting-advisor`**, outreach enrichment, manual tailor advisor, `POST /api/person-profile-bundle`) call a **Meeting Advisor** HTTP API (`POST …/api/v1/advise`). That service orchestrates **WhoIsWhat (K)**, **WhoIsHoss**, and tactical prep JSON. The implementation lives in the sibling **[Contact Advisor](https://github.com/Matonte/contact-advisor)** repo (clone beside `resume-agent` as `contact_advisor` or `flask_sample` so `scripts/start_meeting_advisor.ps1` can find it, or pass `-RepoRoot`).

### Portal / links

| What | URL |
|------|-----|
| **Contact Advisor** source | [github.com/Matonte/contact-advisor](https://github.com/Matonte/contact-advisor) |
| **Meeting prep UI** in Resume Agent (embedded; set `MEETING_ADVISOR_URL`) | [http://127.0.0.1:8000/meeting-advisor](http://127.0.0.1:8000/meeting-advisor) |

Use the Contact Advisor README for venv, dependencies, and **`OPENAI_API_KEY`** on that stack.

### Processes (typical local)

| Role | Base URL | Start (Contact Advisor repo root) |
|------|----------|-------------------------------------|
| Contact Advisor — WhoIsWhat + **`POST /api/v1/people-intel`** | `http://127.0.0.1:5000` | `python run.py` |
| WhoIsHoss | `http://127.0.0.1:5002` | `python run_whoishoss.py` |
| Meeting Advisor — **`POST /api/v1/advise`** | `http://127.0.0.1:5003` | `python run_meeting_advisor.py` |

### Resume Agent `.env`

```env
MEETING_ADVISOR_URL=http://127.0.0.1:5003
CONTACT_ADVISOR_SERVICE_URL=http://127.0.0.1:5000
```

`MEETING_ADVISOR_URL` must be the **Meeting Advisor** process base (not Resume Agent on `:8000`) or advise calls return 404. (`WHOISWHAT_SERVICE_URL` is a deprecated alias for `CONTACT_ADVISOR_SERVICE_URL`.) Optional: **`MEETING_ADVISOR_UI_URL`** redirects the browser from GET `/meeting-advisor`; API still uses `MEETING_ADVISOR_URL`.

### Verify

From this repo: `python scripts/check_meeting_advisor_stack.py`. Windows: `.\scripts\start_meeting_advisor.ps1`. Restart Resume Agent after editing `.env`.

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
