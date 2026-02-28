$ErrorActionPreference = 'Stop'
$projectRoot = 'C:\Users\lenovo\Documents\cursor\codex\projects\nordhold'
$distRoot = Join-Path $projectRoot 'runtime\dist'
$freshRoot = Join-Path $projectRoot 'runtime\dist_t39'
$targetDir = Join-Path $distRoot 'NordholdRealtimeLauncher'
$freshDir = Join-Path $freshRoot 'NordholdRealtimeLauncher'
$exe = Join-Path $targetDir 'NordholdRealtimeLauncher.exe'

if (-not (Test-Path $freshDir)) {
  throw "Fresh build folder not found: $freshDir"
}

Get-Process -Name 'NordholdRealtimeLauncher' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$listener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -ne $listener) {
  try { Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop } catch {}
}

if (Test-Path $targetDir) {
  Remove-Item -Path $targetDir -Recurse -Force
}
Copy-Item -Path $freshDir -Destination $distRoot -Recurse -Force

if (-not (Test-Path $exe)) {
  throw "Target EXE missing after copy: $exe"
}

$proc = Start-Process -FilePath $exe -ArgumentList '--host','127.0.0.1','--port','8000','--no-browser' -PassThru
Start-Sleep -Seconds 3
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health'

Write-Output ("PID=" + $proc.Id)
Write-Output ("EXE_TS=" + ((Get-Item $exe).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')))
Write-Output ("HEALTH=" + ($health | ConvertTo-Json -Compress))
