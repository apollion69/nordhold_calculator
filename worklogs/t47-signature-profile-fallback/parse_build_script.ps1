$ErrorActionPreference = "Stop"
$path = "C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\scripts\build_nordhold_realtime_exe.ps1"
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors -and $errors.Count -gt 0) {
  $errors | ForEach-Object { $_.ToString() }
  exit 1
}
"PS_PARSE_OK"
