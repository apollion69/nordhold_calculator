$ErrorActionPreference = "Stop"
$payload = @{
  process_name = "NordHold.exe"
  poll_ms = 1000
  require_admin = $false
  dataset_version = "1.0.0"
}
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/live/connect" -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 8) | Out-Null
$s = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/snapshot"
[PSCustomObject]@{
  wave = $s.wave
  base_hp_current = $s.build.raw_memory_fields.base_hp_current
  base_hp_max = $s.build.raw_memory_fields.base_hp_max
  leaks_total = $s.build.raw_memory_fields.leaks_total
  is_combat_phase = $s.build.raw_memory_fields.is_combat_phase
} | ConvertTo-Json -Depth 6
