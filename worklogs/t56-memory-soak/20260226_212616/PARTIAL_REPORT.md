# T56 Partial Run Report

- Run dir: `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_212616`
- Capture time (UTC): `2026-02-26T18:53:59Z`
- Soak command:
  - `powershell.exe -ExecutionPolicy Bypass -File scripts/run_nordhold_live_soak.ps1 -DurationS 1800 -PollMs 1000 -Port 8018`

## Completion
- Target duration: `1800s`
- Elapsed at capture: `1627s`
- Duration reached: `false`
- Summary exists: `false`
- Expected summary path:
  - `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/runtime/logs/nordhold-live-soak-20260226_212653.summary.json`

## Precheck gate (required)
- precheck_pass: `true`
- mode: `memory`
- reason: `ok`
- memory_connected: `True`

## Current live status at capture
- mode: `degraded`
- reason: `memory_snapshot_failed:ReadProcessMemory failed: addr=0x56ad0004 size=4 read=0 winerr=299`
- memory_connected: `False`
- snapshot wave/gold/essence: `3/0.0/0.0`

## Artifacts
- precheck json:
  - `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_212616/02_precheck_result.json`
- soak stdout:
  - `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_212616/10_soak_stdout.log`
- launcher stdout:
  - `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/runtime/logs/nordhold-live-soak-20260226_212653.launcher.out.log`
- launcher stderr:
  - `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/runtime/logs/nordhold-live-soak-20260226_212653.launcher.err.log`
- current status json:
  - `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t56-memory-soak/20260226_212616/11_current_status.json`

## Blocker
- `run interrupted by user before 1800s completion; summary.json was not generated`
