# Start flask_sample meeting_advisor for resume-agent outreach enrichment.
# Default assumes sibling checkout: ...\resume-agent and ...\flask_sample
#
# Usage:
#   .\scripts\start_meeting_advisor.ps1
#   .\scripts\start_meeting_advisor.ps1 -FlaskSampleRoot "D:\src\flask_sample"

param(
    [string]$FlaskSampleRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $FlaskSampleRoot) {
    $resumeParent = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $FlaskSampleRoot = Join-Path $resumeParent "flask_sample"
}

if (-not (Test-Path $FlaskSampleRoot)) {
    Write-Error "flask_sample not found at $FlaskSampleRoot. Pass -FlaskSampleRoot with your clone path."
    exit 1
}

Set-Location $FlaskSampleRoot

$venvPy = Join-Path $FlaskSampleRoot ".venv\Scripts\python.exe"
$py = if (Test-Path $venvPy) { $venvPy } else { "python" }

Write-Host "Meeting advisor → http://127.0.0.1:5003 (MEETING_ADVISOR_URL in resume-agent .env)"
Write-Host "Using: $py in $FlaskSampleRoot"
& $py run_meeting_advisor.py
