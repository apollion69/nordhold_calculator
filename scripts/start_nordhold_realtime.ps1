param(
  [switch]$NoBrowser,
  [bool]$HideBackendWindow = $true
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $projectRoot "runtime/logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backendOutLog = Join-Path $logDir "backend_$timestamp.out.log"
$backendErrLog = Join-Path $logDir "backend_$timestamp.err.log"
$frontendOutLog = Join-Path $logDir "frontend_$timestamp.out.log"
$frontendErrLog = Join-Path $logDir "frontend_$timestamp.err.log"
$bindHost = "127.0.0.1"
$port = 8000
$baseUrl = "http://$bindHost`:$port"

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$workspaceRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $projectRoot))
$sharedVenvPython = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
$webRoot = Join-Path $projectRoot "web"
$webDist = Join-Path $webRoot "dist\index.html"

function Test-NordholdApiGet {
  param(
    [string]$Url,
    [int]$TimeoutSec = 2
  )

  try {
    $response = Invoke-WebRequest -Method Get -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
  }
  catch {
    return $false
  }
}

function Resolve-StateEndpoint {
  param(
    [string]$BaseUrl,
    [int]$WaitSeconds = 12
  )

  $canonicalState = "$BaseUrl/api/v1/run/state"
  $legacyState = "$BaseUrl/api/v1/live/status"
  $attempts = [Math]::Max(1, [int]($WaitSeconds * 2))

  for ($i = 0; $i -lt $attempts; $i++) {
    if (Test-NordholdApiGet -Url $canonicalState -TimeoutSec 2) {
      return $canonicalState
    }
    if (Test-NordholdApiGet -Url $legacyState -TimeoutSec 2) {
      return $legacyState
    }
    Start-Sleep -Milliseconds 500
  }

  return ""
}

Write-Host "Project root: $projectRoot"
Write-Host "Backend logs: $backendOutLog / $backendErrLog"
Write-Host "Frontend logs: $frontendOutLog / $frontendErrLog"

Push-Location $projectRoot
try {
  if (-not (Test-Path $venvPython) -and (Test-Path $sharedVenvPython)) {
    Write-Host "Using shared workspace virtual environment: $sharedVenvPython"
    $venvPython = $sharedVenvPython
  }

  if (-not (Test-Path $venvPython)) {
    throw "Python virtual environment is missing. Expected at: $venvPython or $sharedVenvPython"
  }

  if (-not (Test-Path $webDist)) {
    Write-Host "Frontend bundle not found. Building web/dist..."
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) {
      Push-Location $webRoot
      try {
        & $npm.Source install --no-audit --no-fund *> $frontendOutLog
        if ($LASTEXITCODE -ne 0) {
          throw "npm install failed. Check: $frontendOutLog"
        }

        & $npm.Source run build 1>> $frontendOutLog 2>> $frontendErrLog
        if ($LASTEXITCODE -ne 0) {
          throw "npm run build failed. Check: $frontendOutLog / $frontendErrLog"
        }
      }
      finally {
        Pop-Location
      }
    }
    else {
      $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
      if (-not $wsl) {
        throw "Frontend bundle is missing and neither npm nor wsl.exe is available. Missing file: $webDist"
      }

      $drive = $projectRoot.Substring(0, 1).ToLower()
      $rest = $projectRoot.Substring(3).Replace('\', '/')
      $webRootWsl = "/mnt/$drive/$rest/web"
      $wslBuildCmd = "cd '$webRootWsl' && npm install --no-audit --no-fund && npm run build"

      & $wsl.Source -- bash -lc $wslBuildCmd 1>> $frontendOutLog 2>> $frontendErrLog
      if ($LASTEXITCODE -ne 0) {
        throw "WSL frontend build failed. Check: $frontendOutLog / $frontendErrLog"
      }
    }

    if (-not (Test-Path $webDist)) {
      throw "Frontend build completed but bundle is still missing: $webDist"
    }
  }

  Write-Host "Ensuring backend dependencies..."
  & $venvPython -m pip install -q --upgrade pip
  & $venvPython -m pip install -q -e $projectRoot

  $backendStartArgs = @{
    FilePath = $venvPython
    ArgumentList = @("-m", "uvicorn", "nordhold.api:app", "--app-dir", "src", "--host", $bindHost, "--port", "$port")
    RedirectStandardOutput = $backendOutLog
    RedirectStandardError = $backendErrLog
    PassThru = $true
  }
  if ($HideBackendWindow) {
    $backendStartArgs.WindowStyle = "Hidden"
  }
  $backend = Start-Process @backendStartArgs

  Start-Sleep -Seconds 1
  $stateEndpoint = Resolve-StateEndpoint -BaseUrl $baseUrl -WaitSeconds 12

  if (-not $NoBrowser) {
    Start-Process $baseUrl
  }

  Write-Host "Backend PID: $($backend.Id)"
  Write-Host "Open UI: $baseUrl"
  if ($stateEndpoint) {
    Write-Host "State endpoint ready: $stateEndpoint"
  }
  else {
    Write-Host "State endpoint is warming up. Preferred: $baseUrl/api/v1/run/state (legacy fallback: $baseUrl/api/v1/live/status)"
  }
  Write-Host "API endpoints:"
  Write-Host "  POST $baseUrl/api/v1/live/autoconnect"
  Write-Host "  GET  $baseUrl/api/v1/dataset/version"
  Write-Host "  GET  $baseUrl/api/v1/dataset/catalog"
  Write-Host "  GET  $baseUrl/api/v1/run/state"
  Write-Host "  GET  $baseUrl/api/v1/events"
  Write-Host "Backward-compatible live endpoints remain available:"
  Write-Host "  GET  $baseUrl/api/v1/live/status"
  Write-Host "  GET  $baseUrl/api/v1/live/snapshot"
  Write-Host "Use scripts/stop_nordhold_realtime.ps1 to stop backend."
}
finally {
  Pop-Location
}
