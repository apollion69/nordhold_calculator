# T56 Memory Soak Run Log

## Todo
- [x] Run memory precheck on port 8018 and save JSON
- [x] Confirm precheck state: mode=memory, reason=ok, memory_connected=true
- [x] Run full soak for 1800s with poll 1000ms on port 8018 (started)
- [ ] Verify new summary JSON was created for this run (missing)
- [x] Save current partial report with timestamps, command, and metrics

## Done
- [x] Created run directory and initialized artifacts
- [x] Copied `precheck_memory_mode.ps1` into run directory
- [x] Precheck completed with `precheck_pass=true` and required memory-mode state on port 8018
- [x] Started full soak command: `powershell.exe -ExecutionPolicy Bypass -File scripts/run_nordhold_live_soak.ps1 -DurationS 1800 -PollMs 1000 -Port 8018`
- [x] Collected partial outcome after user stop and wrote `PARTIAL_REPORT.json` + `PARTIAL_REPORT.md`

## Runtime Notes
- Soak start (UTC):
  - `2026-02-26T18:26:52Z`
- Partial capture (UTC):
  - `2026-02-26T18:54:24Z`
- Elapsed at capture:
  - `1652s`
- Blocker:
  - `run interrupted by user before 1800s completion; summary.json was not generated`
