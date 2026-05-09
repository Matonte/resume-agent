"""Batch schedule config + API tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.jobs import batch_schedule as bs
from app.main import app


def test_run_times_grid() -> None:
    cfg = bs.BatchScheduleConfig(
        window_start="08:00",
        window_end="21:00",
        interval_hours=3,
    )
    assert cfg.run_times_today() == ["08:00", "11:00", "14:00", "17:00", "20:00"]


def test_run_times_rejects_inverted_window() -> None:
    with pytest.raises(ValueError):
        bs.BatchScheduleConfig(
            window_start="22:00",
            window_end="08:00",
            interval_hours=3,
        ).run_times_today()


def test_load_save_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "batch_schedule.yaml"
    cfg = bs.BatchScheduleConfig(
        window_start="09:30",
        window_end="18:00",
        interval_hours=2,
        task_name="test-task",
        extra_args="--no-email",
        execution_time_limit_minutes=0,
    )
    bs.save_batch_schedule(cfg, path)
    loaded = bs.load_batch_schedule(path)
    assert loaded == cfg


def test_client_host_is_loopback() -> None:
    assert bs.client_host_is_loopback("127.0.0.1")
    assert bs.client_host_is_loopback("::1")
    assert bs.client_host_is_loopback("localhost")
    assert not bs.client_host_is_loopback("192.168.1.1")
    assert not bs.client_host_is_loopback(None)


def test_api_get_put(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "batch_schedule.yaml"
    monkeypatch.setattr(bs, "DEFAULT_PATH", path)
    client = TestClient(app)
    r = client.get("/api/batch-schedule/")
    assert r.status_code == 200
    body = r.json()
    assert "run_times" in body
    assert body["window_start"] == "08:00"

    r2 = client.put(
        "/api/batch-schedule/",
        json={
            "window_start": "10:00",
            "window_end": "16:00",
            "interval_hours": 2,
            "task_name": "resume-agent-daily",
            "extra_args": "--verbose",
            "execution_time_limit_minutes": 0,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["run_times"] == ["10:00", "12:00", "14:00", "16:00"]
    assert path.is_file()


@pytest.mark.skipif(
    __import__("sys").platform != "win32",
    reason="apply-windows-task is Windows-only",
)
def test_apply_windows_task_requires_loopback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bs, "DEFAULT_PATH", tmp_path / "batch_schedule.yaml")
    bs.save_batch_schedule(bs.BatchScheduleConfig(), tmp_path / "batch_schedule.yaml")
    client = TestClient(app)
    r = client.post("/api/batch-schedule/apply-windows-task")
    assert r.status_code == 400


def test_apply_windows_task_mock_subprocess(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "batch_schedule.yaml"
    monkeypatch.setattr(bs, "DEFAULT_PATH", path)
    bs.save_batch_schedule(bs.BatchScheduleConfig(), path)
    monkeypatch.setattr("sys.platform", "win32")

    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "ok"
    proc.stderr = ""

    with (
        patch("app.routers.batch_schedule.client_host_is_loopback", return_value=True),
        patch("app.routers.batch_schedule.subprocess.run", return_value=proc) as run,
    ):
        client = TestClient(app)
        r = client.post(
            "/api/batch-schedule/apply-windows-task",
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    run.assert_called_once()
    args = run.call_args[0][0]
    assert "powershell.exe" in args[0].lower() or args[0].endswith("powershell.exe")
    assert "-WindowStart" in args
