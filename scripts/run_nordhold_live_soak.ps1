param(
  [int]$DurationS = 300,
  [int]$Port = 8013,
  [int]$PollMs = 1000,
  [string]$ProcessName = "NordHold.exe",
  [bool]$RequireAdmin = $true,
  [string]$DatasetVersion = "1.0.0",
  [switch]$NoAutoconnect,
  [switch]$KeepLauncherRunning
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$exePath = Join-Path $projectRoot "runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe"
if (-not (Test-Path $exePath)) {
  throw "EXE was not found: $exePath"
}

$logDir = Join-Path $projectRoot "runtime\logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runId = "nordhold-live-soak-$timestamp"
$launcherOutLog = Join-Path $logDir "$runId.launcher.out.log"
$launcherErrLog = Join-Path $logDir "$runId.launcher.err.log"
$summaryPath = Join-Path $logDir "$runId.summary.json"
$partialPath = Join-Path $logDir "$runId.partial.json"
$baseUrl = "http://127.0.0.1:$Port"

function Invoke-Api {
  param(
    [string]$Method,
    [string]$Path,
    [string]$Body = ""
  )

  $uri = "$baseUrl$Path"
  if ($Method -eq "GET") {
    return Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 5
  }
  if ($Method -eq "POST") {
    return Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json" -Body $Body -TimeoutSec 10
  }
  throw "Unsupported method: $Method"
}

function Wait-ApiHealth {
  param(
    [int]$MaxAttempts = 60
  )

  for ($i = 0; $i -lt $MaxAttempts; $i++) {
    try {
      $health = Invoke-Api -Method "GET" -Path "/health"
      if ($health.status -eq "ok") {
        return $true
      }
    }
    catch {
      # wait and retry
    }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

$launcher = $null
$autoconnectResponse = $null
$failures = 0
$statusNotMemory = 0
$memoryConnectedFalse = 0
$maxCycleLatencyMs = 0.0
$iterations = 0
$lastMode = ""
$lastReason = ""
$lastMemoryConnected = $false
$runCompleted = $false
$runAbortedReason = ""
$soakStartedUtc = (Get-Date).ToUniversalTime()

try {
  # Best effort: free the target port before starting a fresh launcher process.
  try {
    $existingConn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($existingConn) {
      $existingPid = $existingConn | Select-Object -First 1 -ExpandProperty OwningProcess
      Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 300
    }
  }
  catch {
    # continue even if netstat query fails
  }

  $launcher = Start-Process `
    -FilePath $exePath `
    -ArgumentList @("--host", "127.0.0.1", "--port", "$Port", "--no-browser") `
    -PassThru `
    -RedirectStandardOutput $launcherOutLog `
    -RedirectStandardError $launcherErrLog

  if (-not (Wait-ApiHealth -MaxAttempts 60)) {
    throw "API health check did not become ready on $baseUrl"
  }

  if (-not $NoAutoconnect) {
    $autoconnectPayload = @{
      process_name = $ProcessName
      poll_ms = $PollMs
      require_admin = $RequireAdmin
      dataset_version = $DatasetVersion
      dataset_autorefresh = $true
    } | ConvertTo-Json

    try {
      $autoconnectResponse = Invoke-Api -Method "POST" -Path "/api/v1/live/autoconnect" -Body $autoconnectPayload
    }
    catch {
      $autoconnectResponse = @{
        error = $_.Exception.Message
      }
    }
  }

  for ($i = 0; $i -lt $DurationS; $i++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
      $status = Invoke-Api -Method "GET" -Path "/api/v1/live/status"
      $null = Invoke-Api -Method "GET" -Path "/api/v1/live/snapshot"
      $null = Invoke-Api -Method "GET" -Path "/api/v1/run/state"
      $null = Invoke-WebRequest -Method Get -Uri "$baseUrl/api/v1/events?limit=1&heartbeat_ms=1" -TimeoutSec 5

      $lastMode = [string]$status.mode
      $lastReason = [string]$status.reason
      $lastMemoryConnected = [bool]$status.memory_connected

      if ($status.mode -ne "memory") {
        $statusNotMemory++
      }
      if (-not $status.memory_connected) {
        $memoryConnectedFalse++
      }
    }
    catch {
      $failures++
    }
    $sw.Stop()
    if ($sw.Elapsed.TotalMilliseconds -gt $maxCycleLatencyMs) {
      $maxCycleLatencyMs = $sw.Elapsed.TotalMilliseconds
    }
    $iterations++

    $elapsedS = [int]([Math]::Round(((Get-Date).ToUniversalTime() - $soakStartedUtc).TotalSeconds, 0))
    $partial = [ordered]@{
      run_id = $runId
      timestamp_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
      duration_s = $DurationS
      poll_ms = $PollMs
      port = $Port
      process_name = $ProcessName
      require_admin = $RequireAdmin
      dataset_version = $DatasetVersion
      iterations = $iterations
      elapsed_s = $elapsedS
      completed = $false
      endpoint_cycle_failures = $failures
      status_not_memory_count = $statusNotMemory
      memory_connected_false_count = $memoryConnectedFalse
      max_cycle_latency_ms = [Math]::Round($maxCycleLatencyMs, 2)
      last_mode = $lastMode
      last_reason = $lastReason
      last_memory_connected = $lastMemoryConnected
      autoconnect = $autoconnectResponse
      launcher_pid = if ($launcher) { $launcher.Id } else { 0 }
      launcher_out_log = $launcherOutLog
      launcher_err_log = $launcherErrLog
      summary_path = $summaryPath
    }
    Set-Content -Path $partialPath -Value ($partial | ConvertTo-Json -Depth 8) -Encoding UTF8

    Start-Sleep -Milliseconds $PollMs
  }
  $runCompleted = $true
}
catch {
  $runAbortedReason = $_.Exception.Message
}
finally {
  $elapsedS = [int]([Math]::Round(((Get-Date).ToUniversalTime() - $soakStartedUtc).TotalSeconds, 0))
  $summary = [ordered]@{
    run_id = $runId
    timestamp_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
    duration_s = $DurationS
    elapsed_s = $elapsedS
    completed = $runCompleted
    interrupted = (-not $runCompleted)
    aborted_reason = $runAbortedReason
    poll_ms = $PollMs
    port = $Port
    process_name = $ProcessName
    require_admin = $RequireAdmin
    dataset_version = $DatasetVersion
    iterations = $iterations
    endpoint_cycle_failures = $failures
    status_not_memory_count = $statusNotMemory
    memory_connected_false_count = $memoryConnectedFalse
    max_cycle_latency_ms = [Math]::Round($maxCycleLatencyMs, 2)
    last_mode = $lastMode
    last_reason = $lastReason
    last_memory_connected = $lastMemoryConnected
    autoconnect = $autoconnectResponse
    launcher_pid = if ($launcher) { $launcher.Id } else { 0 }
    launcher_out_log = $launcherOutLog
    launcher_err_log = $launcherErrLog
    partial_path = $partialPath
  }
  $summaryJson = $summary | ConvertTo-Json -Depth 8
  Set-Content -Path $summaryPath -Value $summaryJson -Encoding UTF8

  if ($runCompleted) {
    Write-Host "Soak completed."
  }
  else {
    Write-Warning "Soak interrupted before target duration."
  }
  Write-Host "Summary: $summaryPath"

  # Keep a terminal partial snapshot for consistent external readers.
  $partialTail = [ordered]@{
    run_id = $runId
    timestamp_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
    duration_s = $DurationS
    elapsed_s = $elapsedS
    completed = $runCompleted
    interrupted = (-not $runCompleted)
    aborted_reason = $runAbortedReason
    poll_ms = $PollMs
    port = $Port
    process_name = $ProcessName
    require_admin = $RequireAdmin
    dataset_version = $DatasetVersion
    iterations = $iterations
    endpoint_cycle_failures = $failures
    status_not_memory_count = $statusNotMemory
    memory_connected_false_count = $memoryConnectedFalse
    max_cycle_latency_ms = [Math]::Round($maxCycleLatencyMs, 2)
    last_mode = $lastMode
    last_reason = $lastReason
    last_memory_connected = $lastMemoryConnected
    autoconnect = $autoconnectResponse
    launcher_pid = if ($launcher) { $launcher.Id } else { 0 }
    launcher_out_log = $launcherOutLog
    launcher_err_log = $launcherErrLog
    summary_path = $summaryPath
  }
  Set-Content -Path $partialPath -Value ($partialTail | ConvertTo-Json -Depth 8) -Encoding UTF8

  if ($launcher -and -not $KeepLauncherRunning) {
    try {
      Stop-Process -Id $launcher.Id -Force -ErrorAction SilentlyContinue
    }
    catch {
      # best effort
    }
  }

  $summaryJson
}
