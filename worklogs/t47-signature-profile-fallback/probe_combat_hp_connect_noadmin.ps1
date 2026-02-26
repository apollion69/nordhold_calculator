$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"
$path = Join-Path $artifactDir "memory_calibration_candidates_combat_hp_autoload_noadmin.json"
$payload = @{
  process_name = "NordHold.exe"
  poll_ms = 1000
  require_admin = $false
  dataset_version = "1.0.0"
  calibration_candidates_path = $path
  calibration_candidate_id = "artifact_combo_1"
}
$connect = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/live/connect" -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 8)
$status = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/status"
$snapshot = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/snapshot"
$connect | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_connect_combat_hp_noadmin.json") -Encoding UTF8
$status | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_status_combat_hp_noadmin.json") -Encoding UTF8
$snapshot | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_snapshot_combat_hp_noadmin.json") -Encoding UTF8
[PSCustomObject]@{
  mode = $status.mode
  reason = $status.reason
  memory_connected = $status.memory_connected
  candidate = $status.calibration_candidate
  raw_player_hp = $status.last_memory_values.player_hp
  raw_max_player_hp = $status.last_memory_values.max_player_hp
  base_hp_current = $snapshot.build.raw_memory_fields.base_hp_current
  base_hp_max = $snapshot.build.raw_memory_fields.base_hp_max
  wave = $snapshot.wave
  gold = $snapshot.gold
  essence = $snapshot.essence
} | ConvertTo-Json -Depth 8
