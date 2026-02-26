$ErrorActionPreference = "Stop"
$artifactDir = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-realtime-live-debug-20260226_142333"
$payload = @'
{
  "process_name": "NordHold.exe",
  "poll_ms": 1000,
  "require_admin": false,
  "dataset_version": "1.0.0"
}
'@
$response = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/live/connect" -ContentType "application/json" -Body $payload
$response | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $artifactDir "live_connect_noadmin_response.json") -Encoding UTF8
[PSCustomObject]@{mode=$response.mode;reason=$response.reason;memory_connected=$response.memory_connected;signature_profile=$response.signature_profile;last_error=$response.last_error} | ConvertTo-Json -Depth 8
