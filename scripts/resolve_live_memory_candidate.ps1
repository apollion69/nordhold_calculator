param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$CalibrationCandidatesPath,
  [string]$ProcessName = "NordHold.exe",
  [int]$PollMs = 1000,
  [bool]$RequireAdmin = $false,
  [string]$DatasetVersion = "1.0.0",
  [string]$SignatureProfileId = "",
  [string]$ReplaySessionId = "",
  [int]$RequiredConsecutiveMemoryWindows = 5,
  [int]$MaxPollsPerCandidate = 60,
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

if (-not $CalibrationCandidatesPath) {
  throw "CalibrationCandidatesPath is required."
}
if ($RequiredConsecutiveMemoryWindows -lt 1 -or $MaxPollsPerCandidate -lt 1) {
  throw "RequiredConsecutiveMemoryWindows and MaxPollsPerCandidate must be positive."
}

function Invoke-LiveApi {
  param(
    [string]$Method,
    [string]$Uri,
    [string]$Body = ""
  )

  $url = "$BaseUrl$Uri"
  if ($Method -eq "GET") {
    return Invoke-RestMethod -Method Get -Uri $url -TimeoutSec 5
  }
  if ($Method -eq "POST") {
    return Invoke-RestMethod -Method Post -Uri $url -ContentType "application/json" -Body $Body -TimeoutSec 10
  }
  throw "Unsupported method $Method for $url"
}

function Test-Candidate {
  param(
    [string]$CandidateId
  )

  $result = [ordered]@{
    candidate_id = $CandidateId
    status = "not_run"
    transient_failures = 0
    connect_failures_total_last = 0
    connect_transient_failure_count = 0
    connect_retry_success_total = 0
    snapshot_failure_streak_max = 0
    snapshot_failures_total_last = 0
    stable_windows = 0
    snapshot_ok_windows = 0
    attempts = 0
    last_mode = ""
    last_reason = ""
    last_memory_connected = $false
    last_error = ""
    last_error_stage = ""
    last_error_type = ""
    last_error_message = ""
    last_memory_values = @{}
  }

  try {
    $connectPayload = @{
      process_name = $ProcessName
      poll_ms = $PollMs
      require_admin = $RequireAdmin
      dataset_version = $DatasetVersion
      signature_profile_id = $SignatureProfileId
      calibration_candidates_path = $CalibrationCandidatesPath
      calibration_candidate_id = $CandidateId
      replay_session_id = $ReplaySessionId
    } | ConvertTo-Json
    $connect = Invoke-LiveApi -Method "POST" -Uri "/api/v1/live/connect" -Body $connectPayload
  }
  catch {
    $result.status = "connect_error"
    $result.last_error = $_.Exception.Message
    return $result
  }

  $result.status = [string]$connect.mode
  $consecutive = 0
  for ($i = 0; $i -lt $MaxPollsPerCandidate; $i++) {
    try {
      $status = Invoke-LiveApi -Method "GET" -Uri "/api/v1/live/status"
    }
    catch {
      $result.last_error = $_.Exception.Message
      continue
    }

    $result.attempts++
    $result.last_mode = [string]$status.mode
    $result.last_reason = [string]$status.reason
    $result.last_memory_connected = [bool]$status.memory_connected
    $result.last_memory_values = $status.last_memory_values
    if ($status.snapshot_failure_streak -ne $null) {
      $streak = [int]$status.snapshot_failure_streak
      if ($streak -gt $result.snapshot_failure_streak_max) {
        $result.snapshot_failure_streak_max = $streak
      }
    }
    if ($status.snapshot_failures_total -ne $null) {
      $result.snapshot_failures_total_last = [int]$status.snapshot_failures_total
    }
    if ($status.connect_failures_total -ne $null) {
      $result.connect_failures_total_last = [int]$status.connect_failures_total
    }
    if ($status.connect_transient_failure_count -ne $null) {
      $result.connect_transient_failure_count = [int]$status.connect_transient_failure_count
    }
    if ($status.connect_retry_success_total -ne $null) {
      $result.connect_retry_success_total = [int]$status.connect_retry_success_total
    }
    if ($status.last_error -ne $null) {
      $result.last_error_stage = [string]$status.last_error.stage
      $result.last_error_type = [string]$status.last_error.type
      $result.last_error_message = [string]$status.last_error.message
    }

    if ($status.mode -eq "memory" -and $status.reason -eq "ok" -and $status.memory_connected) {
      $result.snapshot_ok_windows++
      $consecutive++
      if ($consecutive -ge $RequiredConsecutiveMemoryWindows) {
        $result.status = "memory_stable"
        break
      }
    }
    else {
      if ($status.reason -like "memory_snapshot_transient:*") {
        $result.transient_failures++
      }
      $consecutive = 0
    }

    Start-Sleep -Milliseconds $PollMs
  }

  $result.stable_windows = [int]$consecutive
  if ($result.status -ne "memory_stable") {
    $result.status = "unstable"
  }
  return $result
}

$pathQuery = [uri]::EscapeDataString($CalibrationCandidatesPath)
$candidatesPayload = Invoke-LiveApi -Method "GET" -Uri "/api/v1/live/calibration/candidates?path=$pathQuery"
$candidateIds = @()
if ($candidatesPayload -ne $null -and $candidatesPayload.candidate_ids) {
  $candidateIds = @($candidatesPayload.candidate_ids)
}
if (-not $candidateIds -and $candidatesPayload.candidates) {
  $candidateIds = @($candidatesPayload.candidates | ForEach-Object { [string]($_.id) })
}
if (-not $candidateIds) {
  throw "No calibration candidates available at path: $CalibrationCandidatesPath"
}

$results = @()
foreach ($candidateId in $candidateIds) {
  $results += Test-Candidate -CandidateId $candidateId
}

$stable = $results | Where-Object { $_.status -eq "memory_stable" } | Sort-Object @{Expression = { $_.connect_failures_total_last }; Ascending = $true }, @{Expression = { $_.snapshot_failure_streak_max }; Ascending = $true }, @{Expression = { $_.snapshot_failures_total_last }; Ascending = $true }
$best = if ($stable.Count -gt 0) { $stable[0] } else { $null }
$failureByStage = @{}
$failureByType = @{}
foreach ($item in $results) {
  $stage = [string]$item.last_error_stage
  if ($stage) {
    if (-not $failureByStage.ContainsKey($stage)) {
      $failureByStage[$stage] = 0
    }
    $failureByStage[$stage]++
  }

  $errorType = [string]$item.last_error_type
  if ($errorType) {
    if (-not $failureByType.ContainsKey($errorType)) {
      $failureByType[$errorType] = 0
    }
    $failureByType[$errorType]++
  }
}

$summary = [ordered]@{
  base_url = $BaseUrl
  dataset_version = $DatasetVersion
  process_name = $ProcessName
  require_admin = $RequireAdmin
  poll_ms = $PollMs
  calibration_candidates_path = $CalibrationCandidatesPath
  required_consecutive_memory_windows = $RequiredConsecutiveMemoryWindows
  max_polls_per_candidate = $MaxPollsPerCandidate
  candidate_ids = $candidateIds
  candidates = $results
  best_candidate_id = if ($best) { [string]$best.candidate_id } else { "" }
  best_connect_failures_total_last = if ($best) { [int]$best.connect_failures_total_last } else { 0 }
  best_snapshot_failure_streak_max = if ($best) { [int]$best.snapshot_failure_streak_max } else { 0 }
  best_snapshot_failures_total_last = if ($best) { [int]$best.snapshot_failures_total_last } else { 0 }
  best_last_reason = if ($best) { [string]$best.last_reason } else { "" }
  failure_taxonomy = [ordered]@{
    by_stage = $failureByStage
    by_type = $failureByType
  }
}

if ($OutputPath) {
  Set-Content -Path $OutputPath -Value ($summary | ConvertTo-Json -Depth 12) -Encoding UTF8
}

if ($best) {
  $summary
}
else {
  throw "No stable candidate found for path=$CalibrationCandidatesPath"
}
