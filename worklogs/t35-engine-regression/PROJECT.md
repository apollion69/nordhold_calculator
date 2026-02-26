# T35 Nordhold Engine Regression

## TODO
- [x] Add deterministic combat test with runtime actions.
- [x] Add deterministic monte-carlo aggregation test.
- [x] Expand golden regression harness to multiple `input_*.json` fixtures.
- [x] Add combat and monte-carlo golden fixture pairs.
- [x] Stabilize serialized numeric output for cross-runtime parity.
- [x] Rebuild expected golden files and run tests in Linux + Windows environments.

## Done
- 2026-02-26 11:00 MSK: Added regression tests in:
  - `tests/test_realtime_engine.py`
  - `tests/test_golden_regression.py`
- 2026-02-26 11:00 MSK: Added golden fixtures:
  - `runtime/golden/input_combat_runtime_actions.json`
  - `runtime/golden/expected_combat_runtime_actions.json`
  - `runtime/golden/input_monte_carlo_seeded.json`
  - `runtime/golden/expected_monte_carlo_seeded.json`
- 2026-02-26 11:10 MSK: Added deterministic float serialization in:
  - `src/nordhold/realtime/models.py`
- 2026-02-26 11:11 MSK: Full test verification:
  - Linux: `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> `17 OK` (`2 skipped`),
  - Windows: `C:\\Users\\lenovo\\Documents\\cursor\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v` -> `17 OK`.
- Artifact:
  - `artifacts/20260226_1100-targeted-regression-tests.log`.
