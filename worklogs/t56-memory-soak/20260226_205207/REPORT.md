# T56 Memory-Mode Precheck Report

- Run timestamp: `20260226_205207`
- Outcome: `PRECHECK_OK`
- Precheck pass: `true`
- Mode: `memory`
- Reason: `ok`
- Memory connected: `true`
- Long soak status: `NOT_STARTED` (requested precheck-only run)

## Commands Executed
1. `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t56-memory-soak\20260226_205207\precheck_memory_mode.ps1 -ProjectRoot C:\Users\lenovo\Documents\cursor\codex\projects\nordhold -RunDir C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\worklogs\t56-memory-soak\20260226_205207 -Port 8018 -PollMs 1000 -ProcessName NordHold.exe -DatasetVersion 1.0.0`
2. Precheck internal process check command:
   `Get-CimInstance Win32_Process -Filter "name='NordHold.exe'" | Select-Object ProcessId,Name,ExecutablePath,CommandLine`
3. Precheck internal autoconnect validation:
   `POST /api/v1/live/autoconnect` with `{process_name: NordHold.exe, poll_ms: 1000, require_admin: true, dataset_version: 1.0.0}` + polling `GET /api/v1/live/status`

## Key Results
- `NordHold.exe` process check: `process_count=1`
- Launcher health before/after precheck: `before=true`, `after=true`
- Launcher started by precheck: `false`
- Required autoconnect state: `mode=memory`, `memory_connected=true`, `reason=ok`
- Actual autoconnect result: `mode=memory`, `memory_connected=true`, `reason=ok`

## Artifacts
- Precheck command output:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_205207/00_precheck_command_output.log`
- Process check JSON:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_205207/01_process_check.json`
- Precheck result JSON:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_205207/02_precheck_result.json`
- Precheck runner script:
  `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_205207/precheck_memory_mode.ps1`
