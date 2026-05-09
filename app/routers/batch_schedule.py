"""API + helpers for editing the Windows batch schedule from the UI."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.jobs.batch_schedule import (
    BatchScheduleConfig,
    client_host_is_loopback,
    load_batch_schedule,
    register_script_path,
    repo_root,
    save_batch_schedule,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/batch-schedule", tags=["batch-schedule"])


class BatchSchedulePayload(BaseModel):
    window_start: str = Field(default="08:00")
    window_end: str = Field(default="21:00")
    interval_hours: int = Field(default=3, ge=1, le=24)
    task_name: str = Field(default="resume-agent-daily")
    extra_args: str = Field(default="--verbose")
    execution_time_limit_minutes: int = Field(default=0, ge=0)


def _schedule_dict(cfg: BatchScheduleConfig) -> Dict[str, Any]:
    return {
        **cfg.model_dump(mode="json"),
        "run_times": cfg.run_times_today(),
    }


def _apply_context(request: Request) -> Dict[str, Any]:
    win = sys.platform == "win32"
    loopback = client_host_is_loopback(request.client.host if request.client else None)
    script_ok = register_script_path().is_file()
    return {
        "platform_is_windows": win,
        "client_is_loopback": loopback,
        "register_script_present": script_ok,
        "apply_available": win and loopback and script_ok,
    }


@router.get("/")
def get_batch_schedule(request: Request) -> JSONResponse:
    cfg = load_batch_schedule()
    body = {**_schedule_dict(cfg), **_apply_context(request)}
    return JSONResponse(body)


@router.put("/")
def put_batch_schedule(payload: BatchSchedulePayload) -> JSONResponse:
    try:
        cfg = BatchScheduleConfig.model_validate(payload.model_dump())
        cfg.run_times_today()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_batch_schedule(cfg)
    return JSONResponse({"ok": True, **_schedule_dict(cfg)})


@router.post("/apply-windows-task")
def apply_windows_task(request: Request) -> JSONResponse:
    ctx = _apply_context(request)
    if not ctx["apply_available"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "Apply is only allowed on Windows from a loopback client, "
                "and scripts/register_scheduled_task.ps1 must exist. "
                f"context={ctx!r}"
            ),
        )
    cfg = load_batch_schedule()
    ps1 = register_script_path()
    root = repo_root()
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ps1),
        "-WindowStart",
        cfg.window_start,
        "-WindowEnd",
        cfg.window_end,
        "-IntervalHours",
        str(cfg.interval_hours),
        "-TaskName",
        cfg.task_name,
        "-ExtraArgs",
        cfg.extra_args,
        "-ExecutionTimeLimitMinutes",
        str(cfg.execution_time_limit_minutes),
        "-RepoRoot",
        str(root),
    ]
    try:
        proc = subprocess.run(
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="register_scheduled_task.ps1 timed out")
    except OSError as exc:
        logger.exception("subprocess failed starting powershell")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    ok = proc.returncode == 0
    return JSONResponse(
        {
            "ok": ok,
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            **_schedule_dict(cfg),
        },
        status_code=200 if ok else 500,
    )


__all__ = ["router"]
