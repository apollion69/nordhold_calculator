$ErrorActionPreference = "SilentlyContinue"
$nowUtc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
$health = $null
$status = $null
$snapshot = $null
$healthErr = ""
$statusErr = ""
$snapshotErr = ""

try { $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8018/health" -TimeoutSec 3 } catch { $healthErr = $_.Exception.Message }
try { $status = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8018/api/v1/live/status" -TimeoutSec 3 } catch { $statusErr = $_.Exception.Message }
try { $snapshot = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8018/api/v1/live/snapshot" -TimeoutSec 3 } catch { $snapshotErr = $_.Exception.Message }

$result = [ordered]@{
  checked_at_utc = $nowUtc
  health = $health
  health_error = $healthErr
  status = $status
  status_error = $statusErr
  snapshot = $snapshot
  snapshot_error = $snapshotErr
}

$result | ConvertTo-Json -Depth 10
