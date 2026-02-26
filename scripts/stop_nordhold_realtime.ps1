$ErrorActionPreference = "SilentlyContinue"

$uvicorn = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -match '^python([0-9]+(\.[0-9]+)?)?\.exe$' -and $_.CommandLine -match "uvicorn" -and $_.CommandLine -match "nordhold.api:app"
}

$viteNode = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq "node.exe" -and $_.CommandLine -match "vite"
}

if ($uvicorn) {
  $uvicorn | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Write-Host "Stopped backend process(es): $($uvicorn.ProcessId -join ', ')"
} else {
  Write-Host "Backend process not found."
}

if ($viteNode) {
  $viteNode | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Write-Host "Stopped frontend process(es): $($viteNode.ProcessId -join ', ')"
} else {
  Write-Host "Frontend process not found."
}
