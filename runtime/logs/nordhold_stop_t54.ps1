$ErrorActionPreference = 'Continue'
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'powershell(\.exe)?' -and $_.CommandLine -match 'nordhold_t54_soak\.ps1' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

try {
  $c = Get-NetTCPConnection -LocalPort 8013 -State Listen -ErrorAction SilentlyContinue
  if ($c) {
    $pid = $c | Select-Object -First 1 -ExpandProperty OwningProcess
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
  }
} catch {}

Get-Process -Name NordholdRealtimeLauncher -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Output 'stopped'
