param(
  [int]$DurationS = 1800,
  [int]$Port = 8013,
  [int]$PollMs = 1000,
  [string]$ProcessName = "NordHold.exe",
  [bool]$RequireAdmin = $false,
  [bool]$AutoElevateForAdmin = $true,
  [bool]$HideLauncherWindow = $true,
[string]$DatasetVersion = "1.0.0",
[string]$CalibrationCandidatesPath = "",
[string]$PythonPath = "",
[bool]$RefreshCandidates = $true,
  [bool]$AllowStaleCandidates = $false,
  [int]$CandidateTtlHours = 24,
  [int]$AutoconnectFailFastS = 30,
  [int]$CandidateProbeDurationS = 120,
  [int]$AutoconnectRequestTimeoutS = 60,
  [int]$ProbeTimeoutPaddingS = 20,
  [int]$Transient299FailFastCycles = 3,
  [switch]$NoAutoconnect,
  [bool]$ForcePythonBackend = $false,
  [switch]$KeepLauncherRunning
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$exePath = Join-Path $projectRoot "runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe"
$launcherMode = if ($ForcePythonBackend) { "python" } else { "dist" }
$launcherStartMode = ""

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

function Convert-NonNegativeInt {
  param(
    [object]$Value,
    [long]$Default = 0
  )

  if ($null -eq $Value) {
    return $Default
  }
  try {
    $numeric = [double]$Value
    if ([double]::IsNaN($numeric) -or [double]::IsInfinity($numeric)) {
      return $Default
    }
    if ($numeric -lt 0) {
      return 0
    }
    return [long][Math]::Floor($numeric)
  }
  catch {
    return $Default
  }
}

function Test-Transient299Reason {
  param([string]$Reason)
  if (-not $Reason) {
    return $false
  }
  return ($Reason -match "winerr=299") -or ($Reason -match "memory_read_transient_299_cluster")
}

function Evaluate-AutoconnectAttemptsTransient299 {
  param(
    [object]$Attempts,
    [int]$Threshold = 3
  )

  if (-not $Attempts -or $Attempts.Count -eq 0) {
    return @([bool]$false, [int]0)
  }

  if ($Threshold -lt 1) {
    $Threshold = 1
  }

  $totalAttempts = 0
  $transientCount = 0
  $hasMemorySuccess = $false

  foreach ($attempt in $Attempts) {
    if (-not $attempt) {
      continue
    }
    $totalAttempts++
    $mode = [string]$attempt.mode
    if ($mode -eq "memory") {
      $hasMemorySuccess = $true
      break
    }
    $reason = [string]$attempt.reason
    if (Test-Transient299Reason -Reason $reason) {
      $transientCount++
    }
  }

  if ($totalAttempts -ge $Threshold -and -not $hasMemorySuccess -and $transientCount -eq $totalAttempts) {
    return @($true, [int]$totalAttempts)
  }
  return @($false, [int]$totalAttempts)
}

function Find-LatestCalibrationCandidatesFile {
  param(
    [string]$Pattern = "memory_calibration_candidates*.json",
    [string]$RootPath = "",
    [bool]$RequireRefreshReady = $false,
    [bool]$PreferNonAutoload = $false
  )

  $searchRoots = @()
  if ($RootPath) {
    $searchRoots += $RootPath
    $worklogsRoot = Join-Path $RootPath "worklogs"
    $runtimeLogsRoot = Join-Path $RootPath "runtime\logs"
  }
  else {
    $searchRoots += $projectRoot
    $worklogsRoot = Join-Path $projectRoot "worklogs"
    $runtimeLogsRoot = Join-Path $projectRoot "runtime\logs"
  }
  if (Test-Path $worklogsRoot) {
    $searchRoots += $worklogsRoot
  }
  if (Test-Path $runtimeLogsRoot) {
    $searchRoots += $runtimeLogsRoot
  }

  $searchRoots = @($searchRoots | Select-Object -Unique)
  $candidates = @()
  foreach ($root in $searchRoots) {
    $found = Get-ChildItem -Path $root -Recurse -Filter $Pattern -File -ErrorAction SilentlyContinue
    if ($found) {
      $candidates += $found
    }
  }
  if (-not $candidates) {
    return ""
  }
  if ($PreferNonAutoload) {
    $filteredCandidates = @()
    foreach ($candidate in $candidates) {
      if (-not (Test-AutoloadCalibrationCandidatesFile -Path $candidate.FullName)) {
        $filteredCandidates += $candidate
      }
    }
    if ($filteredCandidates.Count -gt 0) {
      $candidates = $filteredCandidates
    }
  }
  $refreshCandidates = @()
  $legacyCandidates = @()
  foreach ($candidate in $candidates) {
    $readiness = Get-CandidateRefreshReadiness -Path $candidate.FullName
    if ($readiness.ready) {
      $refreshCandidates += $candidate
    }
    else {
      $legacyCandidates += $candidate
    }
  }
  if ($refreshCandidates.Count -gt 0) {
    $sorted = $refreshCandidates
  }
  elseif ($RequireRefreshReady) {
    return ""
  }
  else {
    $sorted = $legacyCandidates
  }
  if (-not $sorted) {
    return ""
  }
  $sorted = $sorted | Sort-Object LastWriteTimeUtc -Descending
  return [string]$sorted[0].FullName
}

function Convert-ToWindowsPath {
  param(
    [string]$Path
  )

  if (-not $Path) {
    return ""
  }
  $normalized = Normalize-PythonCandidatePath -Path $Path
  if (-not $normalized) {
    return ""
  }
  return $normalized
}

function Normalize-PythonCandidatePath {
  param(
    [string]$Path
  )

  if (-not $Path) {
    return ""
  }
  $normalized = $Path.Trim().Trim('"').Trim("'")
  $normalized = $normalized -replace "/", "\"
  $normalized = $normalized -replace "\\{2,}", "\"
  if ($normalized -match '^[\\/]{2,}[uU][sS][r][\\/]bin[\\/]') {
    return ""
  }
  if ($normalized -match '^\\"' -or $normalized -match "^'") {
    $normalized = $normalized.TrimStart("\", """", "'").TrimEnd("\", """", "'")
  }
  if ($normalized -match '^/mnt/([a-zA-Z])/(.+)$') {
    $drive = $matches[1].ToUpper()
    $rest = $matches[2] -replace '/', '\'
    return "${drive}:$($rest)"
  }
  if ($normalized -match '^[\\\\/][uU][sS][r][\\\\/]bin[\\\\/]') {
    return ""
  }
  if ($normalized -match '^/usr/bin[\\/]' -or $normalized -match '^/bin[/\\]') {
    return ""
  }
  return $normalized
}

function Is-WindowsPythonPathCandidate {
  param(
    [string]$Path
  )

  if (-not $Path) {
    return $false
  }
  $candidate = Normalize-PythonCandidatePath -Path $Path
  if (-not $candidate) {
    return $false
  }
  if ($candidate -match '^/usr/bin[\\/]' -or $candidate -match '^/bin[\\/]') {
    return $false
  }
  if ($candidate -match '^[\\/][uU][sS][r][\\/]bin[\\/]') {
    return $false
  }
  return $true
}

function Test-AutoloadCalibrationCandidatesFile {
  param(
    [string]$Path
  )

  if (-not $Path) {
    return $false
  }
  $fileName = [IO.Path]::GetFileName($Path).ToLowerInvariant()
  return $fileName -match "^memory_calibration_candidates.*autoload.*\\.json$"
}

function Convert-PythonArgument {
  param(
    [string]$Argument
  )

  if ([string]::IsNullOrWhiteSpace($Argument)) {
    return '""'
  }
  if ($Argument -match '[\\s"]') {
    $escaped = $Argument -replace '"', '\"'
    return '"' + $escaped + '"'
  }
  return $Argument
}

function Invoke-PythonProcess {
  param(
    [string]$PythonPath,
    [string[]]$Arguments = @(),
    [string]$StdoutPath = "",
    [string]$StderrPath = "",
    [int]$TimeoutMs = 120000
  )

  $argumentTokens = @()
  foreach ($argument in $Arguments) {
    if ($null -ne $argument) {
      $argumentTokens += Convert-PythonArgument -Argument ([string]$argument)
    }
  }

  $info = New-Object System.Diagnostics.ProcessStartInfo
  $info.FileName = $PythonPath
  $info.Arguments = [string]::Join(" ", $argumentTokens)
  $info.UseShellExecute = $false
  $info.RedirectStandardOutput = $true
  $info.RedirectStandardError = $true
  $info.CreateNoWindow = $true

  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $info

  try {
    $null = $process.Start()
  }
  catch {
    throw "helper_process_start_failed: python=$PythonPath args=$([string]::Join(' ', $Arguments)) $($_.Exception.Message)"
  }

  $timedOut = $false
  if (-not $process.WaitForExit([Math]::Max(1, $TimeoutMs))) {
    try {
      $timedOut = $true
      $process.Kill()
    }
    catch {
    }
    throw "Python helper timed out after $($TimeoutMs)ms: $PythonPath $([string]::Join(' ', $Arguments))"
  }

  $stdoutText = ""
  $stderrText = ""
  try {
    $stdoutText = [string]$process.StandardOutput.ReadToEnd()
  }
  catch {
    $stdoutText = ""
  }
  try {
    $stderrText = [string]$process.StandardError.ReadToEnd()
  }
  catch {
    $stderrText = ""
  }

  if ($StdoutPath) {
    Set-Content -Path $StdoutPath -Value $stdoutText -Encoding UTF8
  }
  if ($StderrPath) {
    Set-Content -Path $StderrPath -Value $stderrText -Encoding UTF8
  }

  return @{
    exit_code = [int]$process.ExitCode
    timed_out = [bool]$timedOut
    arguments = $Arguments
    stdout = $stdoutText
    stderr = $stderrText
    raw_command_line = "$PythonPath $($argumentTokens -join ' ')"
  }
}

function Probe-PythonExecutable {
  param(
    [string]$PythonPath,
    [string[]]$PythonArgs = @(),
    [bool]$RequireUvicorn = $false
  )

  $probeArgs = @()
  if ($PythonArgs) {
    $probeArgs += $PythonArgs
  }
  if ($RequireUvicorn) {
    $probeCommand = "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('uvicorn') else 1)"
  }
  else {
    $probeCommand = "print(1)"
  }
  $probeArgs += "-c"
  $probeArgs += $probeCommand

  $probeStdOut = [IO.Path]::GetTempFileName()
  $probeStdErr = [IO.Path]::GetTempFileName()
  try {
    $probeResult = Invoke-PythonProcess -PythonPath $PythonPath -Arguments $probeArgs -StdoutPath $probeStdOut -StderrPath $probeStdErr -TimeoutMs 5000
  }
  catch {
    return @{
      ok = $false
      error = $_.Exception.Message
      arguments = $probeArgs
      stdout = ""
      stderr = ""
    }
  }

  if ($probeResult.timed_out) {
    return @{
      ok = $false
      error = "python probe timed out after 5000ms"
      arguments = $probeArgs
      stdout = [string]$probeResult.stdout
      stderr = [string]$probeResult.stderr
    }
  }
  if ($probeResult.exit_code -ne 0) {
    return @{
      ok = $false
      error = "python probe failed with exit=$($probeResult.exit_code)"
      arguments = $probeArgs
      stdout = [string]$probeResult.stdout
      stderr = [string]$probeResult.stderr
    }
  }
  return @{
    ok = $true
    arguments = $probeArgs
    stdout = [string]$probeResult.stdout
    stderr = [string]$probeResult.stderr
  }
  finally {
    Remove-Item -Path $probeStdOut -ErrorAction SilentlyContinue
    Remove-Item -Path $probeStdErr -ErrorAction SilentlyContinue
  }
}

function Resolve-PythonExecutable {
  param(
    [string]$PreferredPath = "",
    [string]$ProjectRoot = "",
    [bool]$RequireUvicorn = $false
  )

  $candidates = @()
  $resolutionDiagnostics = @()

  if ($PreferredPath) {
    $preferred = New-PythonCandidateEntry -Path $PreferredPath -Source "preferred"
    if ($preferred) {
      $candidates += $preferred
    }
    else {
      $resolutionDiagnostics += "invalid_preferred:$PreferredPath"
    }
  }

  $projectCandidates = @(
    (New-PythonCandidateEntry -Path (Join-Path $ProjectRoot ".venv-win311\Scripts\python.exe") -Source "project_venv_win311_pythonexe"),
    (New-PythonCandidateEntry -Path (Join-Path $ProjectRoot ".venv-win311\Scripts\python3.exe") -Source "project_venv_win311_python3exe"),
    (New-PythonCandidateEntry -Path (Join-Path $ProjectRoot ".venv\Scripts\python.exe") -Source "project_venv_pythonexe"),
    (New-PythonCandidateEntry -Path (Join-Path $ProjectRoot ".venv\Scripts\python3.exe") -Source "project_venv_python3exe"),
    (New-PythonCandidateEntry -Path (Join-Path $ProjectRoot "venv\Scripts\python.exe") -Source "project_venv_py")
  )
  foreach ($entry in $projectCandidates) {
    if ($entry) {
      $candidates += $entry
    }
  }

  $installedPatterns = @(
    (Join-Path ${env:LOCALAPPDATA} "Programs\Python\Python*\python.exe"),
    "C:\Users\admin\AppData\Local\Programs\Python\Python*\python.exe",
    "C:\Python*\python.exe",
    (Join-Path ${env:ProgramFiles} "Python*\python.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Python*\python.exe")
  )
  foreach ($pattern in $installedPatterns) {
    foreach ($entry in (Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue)) {
      $candidate = New-PythonCandidateEntry -Path $entry.FullName -Source "installed_python"
      if ($candidate) {
        $candidates += $candidate
      }
    }
  }

  $candidates += New-PythonCandidateEntry -Path "python3" -Source "python3_cmd"
  $candidates += New-PythonCandidateEntry -Path "python" -Source "python_cmd"
  $launcherCandidate = New-PythonCandidateEntry -Path "py" -Source "py_launcher_3" -Args @("-3")
  if ($launcherCandidate) {
    $candidates += $launcherCandidate
  }

  foreach ($candidate in $candidates) {
    if (-not $candidate -or -not $candidate.path) {
      continue
    }

    $candidatePath = $candidate.path
    $candidateArgs = @()
    if ($candidate.args) {
      $candidateArgs = [string[]]$candidate.args
    }

    if (-not (Is-WindowsPythonPathCandidate -Path $candidatePath)) {
      $resolutionDiagnostics += "skip:$($candidate.source):$candidatePath"
      continue
    }

    $resolvedPath = $null
    if (Test-Path $candidatePath) {
      try {
        $resolvedPath = [string](Resolve-Path -Path $candidatePath).Path
      }
      catch {
        $resolutionDiagnostics += "resolve-path-failed:$($candidate.source):$($candidatePath):$($_.Exception.Message)"
      }
    }
    else {
      $command = Get-Command $candidatePath -ErrorAction SilentlyContinue
      if ($command -and $command.Path) {
        $resolvedPath = Convert-ToWindowsPath -Path ([string]$command.Path)
      }
    }

    if (-not $resolvedPath -or -not (Test-Path $resolvedPath)) {
      $resolutionDiagnostics += "missing:$($candidate.source):$candidatePath"
      continue
    }
    if (-not (Is-WindowsPythonPathCandidate -Path $resolvedPath)) {
      $resolutionDiagnostics += "unsupported:$($candidate.source):$resolvedPath"
      continue
    }

    $probe = Probe-PythonExecutable -PythonPath $resolvedPath -PythonArgs $candidateArgs -RequireUvicorn $RequireUvicorn
    if ($probe.ok) {
      return [ordered]@{
        path = $resolvedPath
        args = $candidateArgs
        source = $candidate.source
        probe_ok = $true
        probe = $probe
        diagnostics = $resolutionDiagnostics
      }
    }
    $resolutionDiagnostics += "probe-failed:$($candidate.source):$($resolvedPath):$($probe.error)"
  }
  if ($resolutionDiagnostics.Count -eq 0) {
    throw "No Python executable found for candidate refresh."
  }
  throw "No Python executable found for candidate refresh. attempts=$($resolutionDiagnostics -join '; ')"
}

function New-PythonCandidateEntry {
  param(
    [string]$Path,
    [string]$Source,
    [string[]]$Args = @()
  )

  $normalized = Normalize-PythonCandidatePath -Path $Path
  if (-not $normalized) {
    return $null
  }
  return @{
    path = $normalized
    args = [string[]]$Args
    source = $Source
  }
}

function Get-CandidateFileAgeSec {
  param(
    [string]$Path
  )

  if (-not $Path -or -not (Test-Path $Path)) {
    return 0
  }
  try {
    $file = Get-Item -Path $Path
    $age = [Math]::Round((Get-Date).ToUniversalTime().Subtract($file.LastWriteTimeUtc).TotalSeconds)
    return [int][Math]::Max(0, $age)
  }
  catch {
    return 0
  }
}

function Get-CandidateMetadataAgeSec {
  param(
    [string]$Path
  )

  if (-not $Path -or -not (Test-Path $Path)) {
    return 0
  }
  try {
    $payload = Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
  }
  catch {
    return Get-CandidateFileAgeSec -Path $Path
  }

  $candidates = @(
    $payload.generated_at_utc,
    $payload.refresh_metadata.generated_at_utc,
    $payload.generated_at,
    $payload.refresh_metadata.generated_at
  )

  $timestamp = $null
  foreach ($candidate in $candidates) {
    if (-not $candidate) {
      continue
    }
    if ([string]::IsNullOrWhiteSpace([string]$candidate)) {
      continue
    }
    try {
      $timestamp = [DateTime]::Parse($candidate, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AssumeUniversal)
      break
    }
    catch {
      continue
    }
  }

  if (-not $timestamp) {
    return Get-CandidateFileAgeSec -Path $Path
  }
  $age = [Math]::Round((Get-Date).ToUniversalTime().Subtract($timestamp.ToUniversalTime()).TotalSeconds)
  return [int][Math]::Max(0, $age)
}

function Get-CandidateRefreshReadiness {
  param(
    [string]$Path
  )

  $result = @{
    path = [string]$Path
    ready = $false
    has_source_snapshot_meta = $false
    missing_required_fields = @()
    parse_error = ""
  }

  if (-not $Path -or -not (Test-Path $Path)) {
    return $result
  }

  try {
    $payload = Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
  }
  catch {
    $result.parse_error = $_.Exception.Message
    return $result
  }

  $requiredFields = @("current_wave", "gold", "essence")
  $sourceMeta = $payload.source_snapshot_meta_paths
  if (-not $sourceMeta) {
    $result.missing_required_fields = $requiredFields
    return $result
  }
  $result.has_source_snapshot_meta = $true

  if (-not ($sourceMeta -is [psobject])) {
    $result.missing_required_fields = $requiredFields
    return $result
  }

  foreach ($field in $requiredFields) {
    $metaValue = $sourceMeta.$field
    if ([string]::IsNullOrWhiteSpace([string]$metaValue)) {
      $result.missing_required_fields += $field
    }
  }

  if ($result.missing_required_fields.Count -eq 0) {
    $result.ready = $true
  }
  return $result
}

function Add-JsonField {
  param(
    [string]$Path,
    [hashtable]$Fields
  )

  if (-not (Test-Path $Path)) {
    return
  }
  try {
    $payload = Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    if ($payload -is [psobject]) {
      foreach ($key in $Fields.Keys) {
        $payload | Add-Member -MemberType NoteProperty -Name $key -Value $Fields[$key] -Force
      }
      $json = $payload | ConvertTo-Json -Depth 20
      $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
      [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
    }
  }
  catch {
    # keep base artifact even if metadata write fails
  }
}

function Invoke-PythonCapture {
  param(
    [string]$PythonPath,
    [string[]]$PythonArguments = @(),
    [string[]]$Arguments,
    [string]$StdoutPath,
    [string]$StderrPath,
    [int]$TimeoutMs = 120000
  )

  $commandLineArgs = @()
  if ($PythonArguments) {
    $commandLineArgs += $PythonArguments
  }
  $commandLineArgs += $Arguments

  try {
    if (-not (Test-Path $PythonPath)) {
      throw "helper_launch_invalid_python_path: python executable missing at '$PythonPath'"
    }
    $processResult = Invoke-PythonProcess -PythonPath $PythonPath -Arguments $commandLineArgs -StdoutPath $StdoutPath -StderrPath $StderrPath -TimeoutMs $TimeoutMs
  }
  catch {
    $message = [string]$_.Exception.Message
    if ($message -like "*helper_process_start_failed*" -or $message -like "*helper_launch_invalid_python_path*" -or $message -like "*No Python executable found*") {
      throw "helper_launch_invalid_python_path: python=$PythonPath reason=$message"
    }
    throw "helper_launch_error: $message"
  }

  if ($processResult.timed_out) {
    $timeoutSec = [Math]::Round($TimeoutMs / 1000, 0)
    throw "Python helper timed out: $($Arguments[0]) after ${timeoutSec}s"
  }
  if ($processResult.exit_code -ne 0) {
    throw "Python helper failed (exit=$($processResult.exit_code)): $($Arguments[0])"
  }
  return @{
    exit_code = [int]$processResult.exit_code
    python_path = $PythonPath
    python_args = $PythonArguments
    arguments = $commandLineArgs
    timed_out = $false
  }
}

function Invoke-SoakCandidatesRefresh {
  param(
    [string]$SourceCandidatePath,
    [string]$RunId,
    [string]$ProjectRoot,
    [string]$ArtifactsDir,
    [string]$ProcessName,
    [string]$DatasetVersion,
    [int]$ProbeDurationS,
    [string]$PythonPath
  )

  if (-not (Test-Path $SourceCandidatePath)) {
    throw "No calibration source candidates available for refresh: $SourceCandidatePath"
  }
  if (-not (Test-Path $ArtifactsDir)) {
    New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
  }
  $probeScript = Join-Path $ProjectRoot "scripts\nordhold_combat_deep_probe.py"
  $promoteScript = Join-Path $ProjectRoot "scripts\nordhold_promote_deep_probe_candidates.py"
  if (-not (Test-Path $probeScript) -or -not (Test-Path $promoteScript)) {
    throw "Refresh helper scripts are missing under $ProjectRoot\scripts."
  }

  $pythonInvocation = Resolve-PythonExecutable -PreferredPath $PythonPath -ProjectRoot $ProjectRoot
  $python = [string]$pythonInvocation.path
  $pythonArguments = @()
  if ($pythonInvocation.args) {
    $pythonArguments = [string[]]$pythonInvocation.args
  }

  $sourceHash = (Get-FileHash -Path $SourceCandidatePath -Algorithm SHA256).Hash
  $probeReport = Join-Path $ArtifactsDir "combat_deep_probe_report.json"
  $optionalMetaDir = Join-Path $ArtifactsDir "auto_optional_meta"
  $probeStdOut = Join-Path $ArtifactsDir "combat_deep_probe.stdout.log"
  $probeStdErr = Join-Path $ArtifactsDir "combat_deep_probe.stderr.log"
  $promoteOut = Join-Path $ArtifactsDir "memory_calibration_candidates_autoload.json"
  $promoteStdOut = Join-Path $ArtifactsDir "promote_deep_probe_candidates.stdout.log"
  $promoteStdErr = Join-Path $ArtifactsDir "promote_deep_probe_candidates.stderr.log"

  ${env:PYTHONPATH} = "$ProjectRoot\src"
  $probeTimeoutMs = [Math]::Max(120000, ($ProbeDurationS + $ProbeTimeoutPaddingS) * 1000)
  $promoteTimeoutMs = 180000
  $probeArgs = @(
    $probeScript
    "--process",
    $ProcessName,
    "--candidates",
    $SourceCandidatePath,
    "--duration-s",
    [string]$ProbeDurationS,
    "--interval-ms",
    "1000",
    "--radius",
    "4608",
    "--max-addresses",
    "12000",
    "--write-selected-meta-dir",
    $optionalMetaDir,
    "--out",
    $probeReport
  )
  $probeCapture = Invoke-PythonCapture -PythonPath $python -PythonArguments $pythonArguments -Arguments $probeArgs -StdoutPath $probeStdOut -StderrPath $probeStdErr -TimeoutMs $probeTimeoutMs

  if (-not (Test-Path $probeReport)) {
    throw "combat deep probe did not create report: $probeReport"
  }

  $promoteArgs = @(
    $promoteScript,
    "--probe-report",
    $probeReport,
    "--out",
    $promoteOut,
    "--candidate-source",
    $SourceCandidatePath
  )
  $promoteCapture = Invoke-PythonCapture -PythonPath $python -PythonArguments $pythonArguments -Arguments $promoteArgs -StdoutPath $promoteStdOut -StderrPath $promoteStdErr -TimeoutMs $promoteTimeoutMs

  if (-not (Test-Path $promoteOut)) {
    throw "candidate promotion did not create output: $promoteOut"
  }

  $promotedHash = (Get-FileHash -Path $promoteOut -Algorithm SHA256 -ErrorAction Stop).Hash
  Add-JsonField -Path $promoteOut -Fields @{
    refresh_metadata = [ordered]@{
      run_id = $RunId
      generated_at_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
      dataset_version = $DatasetVersion
      ttl_hours = 24
      source_candidates_path = $SourceCandidatePath
      source_candidates_hash_sha256 = $sourceHash
      refreshed_candidates_hash_sha256 = $promotedHash
      deep_probe_report = $probeReport
      helper_python_path = $python
      helper_python_source = $pythonInvocation.source
      helper_python_ok = [bool]$pythonInvocation.probe_ok
      helper_python_probe_error = if ($pythonInvocation.probe.error) { [string]$pythonInvocation.probe.error } else { "" }
      helper_python_args = $pythonArguments
      candidates_refresh_python_probe_ok = [bool]$pythonInvocation.probe_ok
      combat_deep_probe_exit_code = [int]$probeCapture.exit_code
      combat_deep_probe_stdout = $probeStdOut
      combat_deep_probe_stderr = $probeStdErr
      combat_promote_exit_code = [int]$promoteCapture.exit_code
      combat_promote_stdout = $promoteStdOut
      combat_promote_stderr = $promoteStdErr
      helper_probe_log = $probeStdOut
      helper_promote_log = $promoteStdOut
      helper_promote_stdout = $promoteStdOut
      helper_promote_stderr = $promoteStdErr
    }
  }

  return [ordered]@{
    candidates_path = $promoteOut
    deep_probe_report = $probeReport
    source_candidates_path = $SourceCandidatePath
    source_candidates_hash_sha256 = $sourceHash
    refreshed_candidates_hash_sha256 = $promotedHash
    helper_python_path = $python
    helper_python_source = $pythonInvocation.source
    helper_python_ok = [bool]$pythonInvocation.probe_ok
    helper_python_probe_error = if ($pythonInvocation.probe.error) { [string]$pythonInvocation.probe.error } else { "" }
    helper_python_args = $pythonArguments
    candidates_refresh_python_probe_ok = [bool]$pythonInvocation.probe_ok
    combat_deep_probe_exit_code = [int]$probeCapture.exit_code
    combat_deep_probe_stdout = $probeStdOut
    combat_deep_probe_stderr = $probeStdErr
    combat_promote_exit_code = [int]$promoteCapture.exit_code
    combat_promote_stdout = $promoteStdOut
    combat_promote_stderr = $promoteStdErr
    helper_launch_error = ""
  }
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

function Get-LatestSourceWriteTimeUtc {
  param(
    [string[]]$SourcePaths
  )

  $latest = Get-Date "1900-01-01T00:00:00Z"
  foreach ($itemPath in $SourcePaths) {
    if (-not $itemPath -or -not (Test-Path $itemPath)) {
      continue
    }
    try {
      $item = Get-Item -Path $itemPath
      if ($item.LastWriteTimeUtc -gt $latest) {
        $latest = $item.LastWriteTimeUtc
      }
    }
    catch {
      continue
    }
  }
  return $latest
}

function Start-PythonBackendProcess {
  param(
    [string]$PythonPath,
    [string[]]$PythonExtraArgs = @(),
    [int]$LauncherPort,
    [string]$OutLogPath,
    [string]$ErrLogPath,
    [bool]$HideWindow = $true
  )

  if (-not $PythonPath) {
    throw "Python executable path is required for python backend mode."
  }
  $backendArgs = @()
  if ($PythonExtraArgs) {
    $backendArgs += $PythonExtraArgs
  }
  $backendArgs += @(
    "-m",
    "uvicorn",
    "nordhold.api:app",
    "--app-dir",
    "src",
    "--host",
    "127.0.0.1",
    "--port",
    "$LauncherPort"
  )
  $startArgs = @{
    FilePath = $PythonPath
    ArgumentList = $backendArgs
    PassThru = $true
    RedirectStandardOutput = $OutLogPath
    RedirectStandardError = $ErrLogPath
    WorkingDirectory = $projectRoot
  }
  if ($HideWindow) {
    $startArgs.WindowStyle = "Hidden"
  }
  try {
    return Start-Process @startArgs
  }
  catch {
    throw "Failed to start python backend using '$PythonPath': $($_.Exception.Message)"
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
$finalStopReason = ""
$autoconnectRequestError = ""
$soakStartedUtc = (Get-Date).ToUniversalTime()
$isAdminContext = Test-IsAdminContext
$launcherNeedsElevation = $RequireAdmin -and (-not $isAdminContext) -and $AutoElevateForAdmin
$candidateCandidatesPathUsed = ""
$candidateCandidatesPathFromSource = ""
$candidateCandidatesAgeSec = 0
$candidateRefreshPerformed = $false
$candidateRefreshError = ""
$candidateRefreshDetails = @{}
$candidateRefreshAttempted = $false
$candidateCandidatesPathStale = $false
$candidateSourceSelectionMode = ""
$candidateSourceSelectionWarnings = @()
$autoconnectStable = $false
$candidateSetStale = $false
$candidateSetStaleReason = ""
$winnerCandidateId = ""
  $winnerCandidateAgeSec = 0L
$candidateNoStableCandidate = $false
$failedCandidatesCount = 0
$transient299Share = 0.0
$failFastReason = ""
$autoconnectRequestTimedOut = $false
$autoconnectTransient299Streak = 0

if ($RequireAdmin -and -not $isAdminContext -and -not $AutoElevateForAdmin) {
  Write-Warning "RequireAdmin=true but current shell is not elevated and AutoElevateForAdmin=false; attach may fail."
}

$runtimeSourceFiles = @(
  (Join-Path $projectRoot "src\nordhold\realtime\live_bridge.py"),
  (Join-Path $projectRoot "src\nordhold\realtime\calibration_candidates.py"),
  (Join-Path $projectRoot "src\nordhold\realtime\memory_reader.py"),
  (Join-Path $projectRoot "src\nordhold\api.py"),
  (Join-Path $projectRoot "scripts\run_nordhold_live_soak.ps1")
)
$runtimeSourceMtime = Get-LatestSourceWriteTimeUtc -SourcePaths $runtimeSourceFiles
$backendPythonInvocation = $null
if (Test-Path $exePath) {
  $exeInfo = Get-Item -Path $exePath
  if ($runtimeSourceMtime -gt $exeInfo.LastWriteTimeUtc.AddSeconds(120)) {
    Write-Warning "runtime dist launcher is older than source code, switching to python backend"
    $launcherMode = "python"
  }
}
else {
  $launcherMode = "python"
}
if ($launcherMode -eq "python") {
  try {
    $backendPythonInvocation = Resolve-PythonExecutable -PreferredPath $PythonPath -ProjectRoot $projectRoot -RequireUvicorn $true
  }
  catch {
    if ($launcherMode -eq "python" -and -not $ForcePythonBackend) {
      throw $_.Exception.Message
    }
  }
  if (-not $backendPythonInvocation) {
    throw "No python backend available for fallback run mode."
  }
  $launcherStartMode = "python"
}
else {
  $launcherStartMode = "dist"
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

  if ($launcherStartMode -eq "python" -and $backendPythonInvocation) {
    $launcher = Start-PythonBackendProcess `
      -PythonPath $backendPythonInvocation.path `
      -PythonExtraArgs $backendPythonInvocation.args `
      -LauncherPort $Port `
      -OutLogPath $launcherOutLog `
      -ErrLogPath $launcherErrLog `
      -HideWindow:$HideLauncherWindow
  }
  else {
    $launcher = Start-LauncherProcess `
      -ExecutablePath $exePath `
      -LauncherPort $Port `
      -OutLogPath $launcherOutLog `
      -ErrLogPath $launcherErrLog `
      -RunElevated:$launcherNeedsElevation `
      -HideWindow:$HideLauncherWindow
  }

  if (-not (Wait-ApiHealth -MaxAttempts 60)) {
    throw "API health check did not become ready on $baseUrl"
  }
  $candidateRefreshAttempted = (-not $NoAutoconnect -and $RefreshCandidates)
  $candidateCandidatesPathFromSource = [string]$CalibrationCandidatesPath
  if (-not $candidateCandidatesPathFromSource) {
    if ($candidateRefreshAttempted) {
      $candidateCandidatesPathFromSource = Find-LatestCalibrationCandidatesFile -RootPath $projectRoot -RequireRefreshReady $true -PreferNonAutoload $true
      if ($candidateCandidatesPathFromSource) {
        $candidateSourceSelectionMode = "refresh_ready_non_autoload"
      }
      if (-not $candidateCandidatesPathFromSource) {
        $candidateCandidatesPathFromSource = Find-LatestCalibrationCandidatesFile -RootPath $projectRoot -RequireRefreshReady $true
        if ($candidateCandidatesPathFromSource) {
          $candidateSourceSelectionMode = "refresh_ready_autoload_fallback"
          $candidateSourceSelectionWarnings += "refresh source selected from autoload artifact (no fresh non-autoload candidate found)"
        }
      }
      if (-not $candidateCandidatesPathFromSource) {
        $candidateCandidatesPathFromSource = Find-LatestCalibrationCandidatesFile -RootPath $projectRoot -RequireRefreshReady $false -PreferNonAutoload $true
        if ($candidateCandidatesPathFromSource) {
          $candidateSourceSelectionMode = "refresh_any_non_autoload"
        }
      }
      if (-not $candidateCandidatesPathFromSource) {
        $candidateCandidatesPathFromSource = Find-LatestCalibrationCandidatesFile -RootPath $projectRoot -RequireRefreshReady $false
        if ($candidateCandidatesPathFromSource) {
          $candidateSourceSelectionMode = "refresh_any_fallback"
          if (-not (Test-AutoloadCalibrationCandidatesFile -Path $candidateCandidatesPathFromSource)) {
            $candidateSourceSelectionMode = "refresh_any_non_autoload_legacy"
          }
        }
      }
    }
    else {
      $candidateCandidatesPathFromSource = Find-LatestCalibrationCandidatesFile -RootPath $projectRoot -PreferNonAutoload $true
      if ($candidateCandidatesPathFromSource) {
        $candidateSourceSelectionMode = "no_refresh_non_autoload"
      }
      else {
        $candidateCandidatesPathFromSource = Find-LatestCalibrationCandidatesFile -RootPath $projectRoot
        $candidateSourceSelectionMode = "no_refresh_any"
      }
    }
  }
  else {
    $candidateCandidatesPathFromSource = Convert-ToWindowsPath -Path $candidateCandidatesPathFromSource
    $candidateSourceSelectionMode = "explicit"
  }

  if ($candidateCandidatesPathFromSource -and -not (Test-Path $candidateCandidatesPathFromSource) -and (Test-Path (Convert-ToWindowsPath -Path $candidateCandidatesPathFromSource))) {
    $candidateCandidatesPathFromSource = Convert-ToWindowsPath -Path $candidateCandidatesPathFromSource
  }

  if ($candidateCandidatesPathFromSource -and $candidateSourceSelectionMode -eq "explicit" -and (Test-AutoloadCalibrationCandidatesFile -Path $candidateCandidatesPathFromSource)) {
    $candidateSourceSelectionWarnings += "explicit candidate path points to autoload output"
  }

  if ($candidateCandidatesPathFromSource) {
    $candidateCandidatesAgeSec = Get-CandidateMetadataAgeSec -Path $candidateCandidatesPathFromSource
    $candidateCandidatesPathStale = (
      $candidateCandidatesAgeSec -gt [Math]::Max(0, $CandidateTtlHours * 3600)
    )
  }
  if (-not $candidateSourceSelectionMode -and $candidateCandidatesPathFromSource) {
    $candidateSourceSelectionMode = "selected_default"
  }
  if ($candidateRefreshAttempted -and -not (Test-Path $candidateCandidatesPathFromSource)) {
    throw "No calibration candidates source path was found for refresh."
  }

      if ($candidateRefreshAttempted -and $candidateCandidatesPathFromSource) {
        $candidateRefreshRoot = Join-Path $logDir "$runId.candidates-refresh"
        try {
      $candidateRefreshPerformed = $true
      $candidateRefreshDetails = Invoke-SoakCandidatesRefresh -SourceCandidatePath $candidateCandidatesPathFromSource -RunId $runId -ProjectRoot $projectRoot -ArtifactsDir $candidateRefreshRoot -ProcessName $ProcessName -DatasetVersion $DatasetVersion -ProbeDurationS $CandidateProbeDurationS -PythonPath $PythonPath
      if (-not [string]::IsNullOrWhiteSpace($candidateRefreshDetails.candidates_path) -and (Test-Path $candidateRefreshDetails.candidates_path)) {
        $candidateCandidatesPathFromSource = [string]$candidateRefreshDetails.candidates_path
        $candidateCandidatesAgeSec = Get-CandidateMetadataAgeSec -Path $candidateCandidatesPathFromSource
        $candidateCandidatesPathStale = $false
      }
      $candidateRefreshError = ""
    }
    catch {
      $candidateRefreshPerformed = $false
      $candidateRefreshError = "candidate refresh failed: $($_.Exception.Message)"
      if (-not $candidateRefreshDetails -or -not $candidateRefreshDetails.Count) {
        $candidateRefreshDetails = @{}
      }
      if (-not $candidateRefreshDetails.ContainsKey("helper_python_path") -or -not $candidateRefreshDetails.helper_python_path) {
        $candidateRefreshDetails["helper_python_path"] = if ($PythonPath) { [string](Normalize-PythonCandidatePath -Path $PythonPath) } else { "" }
      }
      if (-not $candidateRefreshDetails.ContainsKey("helper_python_source") -or -not $candidateRefreshDetails.helper_python_source) {
        $candidateRefreshDetails["helper_python_source"] = "resolve_python_failed"
      }
      $candidateRefreshDetails["helper_launch_error"] = $candidateRefreshError
      $candidateRefreshDetails["helper_python_ok"] = $false
      $candidateRefreshDetails["combat_deep_probe_stdout"] = Join-Path $candidateRefreshRoot "combat_deep_probe.stdout.log"
      $candidateRefreshDetails["combat_deep_probe_stderr"] = Join-Path $candidateRefreshRoot "combat_deep_probe.stderr.log"
      $candidateRefreshDetails["combat_promote_stdout"] = Join-Path $candidateRefreshRoot "promote_deep_probe_candidates.stdout.log"
      $candidateRefreshDetails["combat_promote_stderr"] = Join-Path $candidateRefreshRoot "promote_deep_probe_candidates.stderr.log"
      if ($candidateRefreshError -match "helper_launch_invalid_python_path|No Python executable found for candidate refresh") {
        $candidateSetStaleReason = "refresh_helper_python_missing"
      }
      if ($candidateRefreshError -match "No Python at|No Python executable found for candidate refresh") {
        $candidateRefreshDetails["helper_python_probe_error"] = $candidateRefreshError
      }
      if (-not $candidateSetStaleReason -and $candidateSourceSelectionMode -like "*autoload*") {
        $candidateSetStaleReason = "refresh_source_stale_or_recursive"
      }
      if ($candidateRefreshError -match "refresh_helper_python_missing|helper_launch_invalid_python_path|No Python executable found for candidate refresh") {
        $candidateSetStale = $true
        $candidateSetStaleReason = "refresh_helper_python_missing"
        $candidateCandidatesPathStale = $true
        $finalStopReason = "refresh_helper_python_missing"
        $runAbortedReason = $finalStopReason
        $failFastReason = $finalStopReason
      }
      Write-Warning $candidateRefreshError
    }
  }

  if ($candidateSourceSelectionMode -and $candidateSourceSelectionMode -ne "") {
    $candidateRefreshDetails["source_selection_mode"] = $candidateSourceSelectionMode
  }
  if ($candidateSourceSelectionWarnings.Count -gt 0) {
    $candidateRefreshDetails["source_selection_warnings"] = $candidateSourceSelectionWarnings
  }

  if (-not $NoAutoconnect -and $candidateCandidatesPathStale -and -not $AllowStaleCandidates -and -not $candidateRefreshPerformed) {
    throw "Candidate artifact is stale (age=${candidateCandidatesAgeSec}s, ttl=$($CandidateTtlHours)h) and refresh failed."
  }

  if (-not $candidateCandidatesPathFromSource -and -not $NoAutoconnect -and -not $RefreshCandidates) {
    Write-Warning "No candidate artifact path was provided and refresh is disabled. Autoconnect will fallback to live discovery."
  }
  if ($candidateCandidatesPathFromSource -and (Test-Path $candidateCandidatesPathFromSource)) {
    $candidateCandidatesPathUsed = [string]$candidateCandidatesPathFromSource
  }
  if ($candidateCandidatesPathUsed -and -not $NoAutoconnect -and $candidateCandidatesPathStale -and -not $AllowStaleCandidates -and -not $candidateRefreshPerformed) {
    throw "Candidate artifact is stale and stale artifacts are disabled (age=${candidateCandidatesAgeSec}s, ttl=$($CandidateTtlHours)h)."
  }

  if (-not $NoAutoconnect -and -not $finalStopReason) {
    $autoconnectPayload = @{
      process_name = $ProcessName
      poll_ms = $PollMs
      require_admin = $RequireAdmin
      dataset_version = $DatasetVersion
      dataset_autorefresh = $true
    } | ConvertTo-Json
    if ($candidateCandidatesPathUsed) {
      $autoconnectPayload = [ordered]@{
        process_name = $ProcessName
        poll_ms = $PollMs
        require_admin = $RequireAdmin
        dataset_version = $DatasetVersion
        dataset_autorefresh = $true
        calibration_candidates_path = $candidateCandidatesPathUsed
      } | ConvertTo-Json
    }

    try {
      $autoconnectResponse = Invoke-Api -Method "POST" -Path "/api/v1/live/autoconnect" -Body $autoconnectPayload -TimeoutSec $AutoconnectRequestTimeoutS
    }
    catch {
      $autoconnectResponse = @{
        error = $_.Exception.Message
      }
      $autoconnectRequestError = [string]$_.Exception.Message
      if ($_.Exception.Message -match "timed out|timeout") {
        $autoconnectRequestTimedOut = $true
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
        $autoconnectResponse = Invoke-Api -Method "POST" -Path "/api/v1/live/autoconnect" -Body $fallbackAutoconnectPayload -TimeoutSec $AutoconnectRequestTimeoutS
      }
      catch {
        $autoconnectResponse = @{
          error = $_.Exception.Message
          fallback_attempted = $true
          fallback_require_admin = $true
        }
        $autoconnectRequestError = [string]$_.Exception.Message
        if ($_.Exception.Message -match "timed out|timeout") {
          $autoconnectRequestTimedOut = $true
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

    if ($autoconnectRequestTimedOut -and (-not $autoconnectStable)) {
      for ($probeIdx = 0; $probeIdx -lt 2; $probeIdx++) {
        Start-Sleep -Milliseconds 200
        try {
          $probeStatus = Invoke-Api -Method "GET" -Path "/api/v1/live/status" -TimeoutSec 3
        }
        catch {
          continue
        }
        $latestProbeReason = [string]$probeStatus.reason
        if ([bool]$probeStatus.memory_connected -and [string]$probeStatus.mode -eq "memory") {
          $autoconnectStable = $true
          break
        }
        if ([bool]$probeStatus.candidate_set_stale) {
          $candidateSetStale = [bool]$probeStatus.candidate_set_stale
          if (-not $candidateSetStaleReason -and $probeStatus.candidate_set_stale_reason) {
            $candidateSetStaleReason = [string]$probeStatus.candidate_set_stale_reason
          }
          break
        }
        if (Test-Transient299Reason -Reason $latestProbeReason) {
          $autoconnectTransient299Streak += 1
          if ($autoconnectTransient299Streak -ge [Math]::Max(1, [Math]::Min(3, $Transient299FailFastCycles))) {
            $candidateSetStale = $true
            if (-not $candidateSetStaleReason) {
              $candidateSetStaleReason = "autoconnect_request_timeout_with_transient_299"
            }
            break
          }
        }
        else {
          $autoconnectTransient299Streak = 0
        }
        if ([string]$probeStatus.mode -eq "memory") {
          $autoconnectStable = $true
          break
        }
      }
    }

    if ($autoconnectResponse.ContainsKey("error")) {
      if (-not $autoconnectResponse.ContainsKey("request_error")) {
        $autoconnectResponse["request_error"] = [string]$autoconnectResponse["error"]
      }
      if ($autoconnectRequestError -and -not $autoconnectResponse.ContainsKey("request_error")) {
        $autoconnectResponse["request_error"] = $autoconnectRequestError
      }
      $autoconnectResponse["request_timed_out"] = [bool]$autoconnectRequestTimedOut
    }

    if ($autoconnectResponse.ContainsKey("candidate_set_stale") -and [bool]$autoconnectResponse["candidate_set_stale"]) {
      $candidateSetStale = [bool]$autoconnectResponse["candidate_set_stale"]
      $candidateSetStaleReason = [string]$autoconnectResponse["candidate_set_stale_reason"]
    }
    if ($autoconnectResponse.ContainsKey("ok") -and [bool]$autoconnectResponse["ok"]) {
      $autoconnectStable = $true
    }
    if (-not $autoconnectStable -and $candidateSetStale) {
      $finalStopReason = "autoconnect_candidate_set_stale"
      $runAbortedReason = $finalStopReason
      $failFastReason = $finalStopReason
    }
    if ($autoconnectResponse.ContainsKey("no_stable_candidate")) {
      $candidateNoStableCandidate = [bool]$autoconnectResponse["no_stable_candidate"]
    }
    if ($autoconnectResponse.ContainsKey("winner_candidate_id") -and [string]$autoconnectResponse["winner_candidate_id"]) {
      $winnerCandidateId = [string]$autoconnectResponse["winner_candidate_id"]
    }
    if ($autoconnectResponse.ContainsKey("winner_candidate_age_sec")) {
      $winnerCandidateAgeParsed = Convert-NonNegativeInt -Value $autoconnectResponse["winner_candidate_age_sec"] -Default 0
      if ($null -ne $winnerCandidateAgeParsed) {
        $winnerCandidateAgeSec = [long]$winnerCandidateAgeParsed
      }
    }
    if ($autoconnectResponse.ContainsKey("failed_candidates_count")) {
      $failedCandidatesCountParsed = Convert-NonNegativeInt -Value $autoconnectResponse["failed_candidates_count"] -Default 0
      if ($null -ne $failedCandidatesCountParsed) {
        $failedCandidatesCount = [int]$failedCandidatesCountParsed
      }
    }
    if ($autoconnectResponse.ContainsKey("winerr299_rate")) {
      $transient299Share = [double]$autoconnectResponse["winerr299_rate"]
    }
    if ($autoconnectResponse.ContainsKey("attempts") -and $autoconnectResponse["attempts"]) {
      $candidateAttempts = $autoconnectResponse["attempts"]
      $attemptSummary = Evaluate-AutoconnectAttemptsTransient299 -Attempts $candidateAttempts -Threshold ([Math]::Max(2, [Math]::Min(3, $Transient299FailFastCycles)))
      $allTransient = [bool]$attemptSummary[0]
      $attemptCount = [int]$attemptSummary[1]
      if (-not $candidateSetStale -and -not $autoconnectStable -and $allTransient -and $attemptCount -gt 0) {
        $candidateSetStale = $true
        if (-not $candidateSetStaleReason) {
          $candidateSetStaleReason = "autoconnect_all_attempts_transient_299"
        }
      }
      if ($attemptCount -gt 0) {
        $failedCandidatesCount = [int]$attemptCount
      }
    }
  }

  if ($finalStopReason) {
    Write-Host "Autoconnect pre-check failed: $finalStopReason"
  }

  if (-not $finalStopReason) {
    for ($i = 0; $i -lt $DurationS; $i++) {
      $sw = [System.Diagnostics.Stopwatch]::StartNew()
      try {
        $status = Invoke-Api -Method "GET" -Path "/api/v1/live/status"
        $null = Invoke-Api -Method "GET" -Path "/api/v1/live/snapshot"
        $null = Invoke-Api -Method "GET" -Path "/api/v1/run/state"

        $lastMode = [string]$status.mode
        $lastReason = [string]$status.reason
        $lastMemoryConnected = [bool]$status.memory_connected

        $latestTransient299 = [bool](Test-Transient299Reason -Reason $lastReason)
        if ($latestTransient299) {
          $autoconnectTransient299Streak += 1
          if ($transient299Share -lt 1.0) {
            $transient299Share = 1.0
          }
        }
        else {
          $autoconnectTransient299Streak = 0
        }
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

        $statusCandidateSetStale = [bool]$status.candidate_set_stale
        $statusCandidateSetStaleReason = [string]$status.candidate_set_stale_reason
        if ($statusCandidateSetStale) {
          $candidateSetStale = $true
          if (-not $candidateSetStaleReason) {
            $candidateSetStaleReason = $statusCandidateSetStaleReason
          }
        }
        if ([string]$status.winner_candidate_id) {
          $winnerCandidateId = [string]$status.winner_candidate_id
        }
        $winnerCandidateAgeParsed = Convert-NonNegativeInt -Value $status.winner_candidate_age_sec -Default 0
        if ($null -ne $winnerCandidateAgeParsed) {
          $winnerCandidateAgeSec = [long]$winnerCandidateAgeParsed
        }
        if ($autoconnectResponse.ContainsKey("winerr299_rate")) {
          $transient299Share = [double]$autoconnectResponse["winerr299_rate"]
        }
        if ($autoconnectResponse.ContainsKey("no_stable_candidate")) {
          $candidateNoStableCandidate = [bool]$autoconnectResponse["no_stable_candidate"]
        }
        if ($autoconnectResponse.ContainsKey("failed_candidates_count")) {
          $failedCandidatesCountParsed = Convert-NonNegativeInt -Value $autoconnectResponse["failed_candidates_count"] -Default 0
          if ($null -ne $failedCandidatesCountParsed) {
            $failedCandidatesCount = [int]$failedCandidatesCountParsed
          }
        }

        if ($status.mode -eq "memory") {
          $autoconnectStable = $true
        }
        elseif ($autoconnectResponse.ContainsKey("ok") -and [bool]$autoconnectResponse["ok"]) {
          $autoconnectStable = $true
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

        if (-not $NoAutoconnect -and -not $autoconnectStable -and $candidateSetStale) {
        $finalStopReason = "autoconnect_candidate_set_stale"
        $runAbortedReason = $finalStopReason
        $failFastReason = $finalStopReason
        break
      }
        if (-not $NoAutoconnect -and -not $autoconnectStable -and $autoconnectRequestTimedOut -and $latestTransient299 -and $autoconnectTransient299Streak -ge [Math]::Max(2, [Math]::Min(3, $Transient299FailFastCycles))) {
          $candidateSetStale = $true
          if (-not $candidateSetStaleReason) {
            $candidateSetStaleReason = "autoconnect_request_timeout_with_transient_299"
          }
          $finalStopReason = "autoconnect_candidate_set_stale"
          $runAbortedReason = $finalStopReason
          $failFastReason = $finalStopReason
          break
        }
      if (-not $NoAutoconnect -and -not $autoconnectStable -and $elapsedS -ge [Math]::Max(1, $AutoconnectFailFastS)) {
        $finalStopReason = "autoconnect_fail_fast_not_memory"
        $runAbortedReason = $finalStopReason
        $failFastReason = $finalStopReason
        break
      }

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
        launcher_mode = [string]$launcherStartMode
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
        candidate_set_stale = [bool]$candidateSetStale
        candidate_set_stale_reason = [string]$candidateSetStaleReason
        candidate_stale_reason = [string]$candidateSetStaleReason
        winner_candidate_id = [string]$winnerCandidateId
        winner_candidate_age_sec = [long]$winnerCandidateAgeSec
        failed_candidates_count = [int]$failedCandidatesCount
        no_stable_candidate = [bool]$candidateNoStableCandidate
        candidate_no_stable_candidate = [bool]$candidateNoStableCandidate
        fail_fast_reason = [string]$failFastReason
        transient_299_share = [Math]::Round($transient299Share, 4)
        launcher_python_path = if ($backendPythonInvocation -and $backendPythonInvocation.path) { [string]$backendPythonInvocation.path } else { "" }
        launcher_python_source = if ($backendPythonInvocation -and $backendPythonInvocation.source) { [string]$backendPythonInvocation.source } else { "" }
        launcher_python_ok = if ($launcherStartMode -eq "python" -and $backendPythonInvocation -and $backendPythonInvocation.probe_ok) { [bool]$backendPythonInvocation.probe_ok } elseif ($launcherStartMode -eq "python") { $false } else { $true }
        admin_fallback_applied = $adminFallbackApplied
        autoconnect_attempt_require_admin = $autoconnectAttemptRequireAdmin
        final_stop_reason = [string]$finalStopReason
        candidate_candidates_path = [string]$candidateCandidatesPathUsed
        candidate_candidates_age_sec = [int]$candidateCandidatesAgeSec
        candidate_candidates_path_stale = [bool]$candidateCandidatesPathStale
        candidate_refresh_performed = [bool]$candidateRefreshPerformed
        candidate_refresh_error = [string]$candidateRefreshError
        candidate_source_selection_mode = [string]$candidateSourceSelectionMode
        candidate_source_selection_warnings = [string[]]$candidateSourceSelectionWarnings
        autoconnect = $autoconnectResponse
        launcher_pid = if ($launcher) { $launcher.Id } else { 0 }
        launcher_out_log = $launcherOutLog
        launcher_err_log = $launcherErrLog
        summary_path = $summaryPath
      }
      Set-Content -Path $partialPath -Value ($partial | ConvertTo-Json -Depth 8) -Encoding UTF8

      Start-Sleep -Milliseconds $PollMs
    }
  }
  if ($finalStopReason) {
    $runCompleted = $false
    if (-not $runAbortedReason) {
      $runAbortedReason = $finalStopReason
    }
  }
  else {
    $runCompleted = ($iterations -ge $DurationS)
  }
}
catch {
  $runAbortedReason = $_.Exception.Message
  if (-not $finalStopReason) {
    if ($runAbortedReason) {
      $finalStopReason = "exception: $runAbortedReason"
    }
    else {
      $finalStopReason = "exception"
    }
  }
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
    launcher_mode = [string]$launcherStartMode
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
    candidate_set_stale = [bool]$candidateSetStale
    candidate_set_stale_reason = [string]$candidateSetStaleReason
    candidate_stale_reason = [string]$candidateSetStaleReason
    winner_candidate_id = [string]$winnerCandidateId
    winner_candidate_age_sec = [long]$winnerCandidateAgeSec
    failed_candidates_count = [int]$failedCandidatesCount
    no_stable_candidate = [bool]$candidateNoStableCandidate
    candidate_no_stable_candidate = [bool]$candidateNoStableCandidate
    final_stop_reason = [string]$finalStopReason
    fail_fast_reason = [string]$failFastReason
    transient_299_share = [Math]::Round($transient299Share, 4)
    launcher_python_path = if ($backendPythonInvocation -and $backendPythonInvocation.path) { [string]$backendPythonInvocation.path } else { "" }
    launcher_python_source = if ($backendPythonInvocation -and $backendPythonInvocation.source) { [string]$backendPythonInvocation.source } else { "" }
    launcher_python_ok = if ($launcherStartMode -eq "python" -and $backendPythonInvocation -and $backendPythonInvocation.probe_ok) { [bool]$backendPythonInvocation.probe_ok } elseif ($launcherStartMode -eq "python") { $false } else { $true }
    candidate_candidates_path = [string]$candidateCandidatesPathUsed
    candidate_candidates_age_sec = [int]$candidateCandidatesAgeSec
    candidate_candidates_path_stale = [bool]$candidateCandidatesPathStale
    candidate_refresh_performed = [bool]$candidateRefreshPerformed
    candidate_refresh_error = [string]$candidateRefreshError
    candidate_refresh_details = $candidateRefreshDetails
    candidate_refresh_attempted = [bool]$candidateRefreshAttempted
    candidate_source_selection_mode = [string]$candidateSourceSelectionMode
    candidate_source_selection_warnings = [string[]]$candidateSourceSelectionWarnings
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
    launcher_mode = [string]$launcherStartMode
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
    candidate_set_stale = [bool]$candidateSetStale
    candidate_set_stale_reason = [string]$candidateSetStaleReason
    candidate_stale_reason = [string]$candidateSetStaleReason
    winner_candidate_id = [string]$winnerCandidateId
    winner_candidate_age_sec = [long]$winnerCandidateAgeSec
    failed_candidates_count = [int]$failedCandidatesCount
    no_stable_candidate = [bool]$candidateNoStableCandidate
    candidate_no_stable_candidate = [bool]$candidateNoStableCandidate
    final_stop_reason = [string]$finalStopReason
    fail_fast_reason = [string]$failFastReason
    transient_299_share = [Math]::Round($transient299Share, 4)
    launcher_python_path = if ($backendPythonInvocation -and $backendPythonInvocation.path) { [string]$backendPythonInvocation.path } else { "" }
    launcher_python_source = if ($backendPythonInvocation -and $backendPythonInvocation.source) { [string]$backendPythonInvocation.source } else { "" }
    launcher_python_ok = if ($launcherStartMode -eq "python" -and $backendPythonInvocation -and $backendPythonInvocation.probe_ok) { [bool]$backendPythonInvocation.probe_ok } elseif ($launcherStartMode -eq "python") { $false } else { $true }
    candidate_candidates_path = [string]$candidateCandidatesPathUsed
    candidate_candidates_age_sec = [int]$candidateCandidatesAgeSec
    candidate_candidates_path_stale = [bool]$candidateCandidatesPathStale
    candidate_refresh_performed = [bool]$candidateRefreshPerformed
    candidate_refresh_error = [string]$candidateRefreshError
    candidate_refresh_details = $candidateRefreshDetails
    candidate_refresh_attempted = [bool]$candidateRefreshAttempted
    candidate_source_selection_mode = [string]$candidateSourceSelectionMode
    candidate_source_selection_warnings = [string[]]$candidateSourceSelectionWarnings
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
