$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"
$exe = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe"
$outLog = Join-Path $artifactDir "launcher_t49_stdout.log"
$errLog = Join-Path $artifactDir "launcher_t49_stderr.log"
Get-CimInstance Win32_Process -Filter "Name='NordholdRealtimeLauncher.exe'" |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$proc = Start-Process -FilePath $exe -ArgumentList @("--no-browser","--port","8000") -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
for ($i=0; $i -lt 24; $i++) {
  Start-Sleep -Milliseconds 250
  try {
    $h = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
    [PSCustomObject]@{pid=$proc.Id; health=$h.status; out=$outLog; err=$errLog} | ConvertTo-Json -Depth 6
    exit 0
  } catch {}
}
throw "health check failed"
