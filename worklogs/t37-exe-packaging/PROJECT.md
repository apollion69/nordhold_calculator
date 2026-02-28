# T37 EXE Packaging

Date: 2026-02-26
Owner: codex

## Todo
- [x] Add Python launcher entrypoint for bundled EXE run.
- [x] Add bundled-mode project root/web dist resolution in API runtime.
- [x] Add PyInstaller build script for Windows EXE output.
- [x] Build `NordholdRealtimeLauncher.exe` and verify artifact path.
- [x] Smoke-run EXE (`/health`) and capture logs.
- [x] Update docs (`README.md`, `RUNBOOK.md`) with EXE workflow.

## Done
- [x] Added `src/nordhold/launcher.py`.
- [x] Updated `src/nordhold/api.py` for env/frozen project root + web path resolution.
- [x] Added `scripts/build_nordhold_realtime_exe.ps1`.
- [x] Built EXE artifact:
  - `runtime/dist/NordholdRealtimeLauncher/NordholdRealtimeLauncher.exe`.
- [x] EXE smoke run passed:
  - `HEALTH={"status":"ok"}` on `http://127.0.0.1:8012/health`.
- [x] Validation:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> `17 OK` (`2 skipped`)
  - `C:\Users\lenovo\Documents\cursor\.venv\Scripts\python.exe -m unittest -v tests.test_api_contract` -> `1 OK`
- [x] Key artifacts:
  - `artifacts/20260226_113013-build-exe-direct.log`
  - `artifacts/20260226_113040-exe-smoke-verbose.log`
  - `artifacts/20260226_113040-exe-run.out.log`
  - `artifacts/20260226_113040-exe-run.err.log`
