$ErrorActionPreference = 'Stop'
$repo = 'C:\Users\lenovo\Documents\cursor\codex\projects\nordhold'
$exe = Join-Path $repo 'runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe'
if (!(Test-Path $exe)) { throw "EXE not found: $exe" }

$port = 8013
$base = "http://127.0.0.1:$port"
$outDir = Join-Path $repo 'runtime\logs'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$runId = "nordhold-t54-soak-$ts"
$outLog = Join-Path $outDir "$runId.out.log"
$errLog = Join-Path $outDir "$runId.err.log"
$summary = Join-Path $outDir "$runId.summary.json"

try {
  $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($conn) { Stop-Process -Id ($conn | Select-Object -First 1 -ExpandProperty OwningProcess) -Force -ErrorAction SilentlyContinue }
} catch {}

$p = Start-Process -FilePath $exe -ArgumentList @('--host','127.0.0.1','--port',"$port",'--no-browser') -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog

$ok = $false
for ($i=0; $i -lt 60; $i++) {
  try {
    $h = Invoke-RestMethod -Method Get -Uri "$base/health" -TimeoutSec 2
    if ($h.status -eq 'ok') { $ok = $true; break }
  } catch {}
  Start-Sleep -Milliseconds 500
}
if (-not $ok) {
  try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
  throw "Health check failed on $base"
}

$autoBody = @{
  process_name = 'NordHold.exe'
  poll_ms = 1000
  require_admin = $true
  dataset_version = '1.0.0'
  dataset_autorefresh = $true
} | ConvertTo-Json
$autoResp = $null
try {
  $autoResp = Invoke-RestMethod -Method Post -Uri "$base/api/v1/live/autoconnect" -Body $autoBody -ContentType 'application/json' -TimeoutSec 10
} catch {}

$seconds = 1860
$failCount = 0
$statusNotMemory = 0
$maxLatencyMs = 0.0
$lastMode = ''
$lastReason = ''
$lastMemoryConnected = $false

for ($i=1; $i -le $seconds; $i++) {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    $status = Invoke-RestMethod -Method Get -Uri "$base/api/v1/live/status" -TimeoutSec 3
    $null = Invoke-RestMethod -Method Get -Uri "$base/api/v1/live/snapshot" -TimeoutSec 3
    $null = Invoke-RestMethod -Method Get -Uri "$base/api/v1/run/state" -TimeoutSec 3
    $null = Invoke-WebRequest -Method Get -Uri "$base/api/v1/events?limit=1&heartbeat_ms=1" -TimeoutSec 3

    $lastMode = [string]$status.mode
    $lastReason = [string]$status.reason
    $lastMemoryConnected = [bool]$status.memory_connected
    if ($status.mode -ne 'memory') { $statusNotMemory++ }
  } catch {
    $failCount++
  }
  $sw.Stop()
  if ($sw.Elapsed.TotalMilliseconds -gt $maxLatencyMs) { $maxLatencyMs = $sw.Elapsed.TotalMilliseconds }
  Start-Sleep -Milliseconds 1000
}

$result = [ordered]@{
  run_id = $runId
  started_at = $ts
  duration_s = $seconds
  endpoint_cycle_failures = $failCount
  status_not_memory_count = $statusNotMemory
  max_cycle_latency_ms = [Math]::Round($maxLatencyMs, 2)
  last_mode = $lastMode
  last_reason = $lastReason
  last_memory_connected = $lastMemoryConnected
  autoconnect_response = $autoResp
  out_log = $outLog
  err_log = $errLog
}

$result | ConvertTo-Json -Depth 8 | Set-Content -Path $summary -Encoding UTF8
$result | ConvertTo-Json -Depth 8

try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
