param(
  [int]$Port = 8013,
  [switch]$StopAllLaunchers
)

$ErrorActionPreference = "Continue"

# Stop any powershell process that runs the soak script.
Get-CimInstance Win32_Process |
  Where-Object {
    ($_.Name -match "powershell(\.exe)?") -and
    ($_.CommandLine -match "run_nordhold_live_soak\.ps1")
  } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

try {
  $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($listener) {
    $pid = $listener | Select-Object -First 1 -ExpandProperty OwningProcess
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
  }
}
catch {
  # best effort
}

if ($StopAllLaunchers) {
  Get-Process -Name "NordholdRealtimeLauncher" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
}

Write-Output "soak stopped"
