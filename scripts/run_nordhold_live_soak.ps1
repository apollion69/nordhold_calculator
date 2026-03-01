param(
  [int]$DurationS = 300,
  [int]$Port = 8013,
  [int]$PollMs = 1000,
  [string]$ProcessName = "NordHold.exe",
  [bool]$RequireAdmin = $false,
  [bool]$AutoElevateForAdmin = $true,
  [bool]$HideLauncherWindow = $true,
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
    [string]$Body = "",
    [int]$TimeoutSec = 0
  )

  $uri = "$baseUrl$Path"
  if ($Method -eq "GET") {
    $effectiveTimeoutSec = if ($TimeoutSec -gt 0) { $TimeoutSec } else { 5 }
    return Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec $effectiveTimeoutSec
  }
  if ($Method -eq "POST") {
    $effectiveTimeoutSec = if ($TimeoutSec -gt 0) { $TimeoutSec } else { 10 }
    return Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json" -Body $Body -TimeoutSec $effectiveTimeoutSec
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

function Convert-ObjectToHashtable {
  param(
    [object]$InputObject
  )

  if ($null -eq $InputObject) {
    return @{}
  }
  if ($InputObject -is [hashtable]) {
    return @{} + $InputObject
  }

  $table = @{}
  foreach ($prop in $InputObject.PSObject.Properties) {
    $table[$prop.Name] = $prop.Value
  }
  return $table
}

function Test-IsAdminContext {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedPowerShellScript {
  param(
    [string]$ScriptPath,
    [int]$TimeoutSec = 30
  )

  $elevatedProc = Start-Process `
    -FilePath "powershell.exe" `
    -Verb RunAs `
    -WindowStyle Hidden `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) `
    -PassThru
  if (-not $elevatedProc.WaitForExit([Math]::Max(1, $TimeoutSec) * 1000)) {
    try {
      Stop-Process -Id $elevatedProc.Id -Force -ErrorAction SilentlyContinue
    }
    catch {
      # best effort
    }
    throw "Timed out waiting for elevated helper after $TimeoutSec seconds."
  }
  if ($elevatedProc.ExitCode -ne 0) {
    throw "Elevated helper failed with exit code $($elevatedProc.ExitCode)."
  }
}

function Stop-ProcessWithElevationFallback {
  param(
    [int]$ProcessId,
    [bool]$AllowElevationFallback = $false
  )

  if ($ProcessId -le 0) {
    return
  }

  try {
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    return
  }
  catch {
    if (-not $AllowElevationFallback) {
      return
    }
  }

  $stopScriptPath = Join-Path $logDir "$runId.stop-$ProcessId.ps1"
  $stopScript = @"
`$ErrorActionPreference = 'SilentlyContinue'
Stop-Process -Id $ProcessId -Force
"@
  Set-Content -Path $stopScriptPath -Value $stopScript -Encoding UTF8
  try {
    Invoke-ElevatedPowerShellScript -ScriptPath $stopScriptPath
  }
  finally {
    Remove-Item -Path $stopScriptPath -Force -ErrorAction SilentlyContinue
  }
}

function Start-LauncherProcess {
  param(
    [string]$ExecutablePath,
    [int]$LauncherPort,
    [string]$OutLogPath,
    [string]$ErrLogPath,
    [bool]$RunElevated = $false,
    [bool]$HideWindow = $true
  )

  $launcherArgs = @("--host", "127.0.0.1", "--port", "$LauncherPort", "--no-browser")
  if (-not $RunElevated) {
    $startArgs = @{
      FilePath = $ExecutablePath
      ArgumentList = $launcherArgs
      PassThru = $true
      RedirectStandardOutput = $OutLogPath
      RedirectStandardError = $ErrLogPath
    }
    if ($HideWindow) {
      $startArgs.WindowStyle = "Hidden"
    }
    return Start-Process @startArgs
  }

  $pidFilePath = Join-Path $logDir "$runId.launcher.pid"
  $bootstrapScriptPath = Join-Path $logDir "$runId.launcher.start-elevated.ps1"
  $windowStyleToken = if ($HideWindow) { "Hidden" } else { "Normal" }
  $launchScript = @"
`$ErrorActionPreference = 'Stop'
`$launcher = Start-Process -FilePath '$ExecutablePath' -ArgumentList @('--host','127.0.0.1','--port','$LauncherPort','--no-browser') -PassThru -RedirectStandardOutput '$OutLogPath' -RedirectStandardError '$ErrLogPath' -WindowStyle $windowStyleToken
Set-Content -Path '$pidFilePath' -Value `$launcher.Id -Encoding ASCII
"@
  Set-Content -Path $bootstrapScriptPath -Value $launchScript -Encoding UTF8
  try {
    Remove-Item -Path $pidFilePath -Force -ErrorAction SilentlyContinue
    Invoke-ElevatedPowerShellScript -ScriptPath $bootstrapScriptPath
    if (-not (Test-Path $pidFilePath)) {
      throw "Elevated launcher bootstrap did not produce pid file: $pidFilePath"
    }
    $launcherPid = [int](Get-Content -Path $pidFilePath | Select-Object -First 1)
    Start-Sleep -Milliseconds 250
    try {
      return Get-Process -Id $launcherPid -ErrorAction Stop
    }
    catch {
      # Process can exit immediately (e.g., port already bound by an existing launcher).
      # Caller will verify health on the target port and continue when possible.
      return $null
    }
  }
  finally {
    Remove-Item -Path $pidFilePath -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $bootstrapScriptPath -Force -ErrorAction SilentlyContinue
  }
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
$snapshotTransientFailureCount = 0
$maxSnapshotFailureStreak = 0
$snapshotFailuresTotalLast = 0
$adminFallbackApplied = $false
$autoconnectAttemptRequireAdmin = $RequireAdmin
$runCompleted = $false
$runAbortedReason = ""
$soakStartedUtc = (Get-Date).ToUniversalTime()
$isAdminContext = Test-IsAdminContext
$launcherNeedsElevation = $RequireAdmin -and (-not $isAdminContext) -and $AutoElevateForAdmin

if ($RequireAdmin -and -not $isAdminContext -and -not $AutoElevateForAdmin) {
  Write-Warning "RequireAdmin=true but current shell is not elevated and AutoElevateForAdmin=false; attach may fail."
}

try {
  # Best effort: free the target port before starting a fresh launcher process.
  try {
    $existingConn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($existingConn) {
      $existingPid = $existingConn | Select-Object -First 1 -ExpandProperty OwningProcess
      Stop-ProcessWithElevationFallback -ProcessId ([int]$existingPid) -AllowElevationFallback $false
      Start-Sleep -Milliseconds 300
    }
  }
  catch {
    # continue even if netstat query fails
  }

  $launcher = Start-LauncherProcess `
    -ExecutablePath $exePath `
    -LauncherPort $Port `
    -OutLogPath $launcherOutLog `
    -ErrLogPath $launcherErrLog `
    -RunElevated:$launcherNeedsElevation `
    -HideWindow:$HideLauncherWindow

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
      $autoconnectResponse = Invoke-Api -Method "POST" -Path "/api/v1/live/autoconnect" -Body $autoconnectPayload -TimeoutSec 60
    }
    catch {
      $autoconnectResponse = @{
        error = $_.Exception.Message
      }
    }

    $initialAutoconnectReason = [string]$autoconnectResponse.reason
    if (-not $RequireAdmin -and $initialAutoconnectReason -eq "process_found_but_admin_required") {
      $adminFallbackApplied = $true
      $autoconnectAttemptRequireAdmin = $true
      $fallbackAutoconnectPayload = @{
        process_name = $ProcessName
        poll_ms = $PollMs
        require_admin = $true
        dataset_version = $DatasetVersion
        dataset_autorefresh = $true
      } | ConvertTo-Json
      try {
        $autoconnectResponse = Invoke-Api -Method "POST" -Path "/api/v1/live/autoconnect" -Body $fallbackAutoconnectPayload -TimeoutSec 60
      }
      catch {
        $autoconnectResponse = @{
          error = $_.Exception.Message
          fallback_attempted = $true
          fallback_require_admin = $true
        }
      }
    }

    try {
      $statusAfterAutoconnect = Invoke-Api -Method "GET" -Path "/api/v1/live/status" -TimeoutSec 10
      $autoconnectFromStatus = Convert-ObjectToHashtable -InputObject $statusAfterAutoconnect.autoconnect_last_result
      if ($autoconnectFromStatus.Count -gt 0) {
        $existingAutoconnect = Convert-ObjectToHashtable -InputObject $autoconnectResponse
        if ($existingAutoconnect.ContainsKey("error") -and -not $autoconnectFromStatus.ContainsKey("request_error")) {
          $autoconnectFromStatus["request_error"] = [string]$existingAutoconnect["error"]
        }
        $autoconnectResponse = $autoconnectFromStatus
      }
    }
    catch {
      # keep original autoconnect response on status probe failures
    }
  }

  for ($i = 0; $i -lt $DurationS; $i++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
      $status = Invoke-Api -Method "GET" -Path "/api/v1/live/status"
      $null = Invoke-Api -Method "GET" -Path "/api/v1/live/snapshot"
      $null = Invoke-Api -Method "GET" -Path "/api/v1/run/state"

      $lastMode = [string]$status.mode
      $lastReason = [string]$status.reason
      $lastMemoryConnected = [bool]$status.memory_connected
      if (-not $NoAutoconnect) {
        $autoconnectFromStatus = Convert-ObjectToHashtable -InputObject $status.autoconnect_last_result
        if ($autoconnectFromStatus.Count -gt 0) {
          $existingAutoconnect = Convert-ObjectToHashtable -InputObject $autoconnectResponse
          if ($existingAutoconnect.Count -eq 0 -or $existingAutoconnect.ContainsKey("error")) {
            if ($existingAutoconnect.ContainsKey("error") -and -not $autoconnectFromStatus.ContainsKey("request_error")) {
              $autoconnectFromStatus["request_error"] = [string]$existingAutoconnect["error"]
            }
            $autoconnectResponse = $autoconnectFromStatus
          }
        }
      }
      if ($status.snapshot_failure_streak -ne $null) {
        $snapshotFailureStreak = [int]$status.snapshot_failure_streak
        if ($snapshotFailureStreak -gt $maxSnapshotFailureStreak) {
          $maxSnapshotFailureStreak = $snapshotFailureStreak
        }
      }
      if ($status.snapshot_failures_total -ne $null) {
        $snapshotFailuresTotalLast = [int]$status.snapshot_failures_total
      }
      if ($status.snapshot_transient_failure_count -ne $null) {
        $snapshotTransientFailureCount = [int]$status.snapshot_transient_failure_count
      }

      if ($status.mode -ne "memory") {
        $statusNotMemory++
      }
      if (-not $status.memory_connected) {
        $memoryConnectedFalse++
      }

      # Keep SSE probe in cycle, but do not drop status/snapshot metrics if this call fails.
      try {
        $null = Invoke-WebRequest -Method Get -Uri "$baseUrl/api/v1/events?limit=1&heartbeat_ms=1" -TimeoutSec 5
      }
      catch {
        $failures++
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
      auto_elevate_for_admin = $AutoElevateForAdmin
      launcher_elevated = $launcherNeedsElevation
      launcher_window_hidden = $HideLauncherWindow
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
      snapshot_transient_failure_count = $snapshotTransientFailureCount
      max_snapshot_failure_streak = $maxSnapshotFailureStreak
      snapshot_failures_total_last = $snapshotFailuresTotalLast
      admin_fallback_applied = $adminFallbackApplied
      autoconnect_attempt_require_admin = $autoconnectAttemptRequireAdmin
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
    auto_elevate_for_admin = $AutoElevateForAdmin
    launcher_elevated = $launcherNeedsElevation
    launcher_window_hidden = $HideLauncherWindow
    dataset_version = $DatasetVersion
    iterations = $iterations
    endpoint_cycle_failures = $failures
    status_not_memory_count = $statusNotMemory
    memory_connected_false_count = $memoryConnectedFalse
    max_cycle_latency_ms = [Math]::Round($maxCycleLatencyMs, 2)
    last_mode = $lastMode
    last_reason = $lastReason
    last_memory_connected = $lastMemoryConnected
    snapshot_transient_failure_count = $snapshotTransientFailureCount
    max_snapshot_failure_streak = $maxSnapshotFailureStreak
    snapshot_failures_total_last = $snapshotFailuresTotalLast
    admin_fallback_applied = $adminFallbackApplied
    autoconnect_attempt_require_admin = $autoconnectAttemptRequireAdmin
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
    auto_elevate_for_admin = $AutoElevateForAdmin
    launcher_elevated = $launcherNeedsElevation
    launcher_window_hidden = $HideLauncherWindow
    dataset_version = $DatasetVersion
    iterations = $iterations
    endpoint_cycle_failures = $failures
    status_not_memory_count = $statusNotMemory
    memory_connected_false_count = $memoryConnectedFalse
    max_cycle_latency_ms = [Math]::Round($maxCycleLatencyMs, 2)
    last_mode = $lastMode
    last_reason = $lastReason
    last_memory_connected = $lastMemoryConnected
    snapshot_transient_failure_count = $snapshotTransientFailureCount
    max_snapshot_failure_streak = $maxSnapshotFailureStreak
    snapshot_failures_total_last = $snapshotFailuresTotalLast
    admin_fallback_applied = $adminFallbackApplied
    autoconnect_attempt_require_admin = $autoconnectAttemptRequireAdmin
    autoconnect = $autoconnectResponse
    launcher_pid = if ($launcher) { $launcher.Id } else { 0 }
    launcher_out_log = $launcherOutLog
    launcher_err_log = $launcherErrLog
    summary_path = $summaryPath
  }
  Set-Content -Path $partialPath -Value ($partialTail | ConvertTo-Json -Depth 8) -Encoding UTF8

  if ($launcher -and -not $KeepLauncherRunning) {
    Stop-ProcessWithElevationFallback -ProcessId ([int]$launcher.Id) -AllowElevationFallback $false
  }

  $summaryJson
}
