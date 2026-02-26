$ErrorActionPreference = "Stop"
Get-CimInstance Win32_Process -Filter "Name='NordholdRealtimeLauncher.exe'" |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
"STOP_DONE"
