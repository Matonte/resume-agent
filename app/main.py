from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routers.api import router
from app.routers.jobs import router as jobs_router
from app.routers.manual import router as manual_router

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Resume Agent Starter", version="0.3.0")
app.include_router(router, prefix="/api")
app.include_router(jobs_router)  # already self-prefixed with /api/jobs
app.include_router(manual_router)  # POST /api/manual-tailor
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def review_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "review.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/jobs/today", response_class=HTMLResponse)
def jobs_today_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "jobs_today.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/tailor", response_class=HTMLResponse)
def tailor_page() -> HTMLResponse:
    """Manual-tailor form. Posts to /api/manual-tailor."""
    html = (TEMPLATES_DIR / "tailor.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/manual-tailor")
def manual_tailor_alias_redirect() -> RedirectResponse:
    """People often guess /manual-tailor; send them to the real UI."""
    return RedirectResponse(url="/tailor", status_code=307)
