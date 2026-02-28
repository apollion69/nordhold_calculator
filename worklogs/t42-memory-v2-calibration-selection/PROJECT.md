# T42 Nordhold Memory v2 + Calibration Selection

## TODO
- [x] Add `live_memory_v2` compatibility in memory schema parsing while preserving `live_memory_v1`.
- [x] Define combat field sets (required + optional) for calibration/scoring.
- [x] Implement deterministic candidate recommendation/scoring and expose recommendation metadata.
- [x] Extend candidate summaries/inspection with `candidate_quality` and `recommended_candidate_id` support data.
- [x] Extend scanner `build-calibration-candidates` command with extra combat-field meta paths and v2 payload metadata.
- [x] Update `data/versions/1.0.0/memory_signatures.json` to compatible v2 schema.
- [x] Add/update targeted tests in Nordhold backend for schema compatibility and candidate scoring.
- [x] Run targeted tests and capture commands/results.

## Done
- [x] Synced canonical context (`AGENTS.md` -> `DECISIONS.md`) before changes.
- [x] Added task lock in canonical tracker: `TASKS.md` -> `T42 in_progress owner=codex`.
- [x] Created dedicated worklog folder and project tracker file for this task.
- [x] Updated core modules:
  - `src/nordhold/realtime/memory_reader.py`
  - `src/nordhold/realtime/calibration_candidates.py`
  - `src/nordhold/realtime/live_bridge.py` (inspection response support fields)
  - `scripts/nordhold_memory_scan.py` (build-calibration-candidates related sections)
  - `data/versions/1.0.0/memory_signatures.json`
- [x] Added/updated tests:
  - `tests/test_live_memory_v1.py`
  - `tests/test_memory_scan_cli.py` (new)
- [x] Validation run_id: `nordhold-t42-memory-v2-20260226_125554`
  - `PYTHONPATH=src python3 -m py_compile src/nordhold/realtime/memory_reader.py src/nordhold/realtime/calibration_candidates.py scripts/nordhold_memory_scan.py tests/test_live_memory_v1.py tests/test_memory_scan_cli.py tests/test_replay_live.py`
  - `PYTHONPATH=src python3 -m unittest -v tests.test_live_memory_v1 tests.test_memory_scan_cli tests.test_replay_live`
  - Result: `Ran 26 tests`, `OK (skipped=2)`
  - Logs:
    - `worklogs/t42-memory-v2-calibration-selection/artifacts/nordhold-t42-memory-v2-20260226_125554/py_compile.log`
    - `worklogs/t42-memory-v2-calibration-selection/artifacts/nordhold-t42-memory-v2-20260226_125554/targeted_tests.log`
