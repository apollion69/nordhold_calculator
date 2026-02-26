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
READABLE_PROTECTIONS = {0x02,0x04,0x08,0x20,0x40,0x80}

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

def is_readable(protect:int)->bool:
    if protect & PAGE_GUARD: return False
    if protect & PAGE_NOACCESS: return False
    return (protect & 0xFF) in READABLE_PROTECTIONS

def iter_regions(handle:int,min_a:int,max_a:int):
    k=ctypes.WinDLL('kernel32', use_last_error=True)
    k.VirtualQueryEx.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(MEMORY_BASIC_INFORMATION),ctypes.c_size_t]
    k.VirtualQueryEx.restype=ctypes.c_size_t
    mbi_size=ctypes.sizeof(MEMORY_BASIC_INFORMATION)
    a=min_a
    while a<max_a:
        mbi=MEMORY_BASIC_INFORMATION()
        res=k.VirtualQueryEx(ctypes.c_void_p(handle),ctypes.c_void_p(a),ctypes.byref(mbi),mbi_size)
        if res==0:
            a+=0x1000
            continue
        base=int(mbi.BaseAddress or 0); size=int(mbi.RegionSize or 0)
        if size<=0:
            a+=0x1000
            continue
        nxt=base+size
        if mbi.State==MEM_COMMIT and is_readable(int(mbi.Protect)) and base<max_a and nxt>min_a:
            s=max(base,min_a); e=min(nxt,max_a)
            if e>s:
                yield s,e-s
        a=max(nxt,a+0x1000)

def main()->int:
    root=Path(r"C:\Users\lenovo\Documents\cursor\codex\projects\nordhold")
    art=root/"worklogs"/"t47-signature-profile-fallback"/"artifacts"/"nordhold-realtime-live-debug-20260226_142333"
    out=art/"changed_int32_candidates.json"
    min_a=0x56000000; max_a=0x58000000

    b=WindowsMemoryBackend(); pid=b.find_process_id('NordHold.exe')
    if pid is None: raise RuntimeError('process not found')
    h=b.open_process(pid)
    rows=[]
    try:
        regions=list(iter_regions(h,min_a,max_a))
        print(f"pid={pid} regions={len(regions)}")
        for base,size in regions:
            try:
                m0=b.read_memory(h,base,size)
                time.sleep(1.0)
                m1=b.read_memory(h,base,size)
            except Exception:
                continue
            lim=min(len(m0),len(m1))-4
            if lim<=0: continue
            for off in range(0,lim+1,4):
                v0=struct.unpack_from('<i',m0,off)[0]
                v1=struct.unpack_from('<i',m1,off)[0]
                if v0!=v1:
                    delta=v1-v0
                    rows.append({"address":hex(base+off),"v0":v0,"v1":v1,"delta":delta,"abs_delta":abs(delta)})
        rows.sort(key=lambda x:(x['abs_delta']), reverse=True)
        payload={"schema":"nordhold_changed_int32_v1","pid":pid,"min_address":hex(min_a),"max_address":hex(max_a),"regions":len(regions),"total_matches":len(rows),"candidates":rows[:1000]}
        out.write_text(json.dumps(payload,indent=2),encoding='utf-8')
        print(f"wrote={out}")
        print(f"total_matches={len(rows)}")
        for item in rows[:30]:
            print(item)
    finally:
        b.close_process(h)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
