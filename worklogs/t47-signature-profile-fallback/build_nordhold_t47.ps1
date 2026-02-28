$ErrorActionPreference = "Stop"
$projectRoot = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold"
$workspaceRoot = "C:\Users\lenovo\Documents\cursor"
$logPath = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\artifacts\nordhold-t47-signature-profile-fallback-20260226_140357\pyinstaller_t47.log"
function Assert-ExternalSuccess([string]$step) { if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$step failed with exit code $LASTEXITCODE" } }
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$sharedVenvPython = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython) -and (Test-Path $sharedVenvPython)) { $venvPython = $sharedVenvPython }
if (-not (Test-Path $venvPython)) { throw "Missing python venv: $venvPython" }
$webDist = Join-Path $projectRoot "web\dist\index.html"
if (-not (Test-Path $webDist)) { throw "Missing frontend dist: $webDist" }
$distRoot = Join-Path $projectRoot "runtime\dist_t47"
$buildRoot = Join-Path $projectRoot "runtime\build\pyinstaller_t47"
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$targetDistDir = Join-Path $distRoot "NordholdRealtimeLauncher"
if (Test-Path $targetDistDir) { Remove-Item -Path $targetDistDir -Recurse -Force }
& $venvPython -m pip install -q -e $projectRoot *>> $logPath
Assert-ExternalSuccess "pip install -e"
& $venvPython -m pip install -q pyinstaller *>> $logPath
Assert-ExternalSuccess "pip install pyinstaller"
$args = @(
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
& $venvPython @args *>> $logPath
Assert-ExternalSuccess "pyinstaller"
$exePath = Join-Path $targetDistDir "NordholdRealtimeLauncher.exe"
if (-not (Test-Path $exePath)) { throw "EXE missing: $exePath" }
Write-Output "EXE_PATH=$exePath"
