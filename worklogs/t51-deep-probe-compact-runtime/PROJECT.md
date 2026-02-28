# PROJECT: T51 Deep-Probe Compact Runtime

## Context
- Goal: continue autonomous deep-extract in active live session and remove oversized probe artifact risk.
- Owner: codex
- Started: 2026-02-26
- Run id: `nordhold-t51-deep-probe-compact-20260226_152011`

## TODO
- [x] Switch deep probe report default to compact mode (no full per-tick samples by default).
- [x] Rework long-probe launcher script for timestamped artifact directories.
- [x] Add early process-existence guard for `NordHold.exe`.
- [x] Validate script + tests for deep-probe/promotion pipeline.
- [x] Re-run API connect check and capture degraded reason when game process is absent.

## Done
- Updated deep probe CLI (`scripts/nordhold_combat_deep_probe.py`):
  - added `--include-samples` flag;
  - default report is compact (`samples_included=false`, `samples=[]`, `sample_count=0`);
  - prevents multi-hundred-MB JSON growth during long runs.
- Updated launcher helper (`worklogs/t47-signature-profile-fallback/start_long_deep_probe.ps1`):
  - adds parameters `DurationS` and `IncludeSamples`;
  - creates per-run artifact directory with timestamp;
  - auto-selects latest `memory_calibration_candidates_autoload.json` from artifacts;
  - fails fast with clear error if `NordHold.exe` is not running;
  - returns `run_id`, `artifact_dir`, `candidates`, `game_pid`.
- Validation:
  - `PYTHONPATH=src python3 -m py_compile scripts/nordhold_combat_deep_probe.py scripts/nordhold_promote_deep_probe_candidates.py tests/test_promote_deep_probe_candidates.py` -> `OK`
  - `PYTHONPATH=src python3 -m unittest -v tests.test_promote_deep_probe_candidates tests.test_memory_scan_cli` -> `3 tests`, `OK`
- Live checks:
  - compact probe start attempt now returns deterministic preflight failure when game is missing:
    - `NordHold.exe is not running. Start the game and rerun deep probe.`
  - API reconnect check confirms deterministic degraded behavior in this state:
    - `reason=memory_unavailable_no_replay`.
  - game process was launched from installed path:
    - `C:\Program Files (x86)\Steam\steamapps\common\Nordhold\NordHold.exe`
  - compact probe run completed successfully:
    - run id: `nordhold-combat-deep-probe-20260226_152414`,
    - report size stayed compact (`~1.1 KB`, `samples_included=false`),
    - selected optional fields were empty in this idle combat state (no dynamic candidate promoted).
  - promotion from compact report executed:
    - generated fresh `memory_calibration_candidates_autoload.json` in the same run folder,
    - live reconnect with empty calibration path auto-selected this latest file and returned:
      - `mode=memory`,
      - `reason=ok`.
  - started long background compact extraction run:
    - `run_id=nordhold-combat-deep-probe-20260226_152912`,
    - `pid=11388`,
    - expected output report:
      - `.../artifacts/nordhold-combat-deep-probe-20260226_152912/combat_deep_probe_long_report.json`.
  - swarm follow-up completed:
    - diagnostics note created:
      - `diagnostics_long_probe.md`,
    - run `152912` verified complete but without optional combat promotion (`selected_meta={}`),
    - autonomous worker reran full flow on:
      - `run_id=nordhold-combat-deep-probe-20260226_154010`,
    - this rerun completed end-to-end:
      - `probe -> promote -> reconnect -> snapshot capture`,
    - final live mode after rerun:
      - `mode=memory`,
      - `reason=ok`,
      - calibration autoload path points to run-local artifact.

## Artifacts
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-t51-deep-probe-compact-20260226_152011/py_compile.log`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-t51-deep-probe-compact-20260226_152011/targeted_tests.log`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-t51-deep-probe-compact-20260226_152011/memory_calibration_candidates_promoted.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_151425/combat_deep_probe_long.stderr.log`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_152414/combat_deep_probe_long_report.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_152414/combat_deep_probe_long.stdout.log`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_152414/memory_calibration_candidates_autoload.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_152414/live_connect_after_compact_probe.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_152414/live_snapshot_after_compact_probe.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_152912/combat_deep_probe_long.pid`
- `codex/projects/nordhold/worklogs/t51-deep-probe-compact-runtime/diagnostics_long_probe.md`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_154010/combat_deep_probe_long_report.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_154010/memory_calibration_candidates_autoload.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_154010/live_connect_after_long_probe.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_154010/live_status_after_long_probe.json`
- `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_154010/live_snapshot_after_long_probe.json`
