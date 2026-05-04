# Start Contact Advisor stack meeting_advisor for resume-agent outreach enrichment.
# Default assumes sibling checkout: ...\resume-agent and ...\contact_advisor (or ...\flask_sample).
#
# Usage:
#   .\scripts\start_meeting_advisor.ps1
#   .\scripts\start_meeting_advisor.ps1 -RepoRoot "D:\src\contact_advisor"
#   .\scripts\start_meeting_advisor.ps1 -FlaskSampleRoot "D:\src\flask_sample"   # deprecated alias

param(
    [Alias("FlaskSampleRoot")]
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $resumeParent = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    foreach ($name in @("contact_advisor", "flask_sample")) {
        $candidate = Join-Path $resumeParent $name
        if (Test-Path $candidate) {
            $RepoRoot = $candidate
            break
        }
    }
}

if (-not $RepoRoot -or -not (Test-Path $RepoRoot)) {
    Write-Error "Contact Advisor repo not found. Clone beside resume-agent as ``contact_advisor`` or ``flask_sample``, or pass -RepoRoot."
    exit 1
}

Set-Location $RepoRoot

$venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$py = if (Test-Path $venvPy) { $venvPy } else { "python" }

Write-Host "Default advisor URL is often http://127.0.0.1:5003 — set MEETING_ADVISOR_URL in resume-agent .env (e.g. http://127.0.0.1:8000 if mounted there)."
Write-Host "Using: $py in $RepoRoot"
& $py run_meeting_advisor.py
