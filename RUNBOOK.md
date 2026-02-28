# Nordhold Realtime Runbook

## Live bridge modes
- `memory`: process is reachable and signature profile is active.
- `replay`: memory path unavailable, replay session is used.
- `degraded`: neither memory nor replay is available.
- `synthetic`: internal safe fallback for API continuity.

## Frontend live-connect flow
### Connect form fields (`POST /api/v1/live/connect`)
- `process_name` (default `NordHold.exe`)
- `poll_ms`
- `require_admin`
- `dataset_version` (optional)
- `replay_session_id` (optional)
- `signature_profile_id` (optional)
- `calibration_candidates_path` (optional)
- `calibration_candidate_id` (optional)

### Load calibration candidates
1. Enter `calibration_candidates_path` in connect form.
2. Call `GET /api/v1/live/calibration/candidates?path=<value>`.
3. Use returned `candidate_ids`/`candidates` to choose `calibration_candidate_id`.
4. Run connect with selected candidate.

### Auto-reconnect behavior
- Preferred state API is `GET /api/v1/run/state` with stream updates from `GET /api/v1/events`.
- Backward-compatible polling remains available via:
  - `GET /api/v1/live/status`
  - `GET /api/v1/live/snapshot`
- If backend or live bridge is temporarily unavailable, frontend retries `POST /api/v1/live/connect` with the last submitted connect payload.

## Signature profile update flow (after game patch)
1. Check installed build id from Steam app manifest.
2. Add new entry to `data/versions/index.json`.
3. Create folder `data/versions/<dataset>/`.
4. Add:
   - `catalog.json`
   - `memory_signatures.json`
   - `changelog.md`
5. Switch `active_version` to the new dataset only after validation.

## `memory_signatures.json` schema (Live memory v1)
- Set `schema_version` to `live_memory_v1`.
- Keep at least one profile in `profiles[]` with:
  - `id`, `process_name`, `module_name`, `poll_ms`, `required_admin`, `fields`.
  - optional `pointer_size` (`4` or `8`) for explicit pointer-chain width.
- In `fields` keep required keys:
  - `current_wave`
  - `gold`
  - `essence`
- Allowed field sources only:
  - `address`
  - `pointer_chain`
- Placeholder signatures must be explicit:
  - `address: "0x0"`
  - `unresolved: true`
  - optional profile-level `resolution_status: "unresolved"`

## Validation checklist
- `POST /api/v1/live/autoconnect` accepts default payload and returns live status.
- `GET /api/v1/dataset/version` returns active dataset metadata.
- `GET /api/v1/dataset/catalog` returns dataset + catalog payload.
- `GET /api/v1/run/state` returns aggregated runtime state.
- `GET /api/v1/events?limit=1` returns SSE status/heartbeat payload.
- `GET /api/v1/live/status` (legacy) returns expected mode.
- `GET /api/v1/live/calibration/candidates?path=...` returns candidate list for the selected calibration file.
- `POST /api/v1/timeline/evaluate` returns wave results for all waves.
- `POST /api/v1/replay/import` works for both json and csv payloads.
- Golden test output matches `runtime/golden/expected_wave_eval.json`.

## Live soak procedure
Run long stability check (default port `8013`, poll `1000 ms`):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_nordhold_live_soak.ps1 -DurationS 1800 -PollMs 1000
```

Expected summary output:
- `runtime\logs\nordhold-live-soak-*.summary.json`
- key fields:
  - `endpoint_cycle_failures`
  - `status_not_memory_count`
  - `memory_connected_false_count`
  - `max_cycle_latency_ms`

Stop the soak loop explicitly if needed:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_nordhold_live_soak.ps1 -Port 8013
```

## Troubleshooting
### Live mode stuck in degraded
- Ensure game process name matches `NordHold.exe`.
- Re-run bridge with admin privileges if required.
- Provide replay session id as fallback.

### EXE launcher mode
- Build executable:
  - `powershell -ExecutionPolicy Bypass -File .\scripts\build_nordhold_realtime_exe.ps1`
- Run executable:
  - `runtime\dist\NordholdRealtimeLauncher\NordholdRealtimeLauncher.exe`
- Runtime flags:
  - `--no-browser`
  - `--host 127.0.0.1`
  - `--port 8000`
- Quick smoke check:
  - open `http://127.0.0.1:8000/health` and verify `{"status":"ok"}`.

### Wrong wave numbers in live snapshot
- Verify signature offsets for current build.
- Confirm `memory_signatures.json` profile id and path in `index.json`.

### Calibration candidates do not load
- Verify `calibration_candidates_path` points to an existing JSON file.
- Check `GET /api/v1/live/calibration/candidates?path=...` response for parser errors.
- Check `GET /api/v1/run/state` for current `reason` and source provenance (legacy fallback: `GET /api/v1/live/status`).
- If IDs are present but connect still degrades, retry with empty `calibration_candidate_id` to use active/default candidate.

### Monte-Carlo is too slow
- Lower `monte_carlo_runs` for interactive profile.
- Use `expected` mode for planning, keep `monte_carlo` for final checks.
