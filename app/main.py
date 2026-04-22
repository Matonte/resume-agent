from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.routers.api import router
from app.routers.jobs import router as jobs_router

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Resume Agent Starter", version="0.3.0")
app.include_router(router, prefix="/api")
app.include_router(jobs_router)  # already self-prefixed with /api/jobs
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def review_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "review.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/jobs/today", response_class=HTMLResponse)
def jobs_today_page() -> HTMLResponse:
    html = (TEMPLATES_DIR / "jobs_today.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)
