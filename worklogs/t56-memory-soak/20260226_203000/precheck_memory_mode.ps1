param(
  [string]$ProjectRoot,
  [string]$RunDir,
  [int]$Port = 8013,
  [int]$PollMs = 1000,
  [string]$ProcessName = "NordHold.exe",
  [string]$DatasetVersion = "1.0.0"
)

$ErrorActionPreference = "Stop"
$baseUrl = "http://127.0.0.1:$Port"
$exePath = Join-Path $ProjectRoot "runtime\\dist\\NordholdRealtimeLauncher\\NordholdRealtimeLauncher.exe"
$runtimeLogDir = Join-Path $ProjectRoot "runtime\\logs"
New-Item -ItemType Directory -Path $runtimeLogDir -Force | Out-Null
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$launcherOutLog = Join-Path $runtimeLogDir "t56-precheck-$timestamp.launcher.out.log"
$launcherErrLog = Join-Path $runtimeLogDir "t56-precheck-$timestamp.launcher.err.log"
$processCheckPath = Join-Path $RunDir "01_process_check.json"
$precheckPath = Join-Path $RunDir "02_precheck_result.json"
$diagnosticPath = Join-Path $RunDir "03_diagnostic_attempt.json"

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
  param([int]$MaxAttempts = 60)

  for ($i = 0; $i -lt $MaxAttempts; $i++) {
    try {
      $health = Invoke-Api -Method "GET" -Path "/health"
      if ($health.status -eq "ok") {
        return $true
      }
    }
    catch {
      # continue
    }
    Start-Sleep -Milliseconds 500
  }

  return $false
}

$processCommand = 'Get-CimInstance Win32_Process -Filter "name=''NordHold.exe''" | Select-Object ProcessId,Name,ExecutablePath,CommandLine'
$processes = @(Get-CimInstance Win32_Process -Filter "name='NordHold.exe'" | Select-Object ProcessId, Name, ExecutablePath, CommandLine)

$processCheck = [ordered]@{
  checked_at_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
  command = $processCommand
  process_count = $processes.Count
  processes = $processes
}

$processCheck | ConvertTo-Json -Depth 8 | Set-Content -Path $processCheckPath -Encoding UTF8

if ($processes.Count -eq 0) {
  $blocker = [ordered]@{
    precheck_pass = $false
    blocker = "NordHold.exe process is not running"
    process_check = $processCheck
  }

  $blocker | ConvertTo-Json -Depth 8 | Set-Content -Path $precheckPath -Encoding UTF8
  Write-Host "BLOCKER: NordHold.exe process is not running"
  Get-Content -Path $processCheckPath
  exit 10
}

$launcher = $null
$launcherStarted = $false
$launcherPid = 0
$healthBeforeLaunch = $false
$healthAfterLaunch = $false
$autoconnectResponse = $null
$autoconnectError = ""
$statusChecks = @()
$precheckPass = $false

try {
  try {
    $health = Invoke-Api -Method "GET" -Path "/health"
    $healthBeforeLaunch = ($health.status -eq "ok")
  }
  catch {
    $healthBeforeLaunch = $false
  }

  if (-not $healthBeforeLaunch) {
    if (-not (Test-Path $exePath)) {
      throw "Launcher EXE was not found: $exePath"
    }

    $launcher = Start-Process `
      -FilePath $exePath `
      -ArgumentList @("--host", "127.0.0.1", "--port", "$Port", "--no-browser") `
      -PassThru `
      -RedirectStandardOutput $launcherOutLog `
      -RedirectStandardError $launcherErrLog

    $launcherStarted = $true
    $launcherPid = $launcher.Id

    if (-not (Wait-ApiHealth -MaxAttempts 60)) {
      throw "API health check did not become ready on $baseUrl"
    }

    $healthAfterLaunch = $true
  }
  else {
    $healthAfterLaunch = $true
  }

  $autoconnectPayload = @{
    process_name = $ProcessName
    poll_ms = $PollMs
    require_admin = $true
    dataset_version = $DatasetVersion
    dataset_autorefresh = $true
  } | ConvertTo-Json -Depth 8

  try {
    $autoconnectResponse = Invoke-Api -Method "POST" -Path "/api/v1/live/autoconnect" -Body $autoconnectPayload
  }
  catch {
    $autoconnectError = $_.Exception.Message
  }

  for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Milliseconds $PollMs
    $attempt = [ordered]@{
      attempt = $i + 1
      timestamp_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
    }

    try {
      $status = Invoke-Api -Method "GET" -Path "/api/v1/live/status"
      $attempt["status"] = $status

      if (
        ($status.mode -eq "memory") -and
        ([bool]$status.memory_connected) -and
        ($status.reason -eq "ok")
      ) {
        $precheckPass = $true
      }
    }
    catch {
      $attempt["error"] = $_.Exception.Message
    }

    $statusChecks += [pscustomobject]$attempt
    if ($precheckPass) {
      break
    }
  }

  $lastStatus = $null
  if ($statusChecks.Count -gt 0) {
    $lastStatus = $statusChecks[$statusChecks.Count - 1]
  }

  $precheck = [ordered]@{
    checked_at_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
    precheck_pass = $precheckPass
    required = [ordered]@{
      mode = "memory"
      memory_connected = $true
      reason = "ok"
      process_name = $ProcessName
      poll_ms = $PollMs
      require_admin = $true
      dataset_version = $DatasetVersion
    }
    process_check_path = $processCheckPath
    launcher = [ordered]@{
      health_before_launch = $healthBeforeLaunch
      health_after_launch = $healthAfterLaunch
      started = $launcherStarted
      pid = $launcherPid
      out_log = $launcherOutLog
      err_log = $launcherErrLog
      exe_path = $exePath
    }
    autoconnect_response = $autoconnectResponse
    autoconnect_error = $autoconnectError
    status_checks = $statusChecks
    last_status = $lastStatus
  }

  $precheck | ConvertTo-Json -Depth 10 | Set-Content -Path $precheckPath -Encoding UTF8

  if ($precheckPass) {
    Write-Host "PRECHECK_OK"
    Get-Content -Path $precheckPath
    exit 0
  }

  $diagConnectResponse = $null
  $diagConnectError = ""
  $diagStatus = $null
  $diagStatusError = ""
  $diagRunState = $null
  $diagRunStateError = ""

  try {
    $diagConnectResponse = Invoke-Api -Method "POST" -Path "/api/v1/live/autoconnect" -Body $autoconnectPayload
  }
  catch {
    $diagConnectError = $_.Exception.Message
  }

  try {
    $diagStatus = Invoke-Api -Method "GET" -Path "/api/v1/live/status"
  }
  catch {
    $diagStatusError = $_.Exception.Message
  }

  try {
    $diagRunState = Invoke-Api -Method "GET" -Path "/api/v1/run/state"
  }
  catch {
    $diagRunStateError = $_.Exception.Message
  }

  $diagnostic = [ordered]@{
    checked_at_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
    diagnostic_attempt = "single_targeted_connect_plus_status_dump"
    connect_response = $diagConnectResponse
    connect_error = $diagConnectError
    live_status = $diagStatus
    live_status_error = $diagStatusError
    run_state = $diagRunState
    run_state_error = $diagRunStateError
  }

  $diagnostic | ConvertTo-Json -Depth 10 | Set-Content -Path $diagnosticPath -Encoding UTF8

  Write-Host "BLOCKER: memory-mode precheck degraded"
  Write-Host "PRECHECK_JSON:"
  Get-Content -Path $precheckPath
  Write-Host "DIAGNOSTIC_JSON:"
  Get-Content -Path $diagnosticPath
  exit 20
}
catch {
  $fatal = [ordered]@{
    checked_at_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
    precheck_pass = $false
    blocker = "precheck_exception"
    error = $_.Exception.Message
  }

  $fatal | ConvertTo-Json -Depth 8 | Set-Content -Path $precheckPath -Encoding UTF8
  Write-Host "BLOCKER: precheck exception"
  Get-Content -Path $precheckPath
  exit 30
}
