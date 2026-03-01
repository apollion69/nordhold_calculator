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
  [int]$CandidateTtlHours = 24,
  [int]$TransientProbePolls = 3,
  [string]$CandidateBuild = "",
  [string]$CandidateDatasetVersion = "",
  [switch]$AllowStaleCandidates,
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$CandidateScanEpochUtc = (Get-Date).ToUniversalTime().ToString("s") + "Z"

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

function Test-Transient299Reason {
  param([string]$Reason)
  if (-not $Reason) {
    return $false
  }
  return ($Reason -match "winerr=299") -or ($Reason -match "transient_299")
}

function Get-CandidateMetadata {
  param(
    [string]$Path,
    [int]$CandidateTtlHours
  )

  $item = Get-Item -Path $Path
  $result = [ordered]@{
    path = [string]$item.FullName
    file_age_sec = [int]([Math]::Round((Get-Date).ToUniversalTime().Subtract($item.LastWriteTimeUtc).TotalSeconds))
    payload_age_sec = 0
    stale_reasons = @()
    build_id = ""
    dataset_version = ""
    generated_at_utc = ""
    candidate_scan_epoch = $CandidateScanEpochUtc
    artifact_hash = ""
  }

  try {
    $rawPayload = Get-Content -Path $Path -Raw -Encoding UTF8
    $payload = ConvertFrom-Json -InputObject $rawPayload
  }
  catch {
    throw "Unable to read calibration payload '$Path': $($_.Exception.Message)"
  }

  if (-not ($payload -is [psobject])) {
    throw "Calibration payload '$Path' is not valid JSON object."
  }

  if ($payload.generated_at_utc) {
    $result.generated_at_utc = [string]$payload.generated_at_utc
    try {
      $generatedAt = [DateTime]::Parse($payload.generated_at_utc, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AssumeUniversal)
      $result.payload_age_sec = [int]([Math]::Round((Get-Date).ToUniversalTime().Subtract($generatedAt.ToUniversalTime()).TotalSeconds))
      if ($result.payload_age_sec -lt 0) { $result.payload_age_sec = 0 }
    }
    catch {
      $result.payload_age_sec = 0
    }
  }

  try {
    $result.artifact_hash = [string](Get-FileHash -Path $Path -Algorithm SHA256).Hash
  }
  catch {
    $result.artifact_hash = ""
  }

  if ($payload.build_id) {
    $result.build_id = [string]$payload.build_id
  }
  elseif ($payload.game_build) {
    $result.build_id = [string]$payload.game_build
  }

  if ($payload.dataset_version) {
    $result.dataset_version = [string]$payload.dataset_version
  }

  $maxAgeSec = [Math]::Max(0, $CandidateTtlHours * 3600)
  if ($maxAgeSec -gt 0) {
    if ($result.file_age_sec -gt $maxAgeSec) {
      $result.stale_reasons += "file_age_ttl_exceeded"
    }
    if ($result.payload_age_sec -gt 0 -and $result.payload_age_sec -gt $maxAgeSec) {
      $result.stale_reasons += "payload_age_ttl_exceeded"
    }
  }

  if ($CandidateBuild -and $result.build_id -and $CandidateBuild -ne $result.build_id) {
    $result.stale_reasons += "build_id_mismatch(payload=$($result.build_id),expected=$CandidateBuild)"
  }
  if ($CandidateDatasetVersion -and $result.dataset_version -and $CandidateDatasetVersion -ne $result.dataset_version) {
    $result.stale_reasons += "dataset_version_mismatch(payload=$($result.dataset_version),expected=$CandidateDatasetVersion)"
  }

  return $result
}

function Test-Candidate {
  param(
    [string]$CandidateId,
    [int]$TransientProbePolls = 3
  )

  $result = [ordered]@{
    candidate_id = $CandidateId
    status = "not_run"
    transient_failures = 0
    first_attempt_reason = ""
    first_attempt_mode = ""
    first_attempt_transient_299 = $false
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
  $effectiveMaxPolls = $MaxPollsPerCandidate
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
    if ($result.attempts -eq 1) {
      $result.first_attempt_mode = [string]$status.mode
      $result.first_attempt_reason = [string]$status.reason
      $result.first_attempt_transient_299 = Test-Transient299Reason -Reason $result.first_attempt_reason
      if ($status.last_error -ne $null -and $status.last_error -ne "") {
        $statusReason = [string]$status.last_error.message
        if (-not $result.first_attempt_transient_299) {
          $result.first_attempt_transient_299 = Test-Transient299Reason -Reason $statusReason
        }
      }
    }
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
      if ($result.attempts -eq 1 -and $result.first_attempt_transient_299) {
        $effectiveMaxPolls = [Math]::Min($MaxPollsPerCandidate, [Math]::Max(1, $TransientProbePolls))
      }
      if ($status.reason -like "memory_snapshot_transient:*" -or (Test-Transient299Reason -Reason $status.reason)) {
        $result.transient_failures++
      }
      $consecutive = 0
    }
    if ($result.attempts -ge $effectiveMaxPolls) {
      break
    }

    Start-Sleep -Milliseconds $PollMs
  }

  $result.stable_windows = [int]$consecutive
  if ($result.status -ne "memory_stable") {
    $result.status = "unstable"
  }
  return $result
}

$candidatePath = (Resolve-Path -Path $CalibrationCandidatesPath -ErrorAction SilentlyContinue).Path
if (-not $candidatePath) {
  throw "Calibration candidate file not found: $CalibrationCandidatesPath"
}

$candidateMetadata = Get-CandidateMetadata -Path $candidatePath -CandidateTtlHours $CandidateTtlHours

try {
  $datasetPayload = Invoke-LiveApi -Method "GET" -Uri "/api/v1/dataset/version"
  if ($candidateMetadata.dataset_version -ne "") {
    if ($datasetPayload.dataset_version -and $CandidateDatasetVersion) {
      if ($CandidateDatasetVersion -ne $candidateMetadata.dataset_version) {
        $candidateMetadata.stale_reasons += "dataset_version_metadata_mismatch(payload=$($candidateMetadata.dataset_version),requested=$CandidateDatasetVersion)"
      }
    }
    if ($datasetPayload.dataset_version -and ($DatasetVersion -ne "")) {
      if ($DatasetVersion -ne $candidateMetadata.dataset_version) {
        $candidateMetadata.stale_reasons += "dataset_version_mismatch(payload=$($candidateMetadata.dataset_version),requested=$DatasetVersion)"
      }
    }
  }
  if ($candidateMetadata.build_id -ne "" -and $datasetPayload.build_id -and $CandidateBuild -eq "") {
    $CandidateBuild = [string]$datasetPayload.build_id
  }
}
catch {
  # fallback: keep metadata checks from payload only
}

$precheckStale = $false
if ($candidateMetadata.stale_reasons.Count -gt 0 -and -not $AllowStaleCandidates) {
  $precheckStale = $true
}
$candidateSetStale = $false
$candidateSetStaleReason = ""
$failedCandidatesCount = 0
$transient299Count = 0

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
$transient299Clustered = $false

if ($precheckStale) {
  $candidateSetStale = $true
  $candidateSetStaleReason = "artifact_stale:" + ($candidateMetadata.stale_reasons -join ', ')
  $failedCandidatesCount = $candidateIds.Count
  $transient299Count = 0
} else {
  foreach ($candidateId in $candidateIds) {
    $results += Test-Candidate -CandidateId $candidateId -TransientProbePolls $TransientProbePolls
  }
}

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

$stable = $results | Where-Object { $_.status -eq "memory_stable" } | Sort-Object @{Expression = { $_.connect_failures_total_last }; Ascending = $true }, @{Expression = { $_.snapshot_failure_streak_max }; Ascending = $true }, @{Expression = { $_.snapshot_failures_total_last }; Ascending = $true }
$best = if ($stable.Count -gt 0) { $stable[0] } else { $null }

if (-not $precheckStale) {
  $failedCandidatesCount = 0
  $transient299Count = 0
  foreach ($item in $results) {
    if ($item.status -ne "memory_stable") {
      $failedCandidatesCount++
    }
    if ([bool]$item.first_attempt_transient_299) {
      $transient299Count++
    }
  }
}

if (-not $candidateSetStale -and $results.Count -gt 0 -and $transient299Count -eq $results.Count) {
  $candidateSetStale = $true
  $candidateSetStaleReason = "all_candidates_first_attempt_transient_299"
  $transient299Clustered = $true
}

$winerr299Rate = 0.0
if ($results.Count -gt 0) {
  $winerr299Rate = [Math]::Round($transient299Count / [double]$results.Count, 4)
}

$winnerCandidateId = ""
if ($best) {
  $winnerCandidateId = [string]$best.candidate_id
}

$winnerCandidateAgeSec = 0
if ($winnerCandidateId) {
  $winnerCandidateAgeSec = [int]$candidateMetadata.file_age_sec
  if ($best.generated_at_utc) {
    try {
      $winnerGeneratedAt = [DateTime]::Parse($best.generated_at_utc, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AssumeUniversal)
      $winnerCandidateAgeSec = [int]([Math]::Round((Get-Date).ToUniversalTime().Subtract($winnerGeneratedAt.ToUniversalTime()).TotalSeconds))
      if ($winnerCandidateAgeSec -lt 0) {
        $winnerCandidateAgeSec = 0
      }
    }
    catch {
      # keep file age fallback
    }
  }
}

$noStableCandidate = $false
if ($candidatesPayload.recommended_candidate_support -and $candidatesPayload.recommended_candidate_support.no_stable_candidate) {
  $noStableCandidate = [bool]$candidatesPayload.recommended_candidate_support.no_stable_candidate
}
$overallNoStableCandidate = $noStableCandidate -or -not $best
$overallNoStableCandidate = [bool]($overallNoStableCandidate -or $candidateSetStale)

$summary = [ordered]@{
  ok = [bool]$best
  base_url = $BaseUrl
  dataset_version = $DatasetVersion
  process_name = $ProcessName
  require_admin = $RequireAdmin
  poll_ms = $PollMs
  calibration_candidates_path = $candidatePath
  required_consecutive_memory_windows = $RequiredConsecutiveMemoryWindows
  max_polls_per_candidate = $MaxPollsPerCandidate
  candidate_ids = $candidateIds
  candidates = $results
  best_candidate_id = $winnerCandidateId
  best_connect_failures_total_last = if ($best) { [int]$best.connect_failures_total_last } else { 0 }
  best_snapshot_failure_streak_max = if ($best) { [int]$best.snapshot_failure_streak_max } else { 0 }
  best_snapshot_failures_total_last = if ($best) { [int]$best.snapshot_failures_total_last } else { 0 }
  best_last_reason = if ($best) { [string]$best.last_reason } else { "" }
  failure_taxonomy = [ordered]@{
    by_stage = $failureByStage
    by_type = $failureByType
  }
  candidate_set_stale = [bool]$candidateSetStale
  candidate_set_stale_reason = [string]$candidateSetStaleReason
  candidate_stale_reason = [string]$candidateSetStaleReason
  transient_299_clustered = [bool]$transient299Clustered
  candidate_scan_epoch = [string]$candidateMetadata.candidate_scan_epoch
  source_artifact_path = [string]$candidateMetadata.path
  artifact_hash = [string]$candidateMetadata.artifact_hash
  failed_candidates_count = [int]$failedCandidatesCount
  winner_candidate_id = $winnerCandidateId
  winner_candidate_age_sec = [int]$winnerCandidateAgeSec
  winerr299_rate = [double]$winerr299Rate
  no_stable_candidate = [bool]$overallNoStableCandidate
  candidate_file_stale = [bool]($candidateMetadata.stale_reasons.Count -gt 0)
  candidate_file_stale_reasons = @($candidateMetadata.stale_reasons)
  candidate_file_age_sec = [int]$candidateMetadata.file_age_sec
  candidate_payload_age_sec = [int]$candidateMetadata.payload_age_sec
  candidate_file_generated_at_utc = [string]$candidateMetadata.generated_at_utc
  candidate_file_build_id = [string]$candidateMetadata.build_id
  candidate_file_dataset_version = [string]$candidateMetadata.dataset_version
}

if ($OutputPath) {
  Set-Content -Path $OutputPath -Value ($summary | ConvertTo-Json -Depth 12) -Encoding UTF8
}

$summary
if (-not $best) {
  exit 2
}
