<#
.SYNOPSIS
  Register (or re-register) the Windows Task Scheduler job that runs the
  resume-agent daily scrape + tailor cycle every morning.

.DESCRIPTION
  Creates a task named "resume-agent-daily" that runs
  `python -m app.jobs.daily_run` at 09:00 local time every day, using the
  repo's .venv if present (falls back to `python` on PATH). Existing task
  with the same name is replaced.

.PARAMETER RunTime
  Optional 24h HH:mm start time. Defaults to "09:00".

.PARAMETER RepoRoot
  Optional absolute path to the repo root. Defaults to the directory two
  levels up from this script.

.EXAMPLE
  PS> scripts\register_scheduled_task.ps1
  PS> scripts\register_scheduled_task.ps1 -RunTime 08:30
#>

param(
    [string]$RunTime = "09:00",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path
}

$TaskName = "resume-agent-daily"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    Write-Host "Using venv python: $PythonExe"
} else {
    $PythonExe = "python"
    Write-Warning "No .venv found at $VenvPython; falling back to 'python' on PATH."
}

$LogsDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir | Out-Null
}
$LogFile = Join-Path $LogsDir "daily_run.log"

# We wrap the python call in cmd /c so output gets redirected to a log file
# in a way Task Scheduler can persist across runs.
$Cmd = "cmd.exe"
$CmdArgs = "/c `"cd /d `"$RepoRoot`" && `"$PythonExe`" -m app.jobs.daily_run >> `"$LogFile`" 2>&1`""

$Action    = New-ScheduledTaskAction -Execute $Cmd -Argument $CmdArgs
$Trigger   = New-ScheduledTaskTrigger -Daily -At $RunTime
$Settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Replace any previous registration so this script is idempotent.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task '$TaskName'."
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "resume-agent: daily 9am scrape, tailor, and digest." `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal | Out-Null

Write-Host ""
Write-Host "Registered '$TaskName' to run daily at $RunTime."
Write-Host "  Repo:        $RepoRoot"
Write-Host "  Python:      $PythonExe"
Write-Host "  Log file:    $LogFile"
Write-Host ""
Write-Host "Manual run:    schtasks /run /tn $TaskName"
Write-Host "Tail log:      Get-Content '$LogFile' -Wait"
Write-Host "Remove task:   Unregister-ScheduledTask -TaskName $TaskName -Confirm:\$false"
