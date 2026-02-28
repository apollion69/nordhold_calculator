from __future__ import annotations

import json
import struct
import time
from pathlib import Path

from scripts.nordhold_memory_scan import ProcessScanner

ROOT = Path(r"C:\Users\lenovo\Documents\cursor\codex\projects\nordhold")
ART = ROOT / "worklogs" / "t47-signature-profile-fallback" / "artifacts" / "nordhold-realtime-live-debug-20260226_142333"
OUT = ART / "increment_counters_plus1.json"

MIN_A = 0x56000000
MAX_A = 0x58000000

scanner = ProcessScanner("NordHold.exe")
pid = scanner.attach()
print(f"pid={pid}")

rows = []
try:
    regions = list(scanner.iter_readable_regions(min_address=MIN_A, max_address=MAX_A))
    print(f"regions={len(regions)}")

    for base, size in regions:
        try:
            b0 = scanner.backend.read_memory(scanner.handle, base, size)
            time.sleep(1.0)
            b1 = scanner.backend.read_memory(scanner.handle, base, size)
            time.sleep(1.0)
            b2 = scanner.backend.read_memory(scanner.handle, base, size)
        except Exception:
            continue

        limit = min(len(b0), len(b1), len(b2)) - 4
        if limit <= 0:
            continue

        for off in range(0, limit + 1, 4):
            v0 = struct.unpack_from('<i', b0, off)[0]
            v1 = struct.unpack_from('<i', b1, off)[0]
            v2 = struct.unpack_from('<i', b2, off)[0]

            if v1 == v0 + 1 and v2 == v1 + 1:
                # plausible timer/counter bounds
                if -10_000_000 <= v0 <= 10_000_000:
                    rows.append({
                        "address": hex(base + off),
                        "v0": v0,
                        "v1": v1,
                        "v2": v2,
                    })

    # keep only top subset by plausible game-time range
    scored = []
    for r in rows:
        v = r["v2"]
        score = 0
        if 0 <= v <= 200000:
            score += 3
        if 0 <= v <= 20000:
            score += 2
        if 100 <= v <= 20000:
            score += 1
        r["score"] = score
        scored.append(r)

    scored.sort(key=lambda x: (x["score"], -abs(x["v2"])), reverse=True)
    payload = {
        "schema": "nordhold_increment_counters_v1",
        "pid": pid,
        "min_address": hex(MIN_A),
        "max_address": hex(MAX_A),
        "regions": len(regions),
        "candidates": scored[:500],
        "total_matches": len(scored),
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(f"wrote={OUT}")
    print(f"total_matches={len(scored)}")
    for item in scored[:30]:
        print(item)
finally:
    scanner.detach()
