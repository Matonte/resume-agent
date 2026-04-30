from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.middleware.profile_bind import ProfileDataMiddleware
from app.routers.api import router
from app.routers.auth_api import router as auth_router
from app.routers.jobs import router as jobs_router
from app.routers.manual import router as manual_router
from app.routers.profiles_api import router as profiles_router

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Resume Agent Starter", version="0.4.0")

# Last-added middleware runs first on the request. Session must run before
# ProfileDataMiddleware reads request.session.
app.add_middleware(ProfileDataMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="ra_session",
    max_age=14 * 24 * 3600,
    same_site="lax",
)

app.include_router(router, prefix="/api")
app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(jobs_router)
app.include_router(manual_router)

# HTML pages and redirects must be registered *before* mounting /static so the
# mounted app cannot take precedence in any edge cases (see FastAPI "Mount"
# docs: mount sub-apps last).
def review_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "review.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/jobs/today", response_class=HTMLResponse)
def jobs_today_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "jobs_today.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/tailor", response_class=HTMLResponse)
def tailor_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "tailor.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/account", response_class=HTMLResponse)
def account_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "account.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/meeting-advisor/", response_class=RedirectResponse)
def meeting_advisor_page_trailing_slash() -> RedirectResponse:
    return RedirectResponse(url="/meeting-advisor", status_code=307)


@app.get("/advisor", response_class=RedirectResponse)
def advisor_short_link() -> RedirectResponse:
    return RedirectResponse(url="/meeting-advisor", status_code=307)


@app.get("/meeting-advisor", response_class=HTMLResponse)
def meeting_advisor_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "meeting_advisor.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/manual-tailor")
def manual_tailor_alias_redirect() -> RedirectResponse:
    return RedirectResponse(url="/tailor", status_code=307)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
