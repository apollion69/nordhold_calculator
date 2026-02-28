$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"
$payload = @{
  process_name = "NordHold.exe"
  poll_ms = 1000
  require_admin = $false
  dataset_version = "1.0.0"
}
$connect = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/live/connect" -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 8)
$status = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/status"
$snapshot = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/snapshot"
$status | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_status_autoload_latest.json") -Encoding UTF8
$snapshot | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_snapshot_autoload_latest.json") -Encoding UTF8
[PSCustomObject]@{
  mode = $status.mode
  reason = $status.reason
  memory_connected = $status.memory_connected
  calibration_candidates_path = $status.calibration_candidates_path
  raw_player_hp = $status.last_memory_values.player_hp
  raw_max_player_hp = $status.last_memory_values.max_player_hp
  base_hp_current = $snapshot.build.raw_memory_fields.base_hp_current
  base_hp_max = $snapshot.build.raw_memory_fields.base_hp_max
} | ConvertTo-Json -Depth 8
