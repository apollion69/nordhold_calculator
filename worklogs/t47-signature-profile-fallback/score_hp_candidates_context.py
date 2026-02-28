from __future__ import annotations

import json
from pathlib import Path

from nordhold.realtime.memory_reader import WindowsMemoryBackend

ROOT = Path(r"C:\Users\lenovo\Documents\cursor\codex\projects\nordhold")
ART = ROOT / "worklogs" / "t47-signature-profile-fallback" / "artifacts" / "nordhold-realtime-live-debug-20260226_142333"
RECORDS = ART / "player_hp_guess20_s1.records.tsv"
OUT = ART / "player_hp_guess20_context_score.json"

TARGET_VALUES = {3, 5, 9, 20, 51, 75, 90, 99}

backend = WindowsMemoryBackend()
pid = backend.find_process_id("NordHold.exe")
if pid is None:
    raise SystemExit("process not found")
handle = backend.open_process(pid)

rows = []
try:
    for line in RECORDS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        addr_s, _ = line.split("\t", 1)
        addr = int(addr_s, 0)

        values = []
        seen_targets = set()
        readable = 0
        for rel in range(-0x200, 0x204, 4):
            a = addr + rel
            try:
                raw = backend.read_memory(handle, a, 4)
            except Exception:
                continue
            readable += 1
            v = int.from_bytes(raw, "little", signed=True)
            values.append(v)
            if v in TARGET_VALUES:
                seen_targets.add(v)

        # prefer clusters where many small game-like counters exist around candidate
        small = sum(1 for v in values if 0 <= v <= 200)
        zeros = values.count(0)
        rows.append(
            {
                "address": hex(addr),
                "readable_cells": readable,
                "small_count": small,
                "zero_count": zeros,
                "target_hits": sorted(seen_targets),
                "target_hit_count": len(seen_targets),
            }
        )
finally:
    backend.close_process(handle)

rows.sort(key=lambda x: (x["target_hit_count"], x["small_count"], -x["zero_count"]), reverse=True)
OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(f"wrote={OUT}")
for item in rows[:12]:
    print(item)
