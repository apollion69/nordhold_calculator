$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"
$candidates = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/calibration/candidates"
$ids = @($candidates.candidate_ids)
$rows = @()
foreach ($id in $ids) {
  $payload = @{
    process_name = "NordHold.exe"
    poll_ms = 1000
    require_admin = $false
    dataset_version = "1.0.0"
    calibration_candidates_path = [string]$candidates.path
    calibration_candidate_id = [string]$id
  }
  $resp = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/live/connect" -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 8)
  Start-Sleep -Milliseconds 200
  $snap = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/snapshot"
  $rows += [PSCustomObject]@{
    candidate = $id
    mode = $resp.mode
    reason = $resp.reason
    wave = $snap.wave
    gold = $snap.gold
    essence = $snap.essence
  }
}
$rows | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $artifactDir "candidate_probe_matrix.json") -Encoding UTF8
$rows | Format-Table -AutoSize | Out-String | Set-Content -Path (Join-Path $artifactDir "candidate_probe_matrix.txt") -Encoding UTF8
$rows | ConvertTo-Json -Depth 8
