$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"
$s1 = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/snapshot"
Start-Sleep -Milliseconds 1800
$s2 = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/live/snapshot"
$payload = [PSCustomObject]@{snapshot_1=$s1; snapshot_2=$s2}
$payload | ConvertTo-Json -Depth 14 | Set-Content -Path (Join-Path $artifactDir "live_snapshot_pair.json") -Encoding UTF8
[PSCustomObject]@{
  wave1=$s1.wave
  gold1=$s1.gold
  essence1=$s1.essence
  wave2=$s2.wave
  gold2=$s2.gold
  essence2=$s2.essence
} | ConvertTo-Json -Depth 8
