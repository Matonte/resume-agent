# Stop process(es) listening on a TCP port (default 8000). Run from repo root:
#   powershell -ExecutionPolicy Bypass -File .\scripts\kill_port.ps1 8000
param(
    [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "No listener on port $Port."
    exit 0
}
$pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $pids) {
    try {
        $p = Get-Process -Id $procId -ErrorAction Stop
        Write-Host "Stopping PID $procId ($($p.ProcessName)) on port $Port"
        Stop-Process -Id $procId -Force
    } catch {
        Write-Warning "Could not stop PID $procId : $_"
    }
}
