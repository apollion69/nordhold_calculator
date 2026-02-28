$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"

$status0 = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/status"
$status0 | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_status_before.json") -Encoding UTF8

$candidates = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/calibration/candidates"
$candidates | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_candidates.json") -Encoding UTF8

$connectPayload = @{
  process_name = "NordHold.exe"
  poll_ms = 1000
  require_admin = $true
  dataset_version = "1.0.0"
}
if ($candidates.path) {
  $connectPayload.calibration_candidates_path = [string]$candidates.path
}
if ($candidates.recommended_candidate_id) {
  $connectPayload.calibration_candidate_id = [string]$candidates.recommended_candidate_id
} elseif ($candidates.active_candidate_id) {
  $connectPayload.calibration_candidate_id = [string]$candidates.active_candidate_id
}

$connectBody = $connectPayload | ConvertTo-Json -Depth 8
$connectResp = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/live/connect" -ContentType "application/json" -Body $connectBody
$connectResp | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_connect_response.json") -Encoding UTF8

Start-Sleep -Milliseconds 1200
$status1 = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/status"
$status1 | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_status_after.json") -Encoding UTF8

$snapshot1 = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/snapshot"
$snapshot1 | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_snapshot_after.json") -Encoding UTF8

[PSCustomObject]@{
  mode = $status1.mode
  reason = $status1.reason
  memory_connected = $status1.memory_connected
  signature_profile = $status1.signature_profile
  candidate = $status1.calibration_candidate
  coverage = $status1.field_coverage
  calibration_quality = $status1.calibration_quality
} | ConvertTo-Json -Depth 8
