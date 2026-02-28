from __future__ import annotations

import json
from pathlib import Path

from nordhold.realtime.memory_reader import WindowsMemoryBackend

ROOT = Path(r"C:\Users\lenovo\Documents\cursor\codex\projects\nordhold")
ART = ROOT / "worklogs" / "t47-signature-profile-fallback" / "artifacts" / "nordhold-realtime-live-debug-20260226_142333"
RECORDS = ART / "player_hp_guess20_s1.records.tsv"
OUT = ART / "player_hp_guess20_candidates_neighborhood.json"

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
        neighborhood = {}
        for rel in range(-0x20, 0x24, 4):
            a = addr + rel
            try:
                raw = backend.read_memory(handle, a, 4)
            except Exception:
                continue
            value = int.from_bytes(raw, "little", signed=True)
            neighborhood[f"{rel:+#x}"] = value

        # Heuristic score: count of small positive counters around anchor.
        around = list(neighborhood.values())
        score_small = sum(1 for v in around if 0 <= v <= 500)
        score_exact20 = sum(1 for v in around if v == 20)
        rows.append(
            {
                "address": hex(addr),
                "score_small": score_small,
                "score_exact20": score_exact20,
                "neighborhood": neighborhood,
            }
        )
finally:
    backend.close_process(handle)

rows.sort(key=lambda x: (x["score_exact20"], x["score_small"]), reverse=True)
OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(f"wrote={OUT}")
print("top10:")
for item in rows[:10]:
    print(item["address"], item["score_exact20"], item["score_small"])
