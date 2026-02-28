param(
  [int]$DurationS = 600,
  [switch]$IncludeSamples
)

$ErrorActionPreference = "Stop"
$projectRoot = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold"
$artifactRoot = Join-Path $projectRoot "worklogs\t47-signature-profile-fallback\artifacts"
$runId = "nordhold-combat-deep-probe-{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$artifactDir = Join-Path $artifactRoot $runId
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null

$python = "C:\Users\lenovo\Documents\cursor\.venv\Scripts\python.exe"
$script = Join-Path $projectRoot "scripts\nordhold_combat_deep_probe.py"
$candidates = Get-ChildItem -Path $artifactRoot -Recurse -Filter "memory_calibration_candidates_autoload.json" -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 -ExpandProperty FullName
if (-not $candidates) {
  throw "memory_calibration_candidates_autoload.json not found under $artifactRoot"
}

$gameProc = Get-Process -Name "NordHold" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $gameProc) {
  throw "NordHold.exe is not running. Start the game and rerun deep probe."
}

$out = Join-Path $artifactDir "combat_deep_probe_long_report.json"
$metaDir = Join-Path $artifactDir "auto_optional_meta_long"
$logOut = Join-Path $artifactDir "combat_deep_probe_long.stdout.log"
$logErr = Join-Path $artifactDir "combat_deep_probe_long.stderr.log"
$pidFile = Join-Path $artifactDir "combat_deep_probe_long.pid"

$env:PYTHONPATH = "$projectRoot\src"
$args = @(
  $script,
  "--process", "NordHold.exe",
  "--candidates", $candidates,
  "--duration-s", "$DurationS",
  "--interval-ms", "1000",
  "--radius", "4608",
  "--max-addresses", "12000",
  "--write-selected-meta-dir", $metaDir,
  "--out", $out
)
if ($IncludeSamples) {
  $args += "--include-samples"
}

$proc = Start-Process -FilePath $python -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logErr
$proc.Id | Set-Content -Path $pidFile -Encoding ascii
[PSCustomObject]@{
  pid = $proc.Id
  stdout = $logOut
  stderr = $logErr
  report = $out
  pid_file = $pidFile
  candidates = $candidates
  run_id = $runId
  artifact_dir = $artifactDir
  include_samples = [bool]$IncludeSamples
  duration_s = $DurationS
  game_pid = $gameProc.Id
} | ConvertTo-Json -Depth 6
