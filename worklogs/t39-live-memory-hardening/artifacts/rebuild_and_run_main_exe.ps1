$ErrorActionPreference = 'Stop'
$projectRoot = 'C:\Users\lenovo\Documents\cursor\codex\projects\nordhold'
$buildScript = Join-Path $projectRoot 'scripts\build_nordhold_realtime_exe.ps1'
$exe = Join-Path $projectRoot 'runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe'

# Stop previous launcher instances to release file locks.
Get-Process -Name 'NordholdRealtimeLauncher' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Also stop listener on port 8000 if it is our old launcher process.
$listener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -ne $listener) {
  try { Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop } catch {}
}

# Rebuild in canonical dist path.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $buildScript -SkipFrontendBuild

if (-not (Test-Path $exe)) {
  throw "EXE not found after build: $exe"
}

# Start fresh runtime.
$proc = Start-Process -FilePath $exe -ArgumentList '--host','127.0.0.1','--port','8000','--no-browser' -PassThru
Start-Sleep -Seconds 3

$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health'
$status = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/live/status'

Write-Output ("PID=" + $proc.Id)
Write-Output ("HEALTH=" + ($health | ConvertTo-Json -Compress))
Write-Output ("STATUS_MODE=" + $status.mode)
Write-Output ("STATUS_REASON=" + $status.reason)
