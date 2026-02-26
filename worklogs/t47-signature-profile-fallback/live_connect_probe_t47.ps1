$ErrorActionPreference = "Stop"
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
$response | ConvertTo-Json -Depth 12
