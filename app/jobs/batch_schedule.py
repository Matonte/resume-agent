"""Local batch run schedule for Windows Task Scheduler (UI + ``data/batch_schedule.yaml``).

The daily pipeline is still ``python -m app.jobs.daily_run``; this module stores when
it should fire and drives ``scripts/register_scheduled_task.ps1`` when you click
**Apply** in the UI.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field, field_validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = _REPO_ROOT / "data" / "batch_schedule.yaml"
_REGISTER_SCRIPT = _REPO_ROOT / "scripts" / "register_scheduled_task.ps1"

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class BatchScheduleConfig(BaseModel):
    """When to run ``daily_run`` via the Windows scheduled task."""

    window_start: str = Field(default="08:00", description="First start (24h HH:mm).")
    window_end: str = Field(
        default="21:00",
        description="Latest start time each day (24h HH:mm); grid is start + n * interval.",
    )
    interval_hours: int = Field(default=3, ge=1, le=24)
    task_name: str = Field(default="resume-agent-daily")
    extra_args: str = Field(
        default="--verbose",
        description="Extra CLI args for daily_run (single string).",
    )
    execution_time_limit_minutes: int = Field(
        default=0,
        ge=0,
        description="0 = no Task Scheduler time limit.",
    )

    @field_validator("window_start", "window_end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        s = (v or "").strip()
        if not _HHMM.match(s):
            raise ValueError("expected 24h HH:mm")
        return s

    def run_times_today(self) -> List[str]:
        """Start times each day: window_start + n * interval while <= window_end."""
        day = datetime.now().date()
        start = datetime.combine(day, datetime.strptime(self.window_start, "%H:%M").time())
        end = datetime.combine(day, datetime.strptime(self.window_end, "%H:%M").time())
        if end < start:
            raise ValueError("window_end must be on or after window_start")
        out: List[str] = []
        n = 0
        step = timedelta(hours=self.interval_hours)
        while True:
            t = start + n * step
            if t > end:
                break
            out.append(t.strftime("%H:%M"))
            n += 1
        if not out:
            raise ValueError("no run times in window; widen the window or lower interval")
        return out


def repo_root() -> Path:
    return _REPO_ROOT


def register_script_path() -> Path:
    return _REGISTER_SCRIPT


def load_batch_schedule(path: Path | None = None) -> BatchScheduleConfig:
    resolved = Path(path) if path else DEFAULT_PATH
    if not resolved.exists():
        return BatchScheduleConfig()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return BatchScheduleConfig()
    return BatchScheduleConfig.model_validate(raw)


def save_batch_schedule(cfg: BatchScheduleConfig, path: Path | None = None) -> None:
    resolved = Path(path) if path else DEFAULT_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode="json")
    resolved.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def client_host_is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


__all__ = [
    "BatchScheduleConfig",
    "DEFAULT_PATH",
    "client_host_is_loopback",
    "load_batch_schedule",
    "register_script_path",
    "repo_root",
    "save_batch_schedule",
]
