# T41 Nordhold Live Bridge Contract Hardening

## TODO
- [x] Add `/api/v1/live/status` contract fields: `field_coverage`, `calibration_quality`, `active_required_fields`.
- [x] Extend `/api/v1/live/snapshot` memory block extraction for combat values and stable defaults for missing optional memory fields.
- [x] Integrate calibration-layer candidate selection rule into `LiveBridge.connect`.
- [x] Preserve v1 backward compatibility for degraded/replay/synthetic behavior.
- [x] Add/update backend tests (`test_replay_live.py`, `test_api_contract.py`) for status/snapshot/connect contract.
- [x] Run targeted backend tests and capture command results.

## Done
- [x] Synced canonical context (`AGENTS.md`, `CONVENTIONS.md`, `STATUS.md`, `TASKS.md`, `DECISIONS.md`).
- [x] Locked task `T41` in `TASKS.md` as `in_progress` owner=`codex`.
- [x] Updated:
  - `src/nordhold/realtime/live_bridge.py`
  - `tests/test_replay_live.py`
  - `tests/test_api_contract.py`
- [x] Targeted validation:
  - `cd codex/projects/nordhold && PYTHONPATH=src python3 -m unittest -v tests.test_replay_live tests.test_api_contract`
    - Result: `Ran 11 tests`, `OK (skipped=4)` (`fastapi` not installed in Linux env).
  - `cd codex/projects/nordhold && /mnt/c/Users/lenovo/Documents/cursor/.venv/Scripts/python.exe -m unittest -v tests.test_replay_live tests.test_api_contract`
    - Result: `Ran 11 tests`, `OK`.
  - `cd codex/projects/nordhold && PYTHONPATH=src python3 -m py_compile src/nordhold/realtime/live_bridge.py tests/test_replay_live.py tests/test_api_contract.py`
    - Result: `OK`.
