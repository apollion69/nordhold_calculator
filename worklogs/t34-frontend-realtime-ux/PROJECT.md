# T34 Nordhold Frontend Realtime UX

## TODO
- [x] Poll `/api/v1/live/status` and `/api/v1/live/snapshot` every 1 second.
- [x] Add dedicated live cards for `wave/gold/essence/source_mode`.
- [x] Implement interactive timeline row editor (`wave/at_s/type/target/value/payload`) with add/remove.
- [x] Keep raw JSON actions textarea synchronized with editor state.
- [x] Add per-wave table with expandable breakdown and live-wave marker.
- [x] Keep responsive behavior for mobile layouts.
- [x] Build frontend and save artifact log.

## Done
- 2026-02-26 11:03 MSK: Implemented UX updates in:
  - `web/src/App.tsx`
  - `web/src/types.ts`
  - `web/src/styles.css`
- 2026-02-26 11:03 MSK: Build verification:
  - `cd web && npm run build` -> `OK`.
- Artifact:
  - `artifacts/20260226_1103-web-build.log`.
