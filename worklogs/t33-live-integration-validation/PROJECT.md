# T33 Nordhold Live Integration Validation

## TODO
- [x] Lock task in root `TASKS.md` as `T33 in_progress`.
- [x] Verify `NordHold.exe` process is running on host.
- [x] Cleanly restart backend via `scripts/stop_nordhold_realtime.ps1` + `scripts/start_nordhold_realtime.ps1 -NoBrowser`.
- [x] Run API chain: `/health`, `/api/v1/live/connect`, `/api/v1/live/status`, `/api/v1/live/snapshot`.
- [x] Build calibration candidates JSON from existing scan/worklog artifacts and retry `live/connect`.
- [x] If still degraded, run scanner narrowing for at least one field and retry connect.
- [x] Save exact commands, payloads, and responses in this worklog artifact set.
- [x] Update root `STATUS.md` and `TASKS.md` after final state.

## Done
- 2026-02-26 00:32 MSK: Created T33 task lock in root `TASKS.md`.
- 2026-02-26 00:24-00:30 MSK: Confirmed host process `NordHold.exe` is running and restarted backend with `start_nordhold_realtime.ps1 -NoBrowser`.
- 2026-02-26 00:31 MSK: Baseline API chain executed; live mode remained `degraded` (`reason=memory_unavailable_no_replay`), snapshot source `synthetic`.
- 2026-02-26 00:32 MSK: Built `artifacts/memory_calibration_candidates_from_t32.json` from `T32` scan outputs and retried live connect.
- 2026-02-26 00:33-00:37 MSK: Achieved stable memory mode with candidate `artifact_combo_1`:
  - `/api/v1/live/connect` -> `status=connected`, `mode=memory`,
  - `/api/v1/live/status` -> `memory_connected=true`,
  - `/api/v1/live/snapshot` -> `wave=3`, `gold=99`, `essence=9`.
- 2026-02-26 00:39 MSK: Hardened `scripts/stop_nordhold_realtime.ps1` and revalidated restart loop:
  - stop now kills both uvicorn PIDs (`python.exe` + `python3.11.exe`),
  - listener `127.0.0.1:8000` goes absent before next start,
  - reconnect with `artifact_combo_1` returns stable `mode=memory`.
- 2026-02-26 00:40 MSK: Root sync updated (`TASKS.md`, `STATUS.md`) and stop-script hardening applied.

## Notes
- Scope path: `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold`
- Worklog artifacts path: `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t33-live-integration-validation/artifacts`
