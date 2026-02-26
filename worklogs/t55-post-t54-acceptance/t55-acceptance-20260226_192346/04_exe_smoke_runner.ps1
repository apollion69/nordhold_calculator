param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][int]$Port,
  [Parameter(Mandatory=$true)][string]$LauncherOutLogPath,
  [Parameter(Mandatory=$true)][string]$LauncherErrLogPath,
  [Parameter(Mandatory=$true)][string]$SmokeLogPath,
  [Parameter(Mandatory=$true)][string]$EndpointsJsonPath
)

$ErrorActionPreference = "Stop"
$baseUrl = "http://127.0.0.1:$Port"
$proc = $null

function Write-SmokeLog {
  param([string]$Message)
  Add-Content -Path $SmokeLogPath -Value "$(Get-Date -Format o) $Message"
}

function Get-Endpoint {
  param([string]$Path)

  try {
    $resp = Invoke-WebRequest -Uri "$baseUrl$Path" -UseBasicParsing -TimeoutSec 5
    return [ordered]@{
      path = $Path
      status = [int]$resp.StatusCode
      body = [string]$resp.Content
      ok = ([int]$resp.StatusCode -eq 200)
    }
  }
  catch {
    $status = 0
    $body = $_.Exception.Message
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
      $status = [int]$_.Exception.Response.StatusCode.value__
    }
    return [ordered]@{
      path = $Path
      status = $status
      body = [string]$body
      ok = $false
    }
  }
}

try {
  Write-SmokeLog "Starting launcher: $ExePath --host 127.0.0.1 --port $Port --no-browser"
  $proc = Start-Process -FilePath $ExePath -ArgumentList @("--host", "127.0.0.1", "--port", "$Port", "--no-browser") -PassThru -RedirectStandardOutput $LauncherOutLogPath -RedirectStandardError $LauncherErrLogPath

  $healthy = $false
  for ($i = 0; $i -lt 120; $i++) {
    try {
      $health = Invoke-RestMethod -Method Get -Uri "$baseUrl/health" -TimeoutSec 2
      if ($health.status -eq "ok") {
        $healthy = $true
        break
      }
    }
    catch {
      # wait and retry
    }
    Start-Sleep -Milliseconds 250
  }

  if (-not $healthy) {
    throw "Health check did not reach ok at $baseUrl/health"
  }

  $results = @(
    (Get-Endpoint -Path "/health"),
    (Get-Endpoint -Path "/api/v1/live/status"),
    (Get-Endpoint -Path "/api/v1/live/snapshot")
  )

  $allOk = ($results | Where-Object { -not $_.ok }).Count -eq 0
  $payload = [ordered]@{
    checked_at = (Get-Date).ToString("o")
    base_url = $baseUrl
    port = $Port
    launcher_pid = if ($proc) { [int]$proc.Id } else { 0 }
    all_ok = [bool]$allOk
    endpoints = $results
  }

  $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $EndpointsJsonPath -Encoding UTF8
  Write-SmokeLog ("Smoke complete. all_ok={0}" -f $allOk)

  if (-not $allOk) {
    exit 1
  }

  exit 0
}
finally {
  if ($proc -and -not $proc.HasExited) {
    try {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
      Write-SmokeLog ("Stopped launcher PID={0}" -f $proc.Id)
    }
    catch {
      Write-SmokeLog ("Failed to stop launcher PID={0}: {1}" -f $proc.Id, $_.Exception.Message)
    }
  }
}
