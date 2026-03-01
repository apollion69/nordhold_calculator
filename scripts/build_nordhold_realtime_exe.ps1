param(
  [switch]$SkipFrontendBuild,
  [switch]$SkipStopRunningLauncher,
  [bool]$QuietExternal = $true
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $projectRoot))
$logDir = Join-Path $projectRoot "runtime\logs"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Assert-ExternalSuccess {
  param(
    [string]$StepName
  )

  # Some hosts may leave LASTEXITCODE as $null; treat that as "unknown" and continue.
  if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    throw "$StepName failed with exit code $LASTEXITCODE."
  }
}

function Stop-NordholdLauncherProcesses {
  param(
    [switch]$SkipStop
  )

  if ($SkipStop) {
    return
  }

  $running = @(Get-Process -Name "NordholdRealtimeLauncher" -ErrorAction SilentlyContinue)
  if ($running.Count -eq 0) {
    return
  }

  Write-Host "Stopping running NordholdRealtimeLauncher processes..."
  foreach ($proc in $running) {
    try {
      Stop-Process -Id $proc.Id -Force -ErrorAction Stop
    }
    catch {
      # Best-effort fallback; may still fail without elevation.
      cmd.exe /c "taskkill /F /PID $($proc.Id)" *> $null
    }
  }

  Start-Sleep -Milliseconds 400
  $remaining = @(Get-Process -Name "NordholdRealtimeLauncher" -ErrorAction SilentlyContinue)
  if ($remaining.Count -gt 0) {
    $pidList = ($remaining | ForEach-Object { $_.Id }) -join ", "
    throw "Cannot stop NordholdRealtimeLauncher.exe (PID(s): $pidList). Close launcher or run this script as Administrator, then retry."
  }
}

function Get-StepToken {
  param(
    [string]$StepName
  )

  if (-not $StepName) {
    return "step"
  }

  $token = $StepName -replace "[^A-Za-z0-9_-]", "_"
  if (-not $token) {
    return "step"
  }
  return $token
}

function Invoke-ExternalCommand {
  param(
    [string]$StepName,
    [string]$FilePath,
    [string[]]$Arguments = @(),
    [string]$WorkingDirectory = $projectRoot
  )

  if (-not $QuietExternal) {
    Push-Location $WorkingDirectory
    try {
      & $FilePath @Arguments
      Assert-ExternalSuccess $StepName
    }
    finally {
      Pop-Location
    }
    return
  }

  $token = Get-StepToken -StepName $StepName
  $stdoutLog = Join-Path $logDir "$timestamp.$token.out.log"
  $stderrLog = Join-Path $logDir "$timestamp.$token.err.log"
  $proc = Start-Process `
    -FilePath $FilePath `
    -ArgumentList $Arguments `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru `
    -Wait

  if ($proc.ExitCode -ne 0) {
    throw "$StepName failed with exit code $($proc.ExitCode). Logs: $stdoutLog ; $stderrLog"
  }
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$sharedVenvPython = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython) -and (Test-Path $sharedVenvPython)) {
  $venvPython = $sharedVenvPython
}
if (-not (Test-Path $venvPython)) {
  throw "Python virtual environment is missing. Expected at: $venvPython or $sharedVenvPython"
}

$webRoot = Join-Path $projectRoot "web"
$webDist = Join-Path $webRoot "dist\index.html"

if (-not $SkipFrontendBuild -and -not (Test-Path $webDist)) {
  Write-Host "Frontend bundle not found. Building web/dist..."
  $npm = Get-Command npm -ErrorAction SilentlyContinue
  if (-not $npm) {
    throw "npm is required to build frontend before packaging EXE."
  }
  Invoke-ExternalCommand -StepName "npm_install" -FilePath $npm.Source -Arguments @("install", "--no-audit", "--no-fund") -WorkingDirectory $webRoot
  Invoke-ExternalCommand -StepName "npm_build" -FilePath $npm.Source -Arguments @("run", "build") -WorkingDirectory $webRoot
}

if (-not (Test-Path $webDist)) {
  throw "Frontend bundle is missing: $webDist"
}

$distRoot = Join-Path $projectRoot "runtime\dist"
$buildRoot = Join-Path $projectRoot "runtime\build\pyinstaller"
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null

$targetDistDir = Join-Path $distRoot "NordholdRealtimeLauncher"
Stop-NordholdLauncherProcesses -SkipStop:$SkipStopRunningLauncher
if (Test-Path $targetDistDir) {
  try {
    Remove-Item -Path $targetDistDir -Recurse -Force
  }
  catch {
    throw "Failed to clean target dist dir '$targetDistDir'. Ensure launcher is not running (or use Administrator), then retry. Original error: $($_.Exception.Message)"
  }
}

Write-Host "Installing packaging dependencies..."
Invoke-ExternalCommand -StepName "pip_upgrade" -FilePath $venvPython -Arguments @("-m", "pip", "install", "-q", "--disable-pip-version-check", "--upgrade", "pip")
Invoke-ExternalCommand -StepName "pip_editable" -FilePath $venvPython -Arguments @("-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", $projectRoot)
Invoke-ExternalCommand -StepName "pip_pyinstaller" -FilePath $venvPython -Arguments @("-m", "pip", "install", "-q", "--disable-pip-version-check", "pyinstaller")

Write-Host "Building EXE with PyInstaller..."
$pyInstallerArgs = @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  "--name", "NordholdRealtimeLauncher",
  "--distpath", $distRoot,
  "--workpath", $buildRoot,
  "--specpath", $buildRoot,
  "--paths", (Join-Path $projectRoot "src"),
  "--collect-submodules", "uvicorn",
  "--collect-submodules", "fastapi",
  "--collect-submodules", "pydantic",
  "--add-data", "$projectRoot\\data;data",
  "--add-data", "$projectRoot\\web\\dist;web\\dist",
  "$projectRoot\\src\\nordhold\\launcher.py"
)

Invoke-ExternalCommand -StepName "pyinstaller_build" -FilePath $venvPython -Arguments $pyInstallerArgs

$exePath = Join-Path $targetDistDir "NordholdRealtimeLauncher.exe"
if (-not (Test-Path $exePath)) {
  throw "EXE was not produced at expected path: $exePath"
}

Write-Host "Build completed."
Write-Host "EXE: $exePath"
Write-Host "Post-build API smoke targets:"
Write-Host "  POST http://127.0.0.1:8000/api/v1/live/autoconnect"
Write-Host "  GET  http://127.0.0.1:8000/api/v1/dataset/version"
Write-Host "  GET  http://127.0.0.1:8000/api/v1/dataset/catalog"
Write-Host "  GET  http://127.0.0.1:8000/api/v1/run/state"
Write-Host "  GET  http://127.0.0.1:8000/api/v1/events"
Write-Host "Legacy compatibility endpoints are still served:"
Write-Host "  GET  http://127.0.0.1:8000/api/v1/live/status"
Write-Host "  GET  http://127.0.0.1:8000/api/v1/live/snapshot"
