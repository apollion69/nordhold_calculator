# PROJECT: T50 Deep-Probe Candidate Promotion

## Context
- Goal: add automation to promote `combat_deep_probe_*_report.json` optional-field findings into a fresh calibration candidates payload.
- Owner: codex
- Started: 2026-02-26
- Run id: `nordhold-t50-promote-deep-probe-candidates-20260226_151739`

## TODO
- [x] Add CLI script `scripts/nordhold_promote_deep_probe_candidates.py`.
- [x] Implement required/source/selected-meta merge flow and active/profile preservation.
- [x] Add unit tests for merge logic without Windows memory access.
- [x] Run targeted tests and store artifacts.

## Done
- Implemented new CLI with inputs:
  - `--probe-report`
  - `--out`
  - `--candidate-source`
  - `--active-candidate-id`
  - `--max-per-field`
  - `--max-candidates`
- Implemented promotion flow:
  - loads probe report + source candidates payload,
  - resolves required/optional field sets from source payload with defaults,
  - validates required snapshot meta paths,
  - merges optional source meta paths with `report.summary.selected_meta.*.meta_path`,
  - rebuilds candidates via `build_calibration_candidates_from_snapshots(...)`,
  - preserves `profile_id` and active candidate precedence,
  - falls back to first generated candidate when active id is missing in generated set.
- Added unit test module `tests/test_promote_deep_probe_candidates.py`.
- Saved validation logs:
  - `worklogs/t50-deep-probe-candidate-promotion/artifacts/nordhold-t50-promote-deep-probe-candidates-20260226_151739/py_compile.log`
  - `worklogs/t50-deep-probe-candidate-promotion/artifacts/nordhold-t50-promote-deep-probe-candidates-20260226_151739/targeted_tests.log`
