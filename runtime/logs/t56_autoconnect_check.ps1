$ErrorActionPreference='Stop'
$base='http://127.0.0.1:8018'
$payload=@{
  process_name='NordHold.exe'
  poll_ms=1000
  require_admin=$true
  dataset_version='1.0.0'
}
$r=Invoke-RestMethod -Uri "$base/api/v1/live/autoconnect" -Method Post -ContentType 'application/json' -Body ($payload | ConvertTo-Json -Depth 6)
$r | ConvertTo-Json -Depth 10
