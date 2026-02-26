$ErrorActionPreference = "Stop"
$exe = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\runtime\dist_t47\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-t47-signature-profile-fallback-20260226_140357"
$outLog = Join-Path $artifactDir "launcher_t47_stdout.log"
$errLog = Join-Path $artifactDir "launcher_t47_stderr.log"
$responsePath = Join-Path $artifactDir "probe_live_connect_response.json"
$statusPath = Join-Path $artifactDir "probe_health.json"

Get-CimInstance Win32_Process -Filter "Name='NordholdRealtimeLauncher.exe'" |
  Where-Object { $_.CommandLine -like "*--port 8010*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$proc = Start-Process -FilePath $exe -ArgumentList @("--no-browser","--port","8010") -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog

$healthy = $false
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Milliseconds 250
  try {
    $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8010/health"
    $healthy = $true
    $health | ConvertTo-Json -Depth 5 | Set-Content -Path $statusPath -Encoding UTF8
    break
  } catch {
  }
}
if (-not $healthy) {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  throw "health probe failed on 8010"
}

$payload = @'
{
  "process_name": "NordHold.exe",
  "poll_ms": 1000,
  "require_admin": true,
  "dataset_version": "1.0.0",
  "signature_profile_id": "default_20985960@artifact_combo_1"
}
'@
$response = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8010/api/v1/live/connect" -ContentType "application/json" -Body $payload
$response | ConvertTo-Json -Depth 12 | Set-Content -Path $responsePath -Encoding UTF8
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
[PSCustomObject]@{response_path=$responsePath; status_path=$statusPath} | ConvertTo-Json -Depth 5
