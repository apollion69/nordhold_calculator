from __future__ import annotations

import json
import time
from pathlib import Path

from nordhold.realtime.memory_reader import WindowsMemoryBackend

ROOT = Path(r"C:\Users\lenovo\Documents\cursor\codex\projects\nordhold")
ART = ROOT / "worklogs" / "t47-signature-profile-fallback" / "artifacts" / "nordhold-realtime-live-debug-20260226_142333"
OUT = ART / "player_hp_candidate_timeseries.json"

# Selected by context-score probe.
CANDIDATES = [
    0x56B4E6E8,
    0x56B50B10,
    0x56BF2F50,
    0x56B30510,
    0x56ADE9F8,
    0x56B1C8D0,
    0x56B07664,
    0x56B1C878,
    0x56B5C18C,
    0x56B65B74,
]

backend = WindowsMemoryBackend()
pid = backend.find_process_id("NordHold.exe")
if pid is None:
    raise SystemExit("process not found")
handle = backend.open_process(pid)

samples = []
start = time.time()
try:
    for i in range(180):  # ~3 minutes
        row = {"t": round(time.time() - start, 3)}
        for addr in CANDIDATES:
            key = hex(addr)
            try:
                raw = backend.read_memory(handle, addr, 4)
                val = int.from_bytes(raw, "little", signed=True)
            except Exception:
                val = None
            row[key] = val
        samples.append(row)
        time.sleep(1.0)
finally:
    backend.close_process(handle)

# Summaries
summary = {}
for addr in CANDIDATES:
    key = hex(addr)
    vals = [s[key] for s in samples if s[key] is not None]
    if not vals:
        summary[key] = {"readable": False}
        continue
    summary[key] = {
        "readable": True,
        "min": min(vals),
        "max": max(vals),
        "first": vals[0],
        "last": vals[-1],
        "distinct": len(set(vals)),
        "changed": len(set(vals)) > 1,
    }

payload = {
    "schema": "nordhold_hp_candidate_timeseries_v1",
    "created_at": time.time(),
    "pid": pid,
    "duration_s": samples[-1]["t"] if samples else 0,
    "candidate_addresses": [hex(a) for a in CANDIDATES],
    "summary": summary,
    "samples": samples,
}
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"wrote={OUT}")
for k, v in summary.items():
    print(k, v)
