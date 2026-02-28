$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"
$exe = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe"
$outLog = Join-Path $artifactDir "launcher_stdout.log"
$errLog = Join-Path $artifactDir "launcher_stderr.log"
$pidPath = Join-Path $artifactDir "launcher_pid.txt"

Get-CimInstance Win32_Process -Filter "Name='NordholdRealtimeLauncher.exe'" |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$proc = Start-Process -FilePath $exe -ArgumentList @("--no-browser","--port","8000") -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
$proc.Id | Set-Content -Path $pidPath -Encoding ascii

$healthy = $false
for ($i = 0; $i -lt 24; $i++) {
  Start-Sleep -Milliseconds 250
  try {
    $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
    $healthy = $true
    $health | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $artifactDir "health.json") -Encoding UTF8
    break
  } catch {
  }
}
if (-not $healthy) {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  throw "Launcher health probe failed on 8000"
}

[PSCustomObject]@{
  pid = $proc.Id
  health = "ok"
  stdout = $outLog
  stderr = $errLog
} | ConvertTo-Json -Depth 5
