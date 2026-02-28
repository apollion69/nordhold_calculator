# T36 Live Session Prep

Date: 2026-02-26
Owner: codex

## Todo
- [x] Add frontend live connection form for all connect payload fields.
- [x] Add calibration candidates loader and candidate select binding.
- [x] Add optional auto-reconnect loop while mode is not memory.
- [x] Update API route contract test for calibration candidates endpoint.
- [x] Update README and RUNBOOK for operator flow.
- [x] Run backend tests + frontend build and store artifacts.

## Done
- [x] Updated frontend files:
  - `web/src/App.tsx`
  - `web/src/types.ts`
  - `web/src/styles.css`
- [x] Updated contract/docs:
  - `tests/test_api_contract.py`
  - `README.md`
  - `RUNBOOK.md`
- [x] Validation:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> `17 OK` (`2 skipped`)
  - `cd web && npm run build` -> `vite build OK`
- [x] Artifacts:
  - `artifacts/20260226_111748-python-tests.log`
  - `artifacts/20260226_111748-web-build.log`
  - `artifacts/20260226_112055-windows-api-contract.log`
