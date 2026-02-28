# T32 Nordhold Live Memory Calibration

## TODO
- [x] Lock task in root `TASKS.md` as `T32 in_progress`.
- [x] Implement practical memory scanner for `NordHold.exe` (`int32`/`float32`).
- [x] Add snapshot narrowing workflow (`equal|changed|increased|decreased|delta`).
- [x] Run scanner on live process and collect candidate addresses for `wave/gold/essence`.
- [x] Save run artifacts and exact rerun commands.
- [x] Update root `STATUS.md` + `TASKS.md` when step is complete.

## Done
- 2026-02-26 00:04 MSK: Added `T32` lock line to root `TASKS.md`.
- 2026-02-26 00:10-00:22 MSK: Executed scanner + narrowing against live `NordHold.exe` and captured artifacts in `artifacts/20260226_live`.
- 2026-02-26 00:32 MSK: Calibration results reused by integration run (`T33`) to build working candidate overlay (`artifact_combo_1`).
- 2026-02-26 00:37 MSK: Root sync updated (`TASKS.md`, `STATUS.md`) with completed state.

## Notes
- Work scope path: `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold`
- Artifacts path: `/mnt/c/Users/lenovo/Documents/cursor/codex/projects/nordhold/worklogs/t32-live-memory-calibration/artifacts`
