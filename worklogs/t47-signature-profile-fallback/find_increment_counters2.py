from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import struct
import time
from pathlib import Path

from nordhold.realtime.memory_reader import WindowsMemoryBackend

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE_PROTECTIONS = {
    0x02,
    0x04,
    0x08,
    0x20,
    0x40,
    0x80,
}


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def is_readable(protect: int) -> bool:
    if protect & PAGE_GUARD:
        return False
    if protect & PAGE_NOACCESS:
        return False
    return (protect & 0xFF) in READABLE_PROTECTIONS


def iter_regions(handle: int, min_address: int, max_address: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.VirtualQueryEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION),
        ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    mbi_size = ctypes.sizeof(MEMORY_BASIC_INFORMATION)

    address = min_address
    while address < max_address:
        mbi = MEMORY_BASIC_INFORMATION()
        result = kernel32.VirtualQueryEx(
            ctypes.c_void_p(handle), ctypes.c_void_p(address), ctypes.byref(mbi), mbi_size
        )
        if result == 0:
            address += 0x1000
            continue
        base = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize or 0)
        if size <= 0:
            address += 0x1000
            continue
        next_address = base + size
        if mbi.State == MEM_COMMIT and is_readable(int(mbi.Protect)) and base < max_address and next_address > min_address:
            start = max(base, min_address)
            stop = min(next_address, max_address)
            if stop > start:
                yield start, stop - start
        address = max(next_address, address + 0x1000)


def main() -> int:
    root = Path(r"C:\Users\lenovo\Documents\cursor\codex\projects\nordhold")
    art = root / "worklogs" / "t47-signature-profile-fallback" / "artifacts" / "nordhold-realtime-live-debug-20260226_142333"
    out = art / "increment_counters_plus1.json"

    min_a = 0x56000000
    max_a = 0x58000000

    backend = WindowsMemoryBackend()
    pid = backend.find_process_id("NordHold.exe")
    if pid is None:
        raise RuntimeError("process not found")
    handle = backend.open_process(pid)

    rows = []
    try:
        regions = list(iter_regions(handle, min_a, max_a))
        print(f"pid={pid} regions={len(regions)}")
        for base, size in regions:
            try:
                b0 = backend.read_memory(handle, base, size)
                time.sleep(1.0)
                b1 = backend.read_memory(handle, base, size)
                time.sleep(1.0)
                b2 = backend.read_memory(handle, base, size)
            except Exception:
                continue

            limit = min(len(b0), len(b1), len(b2)) - 4
            if limit <= 0:
                continue
            for off in range(0, limit + 1, 4):
                v0 = struct.unpack_from("<i", b0, off)[0]
                v1 = struct.unpack_from("<i", b1, off)[0]
                v2 = struct.unpack_from("<i", b2, off)[0]
                if v1 == v0 + 1 and v2 == v1 + 1 and -10_000_000 <= v0 <= 10_000_000:
                    rows.append({"address": hex(base + off), "v0": v0, "v1": v1, "v2": v2})

        for row in rows:
            v = row["v2"]
            score = 0
            if 0 <= v <= 200000:
                score += 3
            if 0 <= v <= 20000:
                score += 2
            if 100 <= v <= 20000:
                score += 1
            row["score"] = score

        rows.sort(key=lambda x: (x["score"], -abs(x["v2"])), reverse=True)
        payload = {
            "schema": "nordhold_increment_counters_v1",
            "pid": pid,
            "min_address": hex(min_a),
            "max_address": hex(max_a),
            "regions": len(regions),
            "total_matches": len(rows),
            "candidates": rows[:500],
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote={out}")
        print(f"total_matches={len(rows)}")
        for item in rows[:30]:
            print(item)
    finally:
        backend.close_process(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
