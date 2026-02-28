# T39 Live Memory Hardening (Backend + Frontend)

Date: 2026-02-26
Owner: codex

## Todo
- [x] Fix bundled EXE calibration path fallback when runtime root resolves to `_internal`.
- [x] Add backend auto-discovery for omitted calibration candidates path.
- [x] Make `GET /api/v1/live/calibration/candidates` `path` query optional.
- [x] Keep backward compatibility for explicit calibration path flow.
- [x] Add/adjust backend tests for fallback/discovery behavior.
- [x] Run targeted tests and capture outputs.
- [x] Set frontend live-form session defaults (`NordHold.exe`, `1000ms`, admin on, dataset `1.0.0`).
- [x] Add frontend auto-candidate loading for one-click `Connect Live` with empty-path discovery.
- [x] Harden frontend auto-reconnect to avoid blank/unresolved payload degradation.
- [x] Keep manual live fields/controls operational.
- [x] Run frontend production build and store log.
- [x] Overwrite canonical `runtime/dist` launcher with fresh build and relaunch it.
- [x] Validate running EXE on `127.0.0.1:8000` (`/health`, live candidates route, live connect).

## Done
- [x] Updated calibration payload path resolver to support `_internal -> parent` fallback for relative paths.
- [x] Added auto-discovery of latest `memory_calibration_candidates*.json` under `project_root/worklogs` (with `_internal` parent fallback).
- [x] Updated live bridge connect flow:
  - explicit path/candidate keeps strict behavior,
  - omitted path with unresolved required fields performs implicit auto-discovery (best-effort) without breaking legacy fallback logic.
- [x] Updated API route handler to allow empty `path` and use backend auto-discovery.
- [x] Added tests:
  - `test_resolve_calibration_payload_path_falls_back_from_internal_to_parent`,
  - `test_load_calibration_payload_autodiscovers_latest_candidate_file`,
  - `test_live_bridge_autodiscovers_calibration_candidates_without_path`,
  - `test_live_calibration_candidates_route_autodiscovers_when_path_is_omitted`.
- [x] Test logs:
  - `artifacts/20260226_114540-linux-targeted-tests.log`
  - `artifacts/20260226_114540-windows-targeted-tests.log`
- [x] Updated frontend file:
  - `web/src/App.tsx`
- [x] Frontend behavior:
  - live connect defaults include dataset `1.0.0`,
  - `Connect Live` auto-loads candidates via `/api/v1/live/calibration/candidates?path=<current_or_empty>` and auto-fills `path` + `candidate`,
  - auto-reconnect reuses last healthy memory payload and skips unresolved blank reconnect payloads.
- [x] Frontend build log:
  - `artifacts/20260226_1146-web-build.log`
- [x] Built fresh EXE payload:
  - `runtime/dist_t39/NordholdRealtimeLauncher/NordholdRealtimeLauncher.exe`
  - build log: `artifacts/20260226_1158-build-exe-dist_t39.log`
- [x] Replaced canonical runtime folder and relaunched:
  - `runtime/dist/NordholdRealtimeLauncher/NordholdRealtimeLauncher.exe --host 127.0.0.1 --port 8000 --no-browser`
  - helper scripts:
    - `artifacts/rebuild_and_run_main_exe.ps1`
    - `artifacts/replace_dist_from_t39_and_run.ps1`
- [x] Added autoload calibration payload with full active candidate:
  - `artifacts/memory_calibration_candidates_autoload.json`
  - `active_candidate_id=artifact_combo_1`
- [x] Runtime verification:
  - `/api/v1/live/calibration/candidates` works without query `path`,
  - `POST /api/v1/live/connect` resolves to `default_20985960@artifact_combo_1`,
  - verified `mode=memory` and `reason=ok` in live status (`require_admin=false` runtime check).
