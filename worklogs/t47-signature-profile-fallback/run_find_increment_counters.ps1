$ErrorActionPreference = "Stop"
$projectRoot = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold"
$scriptPath = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t47-signature-profile-fallback\find_increment_counters.py"
$python = "C:\Users\lenovo\Documents\cursor\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$projectRoot\\src;$projectRoot"
& $python $scriptPath
