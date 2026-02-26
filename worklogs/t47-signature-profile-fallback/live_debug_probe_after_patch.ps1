$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"
$exe = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe"
$outLog = Join-Path $artifactDir "launcher_after_patch_stdout.log"
$errLog = Join-Path $artifactDir "launcher_after_patch_stderr.log"

Get-CimInstance Win32_Process -Filter "Name='NordholdRealtimeLauncher.exe'" |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$proc = Start-Process -FilePath $exe -ArgumentList @("--no-browser","--port","8000") -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog

$healthy = $false
for ($i = 0; $i -lt 24; $i++) {
  Start-Sleep -Milliseconds 250
  try {
    $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
    $healthy = $true
    break
  } catch {
  }
}
if (-not $healthy) {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  throw "Launcher health probe failed on 8000"
}

$candidates = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/calibration/candidates"
$candidates | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_candidates_after_patch.json") -Encoding UTF8

$candidateId = ""
if ($candidates.recommended_candidate_id) { $candidateId = [string]$candidates.recommended_candidate_id }
elseif ($candidates.active_candidate_id) { $candidateId = [string]$candidates.active_candidate_id }

$basePayload = @{
  process_name = "NordHold.exe"
  poll_ms = 1000
  dataset_version = "1.0.0"
}
if ($candidates.path) { $basePayload.calibration_candidates_path = [string]$candidates.path }
if ($candidateId) { $basePayload.calibration_candidate_id = $candidateId }

$payloadAdmin = $basePayload.Clone()
$payloadAdmin.require_admin = $true
$respAdmin = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/live/connect" -ContentType "application/json" -Body ($payloadAdmin | ConvertTo-Json -Depth 8)
$respAdmin | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_connect_after_patch_require_admin_true.json") -Encoding UTF8

$payloadUser = $basePayload.Clone()
$payloadUser.require_admin = $false
$respUser = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/live/connect" -ContentType "application/json" -Body ($payloadUser | ConvertTo-Json -Depth 8)
$respUser | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_connect_after_patch_require_admin_false.json") -Encoding UTF8

$status = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/status"
$status | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_status_after_patch.json") -Encoding UTF8

$snapshot = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/snapshot"
$snapshot | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_snapshot_after_patch.json") -Encoding UTF8

[PSCustomObject]@{
  pid = $proc.Id
  require_admin_true = @{ mode = $respAdmin.mode; reason = $respAdmin.reason; memory_connected = $respAdmin.memory_connected }
  require_admin_false = @{ mode = $respUser.mode; reason = $respUser.reason; memory_connected = $respUser.memory_connected }
  final_status = @{ mode = $status.mode; reason = $status.reason; memory_connected = $status.memory_connected; wave = $snapshot.wave; gold = $snapshot.gold; essence = $snapshot.essence }
} | ConvertTo-Json -Depth 12
