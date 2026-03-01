#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import datetime as dt
import json
import math
import platform
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

from nordhold.realtime.memory_reader import (
    MemoryPermissionError,
    MemoryReadError,
    ProcessNotFoundError,
    WindowsMemoryBackend,
)
from nordhold.realtime.calibration_candidates import (
    OPTIONAL_COMBAT_FIELDS,
    REQUIRED_MEMORY_FIELDS,
    build_calibration_candidates_from_snapshots,
)

ValueType = Literal["int32", "float32", "uint64"]
NarrowMode = Literal["equal", "unchanged", "changed", "increased", "decreased", "delta"]

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

READABLE_PROTECTIONS = {
    0x02,  # PAGE_READONLY
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x20,  # PAGE_EXECUTE_READ
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
}


class SYSTEM_INFO(ctypes.Structure):
    _fields_ = [
        ("dwOemId", wintypes.DWORD),
        ("dwPageSize", wintypes.DWORD),
        ("lpMinimumApplicationAddress", ctypes.c_void_p),
        ("lpMaximumApplicationAddress", ctypes.c_void_p),
        ("dwActiveProcessorMask", ctypes.c_size_t),
        ("dwNumberOfProcessors", wintypes.DWORD),
        ("dwProcessorType", wintypes.DWORD),
        ("dwAllocationGranularity", wintypes.DWORD),
        ("wProcessorLevel", wintypes.WORD),
        ("wProcessorRevision", wintypes.WORD),
    ]


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


@dataclass(slots=True, frozen=True)
class Candidate:
    address: int
    value: int | float


def _parse_int(text: str) -> int:
    return int(str(text).strip(), 0)


def _parse_combat_meta_argument(text: str) -> tuple[str, Path]:
    raw = str(text).strip()
    if "=" not in raw:
        raise ValueError(
            f"Invalid --combat-meta '{text}'. Expected FIELD=PATH (example: lives=artifacts/lives.meta.json)."
        )
    field_name, raw_path = raw.split("=", 1)
    field_name = field_name.strip()
    path_text = raw_path.strip()
    if not field_name:
        raise ValueError(f"Invalid --combat-meta '{text}': empty field name.")
    if not path_text:
        raise ValueError(f"Invalid --combat-meta '{text}': empty path.")
    return field_name, Path(path_text)


def _parse_value(text: str, value_type: ValueType) -> int | float:
    if value_type in {"int32", "uint64"}:
        return _parse_int(text)
    return float(text)


def _decode_value(raw: bytes, value_type: ValueType) -> int | float:
    if value_type == "int32":
        return struct.unpack("<i", raw)[0]
    if value_type == "uint64":
        return struct.unpack("<Q", raw)[0]
    return struct.unpack("<f", raw)[0]


def _value_to_text(value: int | float, value_type: ValueType) -> str:
    if value_type in {"int32", "uint64"}:
        return str(int(value))
    return f"{float(value):.9g}"


def _is_readable(protect: int) -> bool:
    if protect & PAGE_GUARD:
        return False
    if protect & PAGE_NOACCESS:
        return False
    return (protect & 0xFF) in READABLE_PROTECTIONS


def _float_eq(a: float, b: float, epsilon: float) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= epsilon


def _eq(a: int | float, b: int | float, value_type: ValueType, epsilon: float) -> bool:
    if value_type == "float32":
        return _float_eq(float(a), float(b), epsilon)
    return int(a) == int(b)


def _value_width(value_type: ValueType) -> int:
    if value_type == "uint64":
        return 8
    return 4


def _resolve_snapshot_paths(base: Path) -> tuple[Path, Path]:
    name = base.name
    if name.endswith(".meta.json"):
        meta = base
        stem = name[: -len(".meta.json")]
        records = base.with_name(f"{stem}.records.tsv")
        return meta, records
    if base.suffix.lower() == ".json":
        meta = base
        records = base.with_suffix(".records.tsv")
        return meta, records
    meta = base.parent / f"{name}.meta.json"
    records = base.parent / f"{name}.records.tsv"
    return meta, records


def _read_candidates(records_path: Path, value_type: ValueType) -> list[Candidate]:
    out: list[Candidate] = []
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = line.strip()
            if not row or row.startswith("#"):
                continue
            parts = row.split("\t")
            if len(parts) != 2:
                continue
            address = int(parts[0], 0)
            value = _parse_value(parts[1], value_type)
            out.append(Candidate(address=address, value=value))
    return out


def _write_snapshot(
    *,
    out_base: Path,
    process_name: str,
    pid: int,
    value_type: ValueType,
    mode: str,
    criteria: dict[str, object],
    stats: dict[str, int | float],
    candidates: Iterable[Candidate],
    source_snapshot: Optional[Path] = None,
) -> tuple[Path, Path, int]:
    meta_path, records_path = _resolve_snapshot_paths(out_base)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with records_path.open("w", encoding="utf-8", newline="\n") as records:
        for item in candidates:
            records.write(f"{item.address:#x}\t{_value_to_text(item.value, value_type)}\n")
            count += 1

    payload = {
        "schema": "nordhold_memory_scan_snapshot_v1",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "process_name": process_name,
        "pid": pid,
        "value_type": value_type,
        "mode": mode,
        "criteria": criteria,
        "source_snapshot_meta": str(source_snapshot) if source_snapshot else "",
        "records_path": str(records_path),
        "records_count": count,
        "stats": stats,
    }
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return meta_path, records_path, count


class ProcessScanner:
    def __init__(self, process_name: str):
        if platform.system().lower() != "windows":
            raise RuntimeError("This tool must run on Windows Python to use ReadProcessMemory.")
        self.process_name = process_name
        self.backend = WindowsMemoryBackend()
        if not self.backend.supports_memory_read():
            raise RuntimeError("Windows memory backend is not available in this environment.")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.VirtualQueryEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(MEMORY_BASIC_INFORMATION),
            ctypes.c_size_t,
        ]
        self.kernel32.VirtualQueryEx.restype = ctypes.c_size_t
        self.kernel32.GetSystemInfo.argtypes = [ctypes.POINTER(SYSTEM_INFO)]
        self.kernel32.GetSystemInfo.restype = None

        self.pid = 0
        self.handle = 0
        self.max_user_address = self._max_user_address()

    def _max_user_address(self) -> int:
        info = SYSTEM_INFO()
        self.kernel32.GetSystemInfo(ctypes.byref(info))
        return int(info.lpMaximumApplicationAddress or 0x7FFFFFFFFFFF)

    def attach(self) -> int:
        pid = self.backend.find_process_id(self.process_name)
        if pid is None:
            raise ProcessNotFoundError(f"Process not found: {self.process_name}")
        self.handle = self.backend.open_process(pid)
        self.pid = int(pid)
        return self.pid

    def detach(self) -> None:
        if self.handle:
            self.backend.close_process(self.handle)
        self.pid = 0
        self.handle = 0

    def iter_readable_regions(self, min_address: int, max_address: int) -> Iterable[tuple[int, int]]:
        address = max(0, int(min_address))
        end = min(int(max_address), self.max_user_address)
        mbi_size = ctypes.sizeof(MEMORY_BASIC_INFORMATION)

        while address < end:
            mbi = MEMORY_BASIC_INFORMATION()
            result = self.kernel32.VirtualQueryEx(
                ctypes.c_void_p(self.handle),
                ctypes.c_void_p(address),
                ctypes.byref(mbi),
                mbi_size,
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
            if (
                mbi.State == MEM_COMMIT
                and _is_readable(int(mbi.Protect))
                and next_address > min_address
                and base < end
            ):
                start = max(base, min_address)
                stop = min(next_address, end)
                if stop > start:
                    yield start, stop - start

            address = max(next_address, address + 0x1000)

    def read_value(self, address: int, value_type: ValueType) -> int | float:
        raw = self.backend.read_memory(self.handle, int(address), _value_width(value_type))
        return _decode_value(raw, value_type)

    def scan_for_value(
        self,
        *,
        value_type: ValueType,
        target: int | float,
        epsilon: float,
        step: int,
        chunk_bytes: int,
        min_address: int,
        max_address: int,
        max_results: int,
    ) -> tuple[list[Candidate], dict[str, int | float]]:
        candidates: list[Candidate] = []
        regions_scanned = 0
        read_errors = 0
        bytes_scanned = 0
        next_report = 256 * 1024 * 1024
        started = time.monotonic()

        for region_base, region_size in self.iter_readable_regions(min_address=min_address, max_address=max_address):
            regions_scanned += 1
            cursor = region_base
            region_end = region_base + region_size
            carry = b""
            carry_addr = region_base

            while cursor < region_end:
                size = min(chunk_bytes, region_end - cursor)
                try:
                    chunk = self.backend.read_memory(self.handle, cursor, size)
                except MemoryReadError:
                    read_errors += 1
                    carry = b""
                    carry_addr = cursor + size
                    cursor += size
                    continue

                bytes_scanned += len(chunk)
                if bytes_scanned >= next_report:
                    print(
                        f"[scan] scanned={bytes_scanned / (1024 * 1024):.1f} MiB candidates={len(candidates)}",
                        file=sys.stderr,
                    )
                    next_report += 256 * 1024 * 1024

                if carry:
                    payload = carry + chunk
                    payload_address = carry_addr
                else:
                    payload = chunk
                    payload_address = cursor

                value_width = _value_width(value_type)
                limit = len(payload) - value_width
                if limit >= 0:
                    start_offset = (-payload_address) % step
                    offset = start_offset
                    while offset <= limit:
                        current = _decode_value(payload[offset : offset + value_width], value_type)
                        is_match = False
                        if value_type in {"int32", "uint64"}:
                            is_match = int(current) == int(target)
                        else:
                            is_match = _float_eq(float(current), float(target), epsilon)
                        if is_match:
                            candidates.append(Candidate(address=payload_address + offset, value=current))
                            if max_results > 0 and len(candidates) >= max_results:
                                elapsed = time.monotonic() - started
                                return candidates, {
                                    "regions_scanned": regions_scanned,
                                    "bytes_scanned": bytes_scanned,
                                    "read_errors": read_errors,
                                    "elapsed_s": round(elapsed, 3),
                                    "max_results_hit": 1,
                                }
                        offset += step

                carry_size = max(0, _value_width(value_type) - 1)
                if len(payload) >= carry_size and carry_size > 0:
                    carry = payload[-carry_size:]
                    carry_addr = payload_address + len(payload) - carry_size
                else:
                    carry = payload
                    carry_addr = payload_address
                cursor += size

        elapsed = time.monotonic() - started
        return candidates, {
            "regions_scanned": regions_scanned,
            "bytes_scanned": bytes_scanned,
            "read_errors": read_errors,
            "elapsed_s": round(elapsed, 3),
            "max_results_hit": 0,
        }


def _keep_candidate(
    *,
    mode: NarrowMode,
    value_type: ValueType,
    previous: int | float,
    current: int | float,
    epsilon: float,
    expected_value: Optional[int | float],
    expected_delta: Optional[int | float],
) -> bool:
    if mode == "equal":
        if expected_value is None:
            raise ValueError("--value is required for mode=equal")
        return _eq(current, expected_value, value_type, epsilon)
    if mode == "unchanged":
        ok = _eq(current, previous, value_type, epsilon)
    elif mode == "changed":
        ok = not _eq(current, previous, value_type, epsilon)
    elif mode == "increased":
        if value_type == "float32":
            ok = float(current) > float(previous) + epsilon
        else:
            ok = int(current) > int(previous)
    elif mode == "decreased":
        if value_type == "float32":
            ok = float(current) < float(previous) - epsilon
        else:
            ok = int(current) < int(previous)
    elif mode == "delta":
        if expected_delta is None:
            raise ValueError("--delta is required for mode=delta")
        diff = float(current) - float(previous)
        if value_type == "float32":
            ok = _float_eq(diff, float(expected_delta), epsilon)
        else:
            ok = int(round(diff)) == int(expected_delta)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    if not ok:
        return False
    if expected_value is None:
        return True
    return _eq(current, expected_value, value_type, epsilon)


def _print_top(candidates: list[Candidate], limit: int, title: str) -> None:
    print(title)
    if not candidates:
        print("  (no candidates)")
        return
    for idx, item in enumerate(candidates[: max(limit, 0)], start=1):
        print(f"  {idx:03d} addr={item.address:#x} value={item.value}")


def cmd_scan(args: argparse.Namespace) -> int:
    value_type: ValueType = args.value_type
    target = _parse_value(args.value, value_type)
    scanner = ProcessScanner(process_name=args.process)

    try:
        pid = scanner.attach()
    except (ProcessNotFoundError, MemoryPermissionError) as exc:
        print(f"attach_failed: {exc}", file=sys.stderr)
        return 2

    try:
        min_address = int(args.min_address)
        max_address = int(args.max_address) if args.max_address > 0 else scanner.max_user_address
        candidates, stats = scanner.scan_for_value(
            value_type=value_type,
            target=target,
            epsilon=args.epsilon,
            step=args.step,
            chunk_bytes=args.chunk_bytes,
            min_address=min_address,
            max_address=max_address,
            max_results=args.max_results,
        )
    finally:
        scanner.detach()

    meta_path, records_path, count = _write_snapshot(
        out_base=args.out,
        process_name=args.process,
        pid=pid,
        value_type=value_type,
        mode="scan",
        criteria={
            "target_value": target,
            "epsilon": args.epsilon,
            "step": args.step,
            "min_address": min_address,
            "max_address": max_address,
            "max_results": args.max_results,
        },
        stats=stats,
        candidates=candidates,
    )

    print(f"process={args.process} pid={pid}")
    print(f"value_type={value_type} target={target}")
    print(f"candidates={count}")
    print(f"snapshot_meta={meta_path}")
    print(f"snapshot_records={records_path}")
    print(f"scan_stats={json.dumps(stats)}")
    _print_top(candidates, args.print_limit, title="top_candidates:")
    return 0


def cmd_narrow(args: argparse.Namespace) -> int:
    meta_path = args.input
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    value_type: ValueType = payload["value_type"]
    records_path = Path(payload["records_path"])
    source = _read_candidates(records_path, value_type=value_type)

    expected_value: Optional[int | float] = None
    if args.value != "":
        expected_value = _parse_value(args.value, value_type)

    expected_delta: Optional[int | float] = None
    if args.delta != "":
        expected_delta = _parse_value(args.delta, value_type)

    scanner = ProcessScanner(process_name=args.process)
    try:
        pid = scanner.attach()
    except (ProcessNotFoundError, MemoryPermissionError) as exc:
        print(f"attach_failed: {exc}", file=sys.stderr)
        return 2

    started = time.monotonic()
    kept: list[Candidate] = []
    read_errors = 0
    for item in source:
        try:
            current = scanner.read_value(item.address, value_type)
        except MemoryReadError:
            read_errors += 1
            continue
        if _keep_candidate(
            mode=args.mode,
            value_type=value_type,
            previous=item.value,
            current=current,
            epsilon=args.epsilon,
            expected_value=expected_value,
            expected_delta=expected_delta,
        ):
            kept.append(Candidate(address=item.address, value=current))

    scanner.detach()
    elapsed = time.monotonic() - started
    stats = {
        "source_candidates": len(source),
        "read_errors": read_errors,
        "elapsed_s": round(elapsed, 3),
    }

    meta_out, records_out, count = _write_snapshot(
        out_base=args.out,
        process_name=args.process,
        pid=pid,
        value_type=value_type,
        mode=f"narrow:{args.mode}",
        criteria={
            "mode": args.mode,
            "expected_value": expected_value,
            "expected_delta": expected_delta,
            "epsilon": args.epsilon,
        },
        stats=stats,
        candidates=kept,
        source_snapshot=meta_path,
    )

    print(f"process={args.process} pid={pid}")
    print(f"mode={args.mode} value_type={value_type}")
    print(f"source_candidates={len(source)}")
    print(f"candidates={count}")
    print(f"snapshot_meta={meta_out}")
    print(f"snapshot_records={records_out}")
    print(f"narrow_stats={json.dumps(stats)}")
    _print_top(kept, args.print_limit, title="top_candidates:")
    return 0


def cmd_build_calibration_candidates(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parents[1]
    output_path = args.out.expanduser()
    if not output_path.is_absolute():
        output_path = (project_root / output_path).resolve()

    optional_meta_paths: dict[str, Path] = {}
    for item in list(getattr(args, "combat_meta", []) or []):
        field_name, meta_path = _parse_combat_meta_argument(item)
        if field_name in REQUIRED_MEMORY_FIELDS:
            raise ValueError(
                f"--combat-meta field '{field_name}' conflicts with required fields. "
                "Use dedicated --current-wave-meta/--gold-meta/--essence-meta arguments."
            )
        optional_meta_paths[field_name] = meta_path

    payload = build_calibration_candidates_from_snapshots(
        project_root=project_root,
        field_snapshot_meta_paths={
            "current_wave": args.current_wave_meta,
            "gold": args.gold_meta,
            "essence": args.essence_meta,
        },
        output_path=output_path,
        profile_id=args.profile_id,
        candidate_prefix=args.candidate_prefix,
        max_records_per_field=args.max_per_field,
        max_candidates=args.max_candidates,
        active_candidate_id=args.active_candidate_id,
        required_admin=bool(args.required_admin),
        required_fields=REQUIRED_MEMORY_FIELDS,
        optional_fields=OPTIONAL_COMBAT_FIELDS,
        optional_field_snapshot_meta_paths=optional_meta_paths,
    )

    print(f"output={output_path}")
    print(f"schema={payload.get('schema', '')}")
    print(f"candidates={len(payload.get('candidates', []))}")
    print(f"active_candidate_id={payload.get('active_candidate_id', '')}")
    print(f"recommended_candidate_id={payload.get('recommended_candidate_id', '')}")
    print(f"combination_space={payload.get('combination_space', 0)}")
    print(f"combination_truncated={payload.get('combination_truncated', False)}")
    if optional_meta_paths:
        print(f"extra_combat_fields={','.join(optional_meta_paths.keys())}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Practical memory scanner for NordHold.exe (int32/float32/uint64) with snapshot narrowing."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Initial exact-value scan over readable process memory regions.")
    scan.add_argument("--process", default="NordHold.exe")
    scan.add_argument("--type", dest="value_type", choices=["int32", "float32", "uint64"], required=True)
    scan.add_argument("--value", required=True, help="Target value (supports hex for int32, e.g. 0x64).")
    scan.add_argument("--out", type=Path, required=True, help="Snapshot output base path.")
    scan.add_argument("--step", type=int, default=4, help="Scan stride in bytes. Typical: 4.")
    scan.add_argument("--epsilon", type=float, default=0.001, help="Float comparison tolerance.")
    scan.add_argument("--chunk-bytes", type=int, default=1 << 20, help="ReadProcessMemory chunk size.")
    scan.add_argument("--min-address", type=_parse_int, default=0, help="Minimum address (default 0).")
    scan.add_argument(
        "--max-address",
        type=_parse_int,
        default=0,
        help="Maximum address (default 0 = auto max application address).",
    )
    scan.add_argument(
        "--max-results",
        type=int,
        default=250000,
        help="Hard cap for candidates to avoid runaway memory usage.",
    )
    scan.add_argument("--print-limit", type=int, default=30, help="How many candidate rows to print.")
    scan.set_defaults(func=cmd_scan)

    narrow = sub.add_parser("narrow", help="Narrow existing snapshot against current live process values.")
    narrow.add_argument("--process", default="NordHold.exe")
    narrow.add_argument("--input", type=Path, required=True, help="Input snapshot .meta.json path.")
    narrow.add_argument("--out", type=Path, required=True, help="Output snapshot base path.")
    narrow.add_argument("--mode", choices=["equal", "unchanged", "changed", "increased", "decreased", "delta"], required=True)
    narrow.add_argument("--value", default="", help="Absolute expected value for `equal` or additional post-filter.")
    narrow.add_argument("--delta", default="", help="Expected value delta for `mode=delta`.")
    narrow.add_argument("--epsilon", type=float, default=0.001, help="Float comparison tolerance.")
    narrow.add_argument("--print-limit", type=int, default=30, help="How many candidate rows to print.")
    narrow.set_defaults(func=cmd_narrow)

    build_candidates = sub.add_parser(
        "build-calibration-candidates",
        help="Build LiveBridge-compatible calibration candidates JSON from snapshot metas.",
    )
    build_candidates.add_argument("--current-wave-meta", type=Path, required=True, help="Snapshot .meta.json for current_wave.")
    build_candidates.add_argument("--gold-meta", type=Path, required=True, help="Snapshot .meta.json for gold.")
    build_candidates.add_argument("--essence-meta", type=Path, required=True, help="Snapshot .meta.json for essence.")
    build_candidates.add_argument(
        "--combat-meta",
        action="append",
        default=[],
        help="Optional extra combat field snapshot meta in FIELD=PATH form (repeatable).",
    )
    build_candidates.add_argument("--out", type=Path, required=True, help="Output candidates JSON path.")
    build_candidates.add_argument("--profile-id", default="", help="Optional target signature profile id.")
    build_candidates.add_argument("--candidate-prefix", default="artifact_combo", help="Candidate id prefix.")
    build_candidates.add_argument("--max-per-field", type=int, default=4, help="How many addresses to use per field snapshot.")
    build_candidates.add_argument("--max-candidates", type=int, default=256, help="Hard cap for generated combinations.")
    build_candidates.add_argument(
        "--active-candidate-id",
        default="",
        help="Optional active candidate id. Defaults to the first generated candidate.",
    )
    build_candidates.add_argument(
        "--required-admin",
        action="store_true",
        help="Set required_admin=true in generated candidates.",
    )
    build_candidates.set_defaults(func=cmd_build_calibration_candidates)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "step") and args.step <= 0:
        parser.error("--step must be > 0")
    if hasattr(args, "chunk_bytes") and args.chunk_bytes < 64:
        parser.error("--chunk-bytes must be >= 64")
    if hasattr(args, "max_per_field") and args.max_per_field <= 0:
        parser.error("--max-per-field must be > 0")
    if hasattr(args, "max_candidates") and args.max_candidates <= 0:
        parser.error("--max-candidates must be > 0")
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
