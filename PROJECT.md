# Nordhold Realtime Damage Calculator

Date: 2026-02-25
Owner: codex

## TODO
- [x] Set canonical task lock in `TASKS.md` (`T30`, `in_progress`, owner=`codex`).
- [x] Canonicalize project structure and define source-of-truth paths.
- [x] Implement versioned wave-simulation data model with provenance.
- [x] Implement simulation engine modes: `expected`, `combat`, `monte_carlo`.
- [x] Implement local bridge (`/live/*`, replay import/fallback, extract stubs).
- [x] Implement API v1 endpoints for timeline and analytics.
- [x] Add web frontend scaffold (React + TypeScript + worker) and launcher.
- [x] Add unit/simulation/golden/api tests.
- [x] Add runbook/docs for runtime modes and patch signature updates.
- [x] Update `STATUS.md` and `DECISIONS.md` with implementation outcome.

## DONE
- [x] Confirmed source-of-truth target: `codex/projects/nordhold`.
- [x] Confirmed local game install available for bridge work (`Steam appid 3028310`, IL2CPP layout present).
- [x] Added `data/versions` layout with active dataset, changelog and memory signature profile stub.
- [x] Added realtime domain package `src/nordhold/realtime/*`:
  - catalog loader,
  - timeline simulation engine,
  - analytics helpers,
  - live bridge state machine,
  - replay import/store.
- [x] Extended `src/nordhold/api.py` with full `/api/v1/*` surface:
  - live connect/status/snapshot,
  - replay import,
  - timeline evaluate,
  - compare/sensitivity/forecast analytics.
- [x] Added `web/` frontend scaffold (React + TypeScript + worker) for realtime planner and dashboards.
- [x] Added launcher script: `scripts/start_nordhold_realtime.ps1`.
- [x] Hardened launcher to auto-build `web/dist`:
  - uses Windows `npm` when available,
  - falls back to `wsl.exe` build path when Windows `npm` is absent.
- [x] Added test suite and fixtures:
  - `tests/test_realtime_engine.py`,
  - `tests/test_replay_live.py`,
  - `tests/test_golden_regression.py`,
  - `tests/test_api_contract.py`,
  - `runtime/golden/input_wave_eval.json`,
  - `runtime/golden/expected_wave_eval.json`.
- [x] Final verification:
  - backend tests `6/6 OK`,
  - frontend production build `OK`,
  - API smoke passed for all `/api/v1/*` endpoints.

## DONE (T31 Live Memory v1)
- [x] Added profile-driven memory reader module:
  - `src/nordhold/realtime/memory_reader.py`
  - supports `address` and `pointer_chain` field sources,
  - typed reads: `int32`, `uint32`, `float32`, `float64`,
  - profile-level `pointer_size` override (`4|8`).
- [x] Integrated memory reader into `LiveBridge` with safe fallback:
  - memory connect validation on `connect`,
  - degrade on read/connect errors with stable replay/synthetic behavior.
- [x] Extended API live connect payload:
  - optional `signature_profile_id` in `/api/v1/live/connect`.
- [x] Upgraded signature data format:
  - `data/versions/1.0.0/memory_signatures.json` -> `schema_version: live_memory_v1`.
- [x] Added tests:
  - `tests/test_live_memory_v1.py`,
  - extended `tests/test_replay_live.py` for memory snapshot failure fallback.
- [x] Verification:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> `11 OK` (`1 skipped`),
  - `C:\\Users\\lenovo\\Documents\\cursor\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v` -> `11 OK`.

## DONE (T32/T33 Live Calibration + Integration)
- [x] Ran live memory scan/narrow workflow against running `NordHold.exe`.
- [x] Saved calibration artifacts:
  - `worklogs/t32-live-memory-calibration/artifacts/20260226_live/*`.
- [x] Built calibration candidate overlay:
  - `worklogs/t33-live-integration-validation/artifacts/memory_calibration_candidates_from_t32.json`.
- [x] Verified live bridge connection with calibrated candidate (`artifact_combo_1`):
  - `/api/v1/live/connect` -> `status=connected`, `mode=memory`,
  - `/api/v1/live/snapshot` -> `wave=3`, `gold=99`, `essence=9`, `source_mode=memory`.
- [x] Re-ran test suites:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> `14 OK` (`1 skipped`),
  - `C:\\Users\\lenovo\\Documents\\cursor\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v` -> `14 OK`.
- [x] Hardened shutdown script:
  - `scripts/stop_nordhold_realtime.ps1` now matches `python.exe` + `python3*.exe` uvicorn workers.
  - validated: `stop` removes listener `127.0.0.1:8000` before restart.

## DONE (T34 Frontend Realtime UX)
- [x] Added 1-second live snapshot polling in frontend for:
  - `GET /api/v1/live/status`,
  - `GET /api/v1/live/snapshot`.
- [x] Added dedicated live cards in wave dashboard:
  - `wave`, `gold`, `essence`, `source_mode`.
- [x] Replaced actions-only flow with interactive timeline actions editor:
  - add/remove/edit rows for `wave`, `at_s`, `type`, `target_id`, `value`, `payload JSON`,
  - kept synchronized raw JSON textarea for power users.
- [x] Added per-wave table with expandable breakdown:
  - columns: `potential`, `combat`, `dps`, `clear`, `leaks`,
  - live wave marker highlights plan-vs-live both in table and in bar chart.
- [x] Updated mobile layout rules in `web/src/styles.css` for new editor/table blocks.
- [x] Build verification:
  - `cd web && npm run build` -> `OK` (`vite build`),
  - artifact: `worklogs/t34-frontend-realtime-ux/artifacts/20260226_1103-web-build.log`.

## DONE (T34 Backend Calibration Automation)
- [x] Added scanner subcommand:
  - `scripts/nordhold_memory_scan.py build-calibration-candidates`
  - input flags:
    - `--current-wave-meta`,
    - `--gold-meta`,
    - `--essence-meta`,
    - `--out`.
- [x] Added calibration helper module:
  - `src/nordhold/realtime/calibration_candidates.py`:
    - snapshot -> candidate generation,
    - candidate summary parsing for API/diagnostics.
- [x] Extended live diagnostics:
  - `src/nordhold/realtime/live_bridge.py` now exposes:
    - `required_field_resolution`,
    - `calibration_candidate_ids`,
    - `last_memory_values`,
    - `last_error`.
- [x] Added calibration inspection endpoint:
  - `GET /api/v1/live/calibration/candidates?path=...`.
- [x] Targeted verification:
  - `PYTHONPATH=src python3 -m unittest -v tests.test_live_memory_v1 tests.test_replay_live` -> `OK`.

## DONE (T35 Engine Regression + Golden Hardening)
- [x] Added deterministic runtime-action combat test:
  - `tests/test_realtime_engine.py`.
- [x] Added monte-carlo determinism/aggregation test:
  - `tests/test_realtime_engine.py`.
- [x] Extended golden regression harness to all fixtures:
  - `tests/test_golden_regression.py` now validates `runtime/golden/input_*.json`.
- [x] Added new golden fixtures:
  - `input_combat_runtime_actions.json` + `expected_combat_runtime_actions.json`,
  - `input_monte_carlo_seeded.json` + `expected_monte_carlo_seeded.json`.
- [x] Added cross-runtime float stabilization for byte-level golden parity:
  - `src/nordhold/realtime/models.py` (`EvaluationResult.to_dict` normalization).
- [x] Full verification:
  - Linux: `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> `17 OK` (`2 skipped`),
  - Windows: `C:\\Users\\lenovo\\Documents\\cursor\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v` -> `17 OK`.

## DONE (T36 Live Connect UX + Auto-Reconnect Prep)
- [x] Added UI-first live connection controls in `web/src/App.tsx`:
  - process/admin/poll controls,
  - optional dataset/profile/replay/calibration fields.
- [x] Added candidate loading flow:
  - `Load Candidates` calls `GET /api/v1/live/calibration/candidates?path=...`,
  - candidate select syncs to `calibration_candidate_id`.
- [x] Added connect action:
  - `Connect Live` posts payload to `POST /api/v1/live/connect`.
- [x] Added bounded auto-reconnect loop:
  - retries connect by interval while live mode is not `memory`.
- [x] Extended frontend type contracts:
  - `LiveConnectRequest`,
  - `LiveCalibrationCandidatesResponse`,
  - `LiveStatus.calibration_candidate_ids`.
- [x] Synced docs/contracts:
  - `tests/test_api_contract.py` includes `/api/v1/live/calibration/candidates`,
  - `README.md` and `RUNBOOK.md` document connect + candidates + auto-reconnect flow.
- [x] Validation:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> `17 OK` (`2 skipped`),
  - `C:\\Users\\lenovo\\Documents\\cursor\\.venv\\Scripts\\python.exe -m unittest -v tests.test_api_contract` -> `1 OK`,
  - `cd web && npm run build` -> `OK`.
- [x] Artifacts:
  - `worklogs/t36-live-session-prep/artifacts/20260226_111748-python-tests.log`,
  - `worklogs/t36-live-session-prep/artifacts/20260226_111748-web-build.log`,
  - `worklogs/t36-live-session-prep/artifacts/20260226_112055-windows-api-contract.log`.

## DONE (T37 Windows EXE Packaging)
- [x] Added Windows launcher entrypoint:
  - `src/nordhold/launcher.py`.
- [x] Added bundled runtime path resolution in API:
  - `src/nordhold/api.py` now supports:
    - `NORDHOLD_PROJECT_ROOT`,
    - `NORDHOLD_WEB_DIST`,
    - frozen path probing for EXE mode.
- [x] Added EXE build pipeline:
  - `scripts/build_nordhold_realtime_exe.ps1`.
- [x] Updated docs for EXE workflow:
  - `README.md`,
  - `RUNBOOK.md`.
- [x] Built EXE artifact:
  - `runtime/dist/NordholdRealtimeLauncher/NordholdRealtimeLauncher.exe`.
- [x] EXE smoke validation:
  - launched EXE on `127.0.0.1:8012`,
  - verified `/health` -> `{\"status\":\"ok\"}`,
  - terminated process cleanly after check.
- [x] Validation:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> `17 OK` (`2 skipped`),
  - `C:\\Users\\lenovo\\Documents\\cursor\\.venv\\Scripts\\python.exe -m unittest -v tests.test_api_contract` -> `1 OK`.
- [x] Artifacts:
  - `worklogs/t37-exe-packaging/artifacts/20260226_113013-build-exe-direct.log`,
  - `worklogs/t37-exe-packaging/artifacts/20260226_113040-exe-smoke-verbose.log`,
  - `worklogs/t37-exe-packaging/artifacts/20260226_113040-exe-run.out.log`,
  - `worklogs/t37-exe-packaging/artifacts/20260226_113040-exe-run.err.log`.
