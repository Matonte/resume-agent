# Run the daily pipeline locally (scrapers + tailor). Default: no digest email.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Missing .venv. Run: python -m venv .venv && .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

$extra = $args
if ($extra.Count -eq 0) {
    $extra = @("--no-email", "--verbose")
}

& $py -m app.jobs.daily_run @extra
