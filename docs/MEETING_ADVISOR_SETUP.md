# Meeting Advisor setup

Resume Agent’s meeting-prep features call a **Meeting Advisor** HTTP API. That API lives in the sibling **[Contact Advisor](https://github.com/Matonte/contact-advisor)** repo and depends on two other local services.

Use this guide when `Run advisor` fails, people-intel is empty, or advise calls return 404.

## What you need running

Start services in this order (Contact Advisor repo root):

| Order | Service | Default URL | Start command |
|------:|---------|-------------|----------------|
| 1 | Contact Advisor (WhoIsWhat + people-intel) | `http://127.0.0.1:5000` | `python run.py` |
| 2 | WhoIsHoss | `http://127.0.0.1:5002` | `python run_whoishoss.py` |
| 3 | Meeting Advisor (`POST /api/v1/advise`) | `http://127.0.0.1:5003` | `python run_meeting_advisor.py` |
| 4 | Resume Agent | `http://127.0.0.1:8000` | `uvicorn` / `scripts/run_local.ps1` |

Meeting Advisor expects WhoIsWhat (`:5000`) and WhoIsHoss (`:5002`) to be reachable. If you only start Resume Agent, embedded advisor calls will fail.

### When you need an *additional* instance

- **Local + AWS/Docker at once:** set Resume Agent env vars to the stack you want (local `127.0.0.1` vs host/service DNS). Do not point `MEETING_ADVISOR_URL` at Resume Agent’s own `:8000` unless that process actually serves `/api/v1/advise`.
- **Second developer machine / remote EC2:** run the Contact Advisor trio on that host (or containers bound to localhost), then point Resume Agent at those URLs. On EC2, keep `5000`/`5002`/`5003` on `127.0.0.1` — do not open them publicly.
- **UI hosted elsewhere:** set `MEETING_ADVISOR_UI_URL` for browser redirect; API calls still use `MEETING_ADVISOR_URL`.

## Resume Agent environment variables

Set these in Resume Agent’s `.env` (restart after changes):

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `MEETING_ADVISOR_URL` | **Yes** for advise | Base URL of the Meeting Advisor process (e.g. `http://127.0.0.1:5003`) |
| `CONTACT_ADVISOR_SERVICE_URL` | Recommended | Base URL for WhoIsWhat / people-intel (e.g. `http://127.0.0.1:5000`). Alias: `WHOISWHAT_SERVICE_URL` |
| `MEETING_ADVISOR_ADVISE_PATH` | Optional | Path for advise POST (default `/api/v1/advise`) |
| `MEETING_ADVISOR_UI_URL` | Optional | If set, GET `/meeting-advisor` redirects the browser here |
| `OPENAI_API_KEY` | On Contact Advisor stack | Required by Contact Advisor / Meeting Advisor LLM calls (also used by Resume Agent for other features) |

Example:

```env
MEETING_ADVISOR_URL=http://127.0.0.1:5003
CONTACT_ADVISOR_SERVICE_URL=http://127.0.0.1:5000
```

## Clone / locate Contact Advisor

Clone beside this repo so helper scripts can find it:

```text
parent/
  resume-agent/
  contact-advisor/   # or contact_advisor / flask_sample
```

Windows helper from Resume Agent:

```powershell
.\scripts\start_meeting_advisor.ps1
# or with an explicit root:
.\scripts\start_meeting_advisor.ps1 -RepoRoot C:\path\to\contact-advisor
```

Follow Contact Advisor’s README for its venv and dependencies.

## Verify

From Resume Agent:

```bash
python scripts/check_meeting_advisor_stack.py
```

Then open [http://127.0.0.1:8000/meeting-advisor](http://127.0.0.1:8000/meeting-advisor) and run a prep request.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Advise returns **404** | `MEETING_ADVISOR_URL` points at Resume Agent or wrong port | Point at `:5003` (Meeting Advisor), not `:8000` |
| Connection refused / timeout | Service not started or wrong host | Start services in order 5000 → 5002 → 5003; confirm URLs |
| People-intel empty | `CONTACT_ADVISOR_SERVICE_URL` unset or `:5000` down | Set env var; start `python run.py` |
| LLM / empty advice JSON | Missing `OPENAI_API_KEY` on Contact Advisor | Set the key in that stack’s environment |
| Works locally, fails on EC2 | Advisor not running on instance, or URL uses public IP | Run stack on the instance; use `http://127.0.0.1:5003` inside Docker/host networking |
| Browser UI wrong app | `MEETING_ADVISOR_UI_URL` mis-set | Clear it to use embedded UI, or set to the intended external UI |

## Related

- Main README section: [Contact Advisor + Meeting Advisor](../README.md#contact-advisor--meeting-advisor-optional)
- Cutover checklist: [CUTOVER_CHECKLIST.md](./CUTOVER_CHECKLIST.md)
- AWS notes: [aws/README.md](../aws/README.md)
