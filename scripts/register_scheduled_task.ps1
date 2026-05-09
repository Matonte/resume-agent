<#
.SYNOPSIS
  Register (or re-register) the Windows Task Scheduler job that runs the
  resume-agent scrape + tailor cycle on a repeating daytime schedule.

.DESCRIPTION
  Creates a task named "resume-agent-daily" that runs
  `python -m app.jobs.daily_run` using the repo's .venv (falls back to `python`
  on PATH). Existing task with the same name is replaced.

  Default schedule: every 3 hours starting at 08:00 local time, with run times
  at 08:00, 11:00, 14:00, 17:00, and 20:00 (last start at or before -WindowEnd).

  **Previous versions used a 30-minute execution limit**, which often kills
  this job mid-run (Playwright + LLM). The limit is now unlimited unless you
  override -ExecutionTimeLimitMinutes.

.PARAMETER WindowStart
  First run time each day (24h HH:mm). Default "08:00".

.PARAMETER WindowEnd
  Latest allowed *start* time each day (24h HH:mm). Default "21:00".
  Run times are WindowStart + n * IntervalHours while still <= WindowEnd.

.PARAMETER IntervalHours
  Hours between starts. Default 3.

.PARAMETER TaskName
  Scheduled task name. Default "resume-agent-daily".

.PARAMETER RepoRoot
  Optional absolute path to the repo root. Defaults to the parent of scripts/.

.PARAMETER ExtraArgs
  Extra arguments for daily_run (single string). Default "--verbose".
  Example: '--no-email --verbose'

.PARAMETER ExecutionTimeLimitMinutes
  Task Scheduler hard cap in minutes; 0 = no limit (recommended). Default 0.

.EXAMPLE
  PS> scripts\register_scheduled_task.ps1

.EXAMPLE
  PS> scripts\register_scheduled_task.ps1 -WindowStart "09:00" -IntervalHours 2 -WindowEnd "18:00"
#>

param(
    [string]$WindowStart = "08:00",
    [string]$WindowEnd = "21:00",
    [int]$IntervalHours = 3,
    [string]$TaskName = "resume-agent-daily",
    [string]$RepoRoot = "",
    [string]$ExtraArgs = "--verbose",
    [int]$ExecutionTimeLimitMinutes = 0
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path
}

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

function Get-ScheduledRunTimes {
    param(
        [string]$StartHHmm,
        [string]$EndHHmm,
        [int]$StepHours
    )
    $day = [DateTime]::Today
    $startT = [DateTime]::ParseExact($StartHHmm, "HH:mm", $null).TimeOfDay
    $endT = [DateTime]::ParseExact($EndHHmm, "HH:mm", $null).TimeOfDay
    $start = $day + $startT
    $end = $day + $endT
    if ($end -lt $start) {
        throw "WindowEnd must be on or after WindowStart (same calendar day)."
    }
    $times = [System.Collections.Generic.List[string]]::new()
    $n = 0
    while ($true) {
        $t = $start.AddHours($n * $StepHours)
        if ($t -gt $end) { break }
        $times.Add($t.ToString("HH:mm"))
        $n++
    }
    if ($times.Count -eq 0) {
        throw "No run times in window $StartHHmm .. $EndHHmm with interval ${StepHours}h."
    }
    return $times
}

$runTimes = Get-ScheduledRunTimes -StartHHmm $WindowStart -EndHHmm $WindowEnd -StepHours $IntervalHours
Write-Host "Run times (local): $($runTimes -join ', ')"

$argTail = if ([string]::IsNullOrWhiteSpace($ExtraArgs)) { "" } else { " $ExtraArgs" }
# Log separator + run (append stdout/stderr). cmd /c keeps quoting predictable for Task Scheduler.
$Cmd = "cmd.exe"
$Inner = "cd /d `"$RepoRoot`" && `"$PythonExe`" -m app.jobs.daily_run$argTail >> `"$LogFile`" 2>&1"
$CmdArgs = "/c `"$Inner`""

$Action = New-ScheduledTaskAction -Execute $Cmd -Argument $CmdArgs

$Triggers = foreach ($rt in $runTimes) {
    New-ScheduledTaskTrigger -Daily -At $rt
}

$limit = if ($ExecutionTimeLimitMinutes -le 0) {
    [TimeSpan]::Zero
} else {
    New-TimeSpan -Minutes $ExecutionTimeLimitMinutes
}

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit $limit `
    -MultipleInstances Queue

# Interactive = only when this user is logged on (matches typical dev machine).
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task '$TaskName'."
}

$desc = "resume-agent: scrape + tailor every ${IntervalHours}h from $WindowStart to last start <= $WindowEnd."

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description $desc `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Principal $Principal | Out-Null

Write-Host ""
Write-Host "Registered '$TaskName' with $($Triggers.Count) daily trigger(s)."
Write-Host "  Repo:        $RepoRoot"
Write-Host "  Python:      $PythonExe"
Write-Host "  Log file:    $LogFile"
$limitLabel = if ($ExecutionTimeLimitMinutes -le 0) { "none (TimeSpan zero)" } else { "$ExecutionTimeLimitMinutes min" }
Write-Host "  Exec limit:  $limitLabel"
Write-Host ""
Write-Host "Manual run:    schtasks /run /tn $TaskName"
Write-Host "Tail log:      Get-Content '$LogFile' -Wait"
Write-Host ('Remove task:   Unregister-ScheduledTask -TaskName ' + $TaskName + ' -Confirm:$false')
Write-Host ""
Write-Host "Note: LogonType Interactive - runs only while this Windows user is logged in."
Write-Host "      If a run is still going when the next slot fires, instances are queued."
