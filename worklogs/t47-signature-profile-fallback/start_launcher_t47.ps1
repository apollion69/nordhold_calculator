$ErrorActionPreference = "Stop"
$exe = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\runtime\dist_t47\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe"
$outLog = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-t47-signature-profile-fallback-20260226_140357\launcher_t47_stdout.log"
$errLog = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-t47-signature-profile-fallback-20260226_140357\launcher_t47_stderr.log"
Get-CimInstance Win32_Process -Filter "Name='NordholdRealtimeLauncher.exe'" |
  Where-Object { $_.CommandLine -like "*--port 8010*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$proc = Start-Process -FilePath $exe -ArgumentList @("--no-browser","--port","8010") -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Start-Sleep -Seconds 2
$health = ""
try {
  $health = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8010/health").Content
} catch {
  $health = "ERR"
}
[PSCustomObject]@{
  pid = $proc.Id
  health = $health
  out_log = $outLog
  err_log = $errLog
} | ConvertTo-Json -Depth 5
