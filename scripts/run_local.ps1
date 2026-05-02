# Start the FastAPI app locally (no Docker, no AWS).
# If URLs 404 but tests pass, an old server may still own port 8000 — run:
#   powershell -ExecutionPolicy Bypass -File .\scripts\kill_port.ps1 8000
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Missing .venv. Run: python -m venv .venv && .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

Write-Host "Resume Agent → http://127.0.0.1:8000/  (Ctrl+C to stop)"
& $py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
