param(
  [switch]$SkipFrontendBuild,
  [switch]$SkipStopRunningLauncher
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $projectRoot))

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
  Push-Location $webRoot
  try {
    & $npm.Source install --no-audit --no-fund
    Assert-ExternalSuccess "npm install"
    & $npm.Source run build
    Assert-ExternalSuccess "npm run build"
  }
  finally {
    Pop-Location
  }
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
& $venvPython -m pip install -q --upgrade pip
& $venvPython -m pip install -q -e $projectRoot
& $venvPython -m pip install -q pyinstaller

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

& $venvPython @pyInstallerArgs

Assert-ExternalSuccess "PyInstaller build"

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
