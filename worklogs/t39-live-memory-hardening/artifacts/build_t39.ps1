$ErrorActionPreference = 'Stop'
function Assert-ExternalSuccess([string]$Step) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with exit code $LASTEXITCODE"
  }
}
$projectRoot = 'C:\Users\lenovo\Documents\cursor\codex\projects\nordhold'
$py = 'C:\Users\lenovo\Documents\cursor\.venv\Scripts\python.exe'
$distRoot = Join-Path $projectRoot 'runtime\dist_t39'
$buildRoot = Join-Path $projectRoot 'runtime\build\pyinstaller_t39'
$target = Join-Path $distRoot 'NordholdRealtimeLauncher'

if (-not (Test-Path $py)) {
  throw "Python not found: $py"
}

if (Test-Path $target) {
  Remove-Item -Path $target -Recurse -Force
}

New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null

Write-Output "RUN: pip install -e"
& $py -m pip install -e $projectRoot
Assert-ExternalSuccess 'pip install -e'

Write-Output "RUN: pip install pyinstaller"
& $py -m pip install pyinstaller
Assert-ExternalSuccess 'pip install pyinstaller'

$args = @(
  '-m','PyInstaller',
  '--noconfirm',
  '--clean',
  '--name','NordholdRealtimeLauncher',
  '--distpath',$distRoot,
  '--workpath',$buildRoot,
  '--specpath',$buildRoot,
  '--paths',(Join-Path $projectRoot 'src'),
  '--collect-submodules','uvicorn',
  '--collect-submodules','fastapi',
  '--collect-submodules','pydantic',
  '--add-data',"$projectRoot\data;data",
  '--add-data',"$projectRoot\web\dist;web\dist",
  "$projectRoot\src\nordhold\launcher.py"
)
Write-Output "RUN: pyinstaller"
& $py @args
Assert-ExternalSuccess 'pyinstaller'

$exe = Join-Path $target 'NordholdRealtimeLauncher.exe'
if (-not (Test-Path $exe)) {
  throw "EXE missing: $exe"
}
Write-Output "EXE_OK $exe"
