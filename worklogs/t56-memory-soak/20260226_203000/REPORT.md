# T56 Memory-Mode Acceptance Run Report

- Run timestamp: `20260226_203000`
- Outcome: `BLOCKER`
- Blocker reason: `process_found_but_admin_required`
- Soak run (`-DurationS 1800`) status: `NOT_STARTED` (precheck degraded)

## Commands Executed
1. `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t56-memory-soak\20260226_203000\precheck_memory_mode.ps1 -ProjectRoot C:\Users\lenovo\Documents\cursor\codex\projects\nordhold -RunDir C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t56-memory-soak\20260226_203000 -Port 8013 -PollMs 1000 -ProcessName NordHold.exe -DatasetVersion 1.0.0`
2. Precheck internal process check command:
   `Get-CimInstance Win32_Process -Filter "name='NordHold.exe'" | Select-Object ProcessId,Name,ExecutablePath,CommandLine`
3. Precheck internal launcher start (executed because `/health` was not ready):
   `NordholdRealtimeLauncher.exe --host 127.0.0.1 --port 8013 --no-browser`
4. Precheck internal autoconnect validation:
   `POST /api/v1/live/autoconnect` with `{process_name: NordHold.exe, poll_ms: 1000, require_admin: true, dataset_version: 1.0.0}` + polling `GET /api/v1/live/status`
5. Targeted diagnostic attempt (single retry, as required):
   one more `POST /api/v1/live/autoconnect` + `GET /api/v1/live/status` + `GET /api/v1/run/state`

## Key Results
- `NordHold.exe` process check: `process_count=1` (running)
- Launcher precheck: started, `pid=22012`
- Required autoconnect state expected: `mode=memory`, `memory_connected=true`, `reason=ok`
- Actual autoconnect result: `mode=degraded`, `memory_connected=false`, `reason=process_found_but_admin_required`
- Diagnostic retry result: unchanged (`degraded`, `process_found_but_admin_required`, `memory_connected=false`)

## Requested Soak Metrics
- Summary JSON: `N/A` (full soak not executed due precheck blocker)
- `endpoint_cycle_failures`: `N/A`
- `status_not_memory_count`: `N/A`
- `memory_connected_false_count`: `N/A`
- `last_mode`: `N/A`
- `last_reason`: `N/A`
- `max_cycle_latency_ms`: `N/A`
- Autoconnect block indicates `memory_connected=true`: `NO` (`false`)

## Artifacts
- Precheck command output:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_203000/00_precheck_command_output.log`
- Process check JSON:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_203000/01_process_check.json`
- Precheck result JSON:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_203000/02_precheck_result.json`
- Diagnostic attempt JSON:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_203000/03_diagnostic_attempt.json`
- Precheck runner script:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_203000/precheck_memory_mode.ps1`
- Launcher stdout log (precheck start):
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/runtime/logs/t56-precheck-20260226_203124.launcher.out.log`
- Launcher stderr log (precheck start):
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/runtime/logs/t56-precheck-20260226_203124.launcher.err.log`
