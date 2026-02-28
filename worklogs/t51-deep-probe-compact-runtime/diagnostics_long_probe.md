# Diagnostics: Nordhold long probe runtime (`nordhold-combat-deep-probe-20260226_152912`)

Date: 2026-02-26
Scope: diagnostics-only check for the current/last long probe run.

## 1) Probe/process health + live status snapshot

- Probe run directory exists:
  - `codex/projects/nordhold/worklogs/t47-signature-profile-fallback/artifacts/nordhold-combat-deep-probe-20260226_152912`
- Probe PID file contains `11388`; process is no longer alive (`PID_ALIVE=0`).
- Probe finished and produced compact report/logs:
  - `combat_deep_probe_long_report.json`
  - `combat_deep_probe_long.stdout.log`
  - `combat_deep_probe_long.stderr.log` (empty)
- `stdout` summary for this run:
  - `candidate_id=artifact_combo_1`
  - `probe_address_count=9400`
  - `top_enemies_alive=` (empty)
  - `top_combat_time_s=` (empty)
  - `top_is_combat_phase=` (empty)

Current game process check (separate from probe PID):
- `NordHold.exe` is currently running (observed process id: `12000`).

Current live API check:
- No local live API responder on `127.0.0.1:8000` or `127.0.0.1:18000` at diagnostics time.
- Therefore, latest available persisted live status in t47 artifacts was used:
  - `.../nordhold-combat-deep-probe-20260226_152414/live_status_after_compact_probe.json`
  - `current_wave=3`
  - `gold=99`
  - `essence=9`
  - `enemies_alive=0`
  - `is_combat_phase=false`

## 2) t47 report comparison: do dynamic combat candidates ever appear?

Compared probe reports:
- `.../nordhold-realtime-live-debug-20260226_142333/combat_deep_probe_report.json` (30s)
- `.../nordhold-realtime-live-debug-20260226_142333/combat_deep_probe_long_report.json` (600s)
- `.../nordhold-combat-deep-probe-20260226_152414/combat_deep_probe_long_report.json` (120s)
- `.../nordhold-combat-deep-probe-20260226_152912/combat_deep_probe_long_report.json` (600s)

Result across all compared reports:
- `summary.top_enemies_alive = null`
- `summary.top_combat_time_s = null`
- `summary.top_is_combat_phase = null`
- `summary.selected_meta = {}`

Conclusion:
- In available t47 artifacts, dynamic combat candidates for `enemies_alive`, `combat_time_s`, `is_combat_phase` did not appear yet.

## 3) Practical gameplay recommendations to maximize detection

Use this play pattern during a fresh long probe:

1. Spend most of the probe inside active combat, not in menus/idle/upgrade screens.
2. Force repeated state transitions:
   - clear a wave (`enemies_alive -> 0`),
   - immediately start next combat (`enemies_alive > 0`).
3. Create long and short combat windows in one run:
   - keep enemies alive for 30-60s in some waves,
   - quick-clear other waves.
   This gives stronger variation for `combat_time_s` and `is_combat_phase` correlation.
4. Avoid stopping/restarting the game process mid-probe.
5. Keep a single stable map/session while probing; do not alt-tab pause for long periods.
6. If still unresolved, run one focused 120-180s probe while intentionally alternating:
   - 20-30s pure idle between waves,
   - 40-60s dense combat,
   repeated several times.

Expected effect:
- higher signal variance for the three target fields, improving chance that top candidates become non-null.
