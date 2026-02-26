# Nordhold Realtime Damage Calculator

Offline-first realtime planner and wave simulator for Nordhold.

## What is implemented
- Versioned data catalog (`data/versions/*`) with build-aware metadata.
- Realtime simulation API (`/api/v1/*`) with modes:
  - `expected`
  - `combat`
  - `monte_carlo`
- Timeline-aware build plan model with wave actions.
- Local live bridge contract for memory/replay/synthetic modes.
- Replay import (`json/csv`) + local storage in `runtime/replays`.
- Analytics endpoints:
  - compare
  - sensitivity
  - forecast
- React + TypeScript web UI scaffold (`web/`) using worker-based evaluation.

## API endpoints (v1)
- `POST /api/v1/live/connect`
- `POST /api/v1/live/autoconnect`
- `GET /api/v1/dataset/version`
- `GET /api/v1/dataset/catalog`
- `GET /api/v1/run/state`
- `GET /api/v1/events`
- `GET /api/v1/live/calibration/candidates`
- `GET /api/v1/live/status` (legacy state endpoint)
- `GET /api/v1/live/snapshot` (legacy snapshot endpoint)
- `POST /api/v1/replay/import`
- `POST /api/v1/timeline/evaluate`
- `POST /api/v1/analytics/compare`
- `POST /api/v1/analytics/sensitivity`
- `POST /api/v1/analytics/forecast`

## Frontend live-connect flow (contract)
Connect form fields (mapped to `POST /api/v1/live/connect`):
- `process_name` (default: `NordHold.exe`)
- `poll_ms`
- `require_admin`
- `dataset_version` (optional)
- `replay_session_id` (optional)
- `signature_profile_id` (optional)
- `calibration_candidates_path` (optional)
- `calibration_candidate_id` (optional)

Load candidates in UI:
- Use `GET /api/v1/live/calibration/candidates?path=<calibration_candidates_path>`.
- Fill candidate selector from `candidate_ids`/`candidates` in response.

Connect and auto-reconnect behavior:
- UI sends `POST /api/v1/live/connect` with current form payload.
- Preferred run-state API for clients is `GET /api/v1/run/state`, with stream updates from `GET /api/v1/events`.
- Backward-compatible polling remains available via `GET /api/v1/live/status` + `GET /api/v1/live/snapshot`.
- If backend is restarted or bridge becomes unavailable, UI retries connect using the last submitted connect payload.

## Local run
### Install dependencies
```powershell
cd C:\Users\lenovo\Documents\cursor\codex\projects\nordhold
python -m pip install -e .
cd .\web
npm install
```

### Backend
```powershell
cd C:\Users\lenovo\Documents\cursor\codex\projects\nordhold
python -m uvicorn nordhold.api:app --app-dir src --host 127.0.0.1 --port 8000
```

### Frontend
```powershell
cd C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\web
npm install
npm run dev
```

### One-command launcher
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_nordhold_realtime.ps1
```

This launcher auto-bootstraps:
- local `.venv` (if missing),
- Python dependencies (`fastapi`, `uvicorn`, project package),
- frontend build if `web/dist` is missing (`npm` on Windows, or `wsl.exe` fallback),
- starts backend and serves UI from `web/dist` directly at `http://127.0.0.1:8000`.

### Stop services
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_nordhold_realtime.ps1
```

### Live soak (stability/perf)
Run a bounded live API soak loop (autoconnect + status/snapshot/run-state/events):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_nordhold_live_soak.ps1 -DurationS 1800 -PollMs 1000
```

Stop soak loop (and launcher on the same port):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_nordhold_live_soak.ps1 -Port 8013
```

Summary JSON is written to `runtime\logs\nordhold-live-soak-*.summary.json`.

## Windows EXE build/run
### Build EXE
```powershell
cd C:\Users\lenovo\Documents\cursor\codex\projects\nordhold
powershell -ExecutionPolicy Bypass -File .\scripts\build_nordhold_realtime_exe.ps1
```

Expected output binary:
- `runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe`

### Run EXE
```powershell
cd C:\Users\lenovo\Documents\cursor\codex\projects\nordhold\runtime\dist\NordholdRealtimeLauncher
.\NordholdRealtimeLauncher.exe
```

Optional flags:
- `--no-browser`
- `--host 127.0.0.1`
- `--port 8000`
- `--log-level info`

## Data directories
- `data/versions/*` - datasets, changelog, signature profiles.
- `runtime/snapshots` - live snapshots.
- `runtime/replays` - imported replay sessions.
- `runtime/golden` - golden test fixtures.

## Memory signatures format (Live memory v1)
- `memory_signatures.json` must declare `schema_version: "live_memory_v1"`.
- Top-level keys: `build_id`, `process_name`, `profiles[]`.
- Profile keys: `id`, `process_name`, `module_name`, `poll_ms`, `required_admin`, `fields`.
- Optional profile key: `pointer_size` (`4` or `8`) to force pointer-chain width for target build.
- Required fields for live snapshot: `current_wave`, `gold`, `essence`.
- Field `source` must be one of:
  - `address`: direct value address via `address` (+ optional `relative_to_module`).
  - `pointer_chain`: base `address` + `offsets[]` (+ optional `relative_to_module`).
- For unresolved placeholders use explicit marker `unresolved: true` and keep `address: "0x0"` until resolved.

## Notes
- Memory-read adapter is intentionally read-only and signature-profile based.
- If memory signatures are missing/broken for current build, API stays operational via replay fallback mode.
