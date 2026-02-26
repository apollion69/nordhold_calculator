#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nordhold.realtime.memory_reader import MemoryReadError, ProcessNotFoundError, WindowsMemoryBackend


@dataclass(slots=True, frozen=True)
class CandidateField:
    name: str
    address: int


def _parse_int(text: str) -> int:
    return int(str(text).strip(), 0)


def _load_calibration_candidate(
    path: Path,
    candidate_id: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid calibration JSON: {path}")

    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        raise ValueError(f"Calibration payload has no candidates: {path}")

    selected_id = candidate_id.strip()
    if not selected_id:
        selected_id = str(payload.get("recommended_candidate_id", "")).strip()
    if not selected_id:
        selected_id = str(payload.get("active_candidate_id", "")).strip()
    if not selected_id:
        first = candidates[0]
        if isinstance(first, dict):
            selected_id = str(first.get("id", "")).strip()

    selected: dict[str, Any] | None = None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "")).strip() == selected_id:
            selected = item
            break
    if selected is None:
        raise ValueError(f"Candidate '{selected_id}' not found in {path}")

    return payload, selected, selected_id


def _extract_anchor_fields(candidate_payload: dict[str, Any]) -> list[CandidateField]:
    fields_raw = candidate_payload.get("fields", {})
    if not isinstance(fields_raw, dict):
        return []
    anchors: list[CandidateField] = []
    for name, spec in fields_raw.items():
        if not isinstance(spec, dict):
            continue
        address_text = str(spec.get("address", "")).strip()
        if not address_text:
            continue
        try:
            address = _parse_int(address_text)
        except ValueError:
            continue
        if address <= 0:
            continue
        anchors.append(CandidateField(name=str(name), address=address))
    return anchors


def _collect_probe_addresses(
    anchors: list[CandidateField],
    *,
    radius: int,
    max_addresses: int,
) -> list[int]:
    addresses: set[int] = set()
    for anchor in anchors:
        start = max(0, anchor.address - radius)
        stop = anchor.address + radius
        aligned_start = start - (start % 4)
        for addr in range(aligned_start, stop + 1, 4):
            addresses.add(addr)
            if max_addresses > 0 and len(addresses) >= max_addresses:
                break
        if max_addresses > 0 and len(addresses) >= max_addresses:
            break
    return sorted(addresses)


def _safe_read_int32(backend: WindowsMemoryBackend, handle: int, address: int) -> int | None:
    try:
        raw = backend.read_memory(handle, address, 4)
    except MemoryReadError:
        return None
    return int.from_bytes(raw, "little", signed=True)


def _sample_addresses(
    backend: WindowsMemoryBackend,
    handle: int,
    addresses: list[int],
    *,
    duration_s: int,
    interval_ms: int,
    include_samples: bool,
) -> tuple[list[dict[str, Any]], dict[int, list[int | None]]]:
    series: dict[int, list[int | None]] = {addr: [] for addr in addresses}
    samples: list[dict[str, Any]] = []

    started = time.time()
    while True:
        now = time.time()
        rel_s = now - started
        row: dict[str, Any] | None = {"t": round(rel_s, 3)} if include_samples else None
        for addr in addresses:
            value = _safe_read_int32(backend, handle, addr)
            series[addr].append(value)
            if row is not None:
                row[hex(addr)] = value
        if row is not None:
            samples.append(row)

        if rel_s >= duration_s:
            break
        time.sleep(max(0.05, float(interval_ms) / 1000.0))

    return samples, series


def _address_stats(values: list[int | None]) -> dict[str, Any]:
    present = [v for v in values if v is not None]
    if not present:
        return {
            "readable": False,
            "distinct": 0,
            "changed": False,
            "first": None,
            "last": None,
            "min": None,
            "max": None,
            "delta_count": 0,
            "non_decreasing_ratio": 0.0,
            "plus_one_ratio": 0.0,
        }

    deltas: list[int] = []
    for idx in range(1, len(present)):
        deltas.append(present[idx] - present[idx - 1])
    non_decreasing = sum(1 for d in deltas if d >= 0)
    plus_one = sum(1 for d in deltas if d == 1)
    delta_count = len(deltas)
    distinct = len(set(present))
    return {
        "readable": True,
        "distinct": distinct,
        "changed": distinct > 1,
        "first": present[0],
        "last": present[-1],
        "min": min(present),
        "max": max(present),
        "delta_count": delta_count,
        "non_decreasing_ratio": float(non_decreasing) / float(delta_count) if delta_count > 0 else 0.0,
        "plus_one_ratio": float(plus_one) / float(delta_count) if delta_count > 0 else 0.0,
    }


def _score_enemies_alive(stats: dict[str, Any]) -> int:
    if not stats["readable"]:
        return 0
    min_v = int(stats["min"])
    max_v = int(stats["max"])
    distinct = int(stats["distinct"])
    if min_v < 0 or max_v > 500:
        return 0
    score = 0
    if distinct > 1:
        score += 2
    if 0 <= max_v <= 200:
        score += 2
    if stats["non_decreasing_ratio"] < 1.0:
        score += 1
    return score


def _score_combat_time(stats: dict[str, Any]) -> int:
    if not stats["readable"]:
        return 0
    min_v = int(stats["min"])
    max_v = int(stats["max"])
    distinct = int(stats["distinct"])
    if min_v < 0 or max_v > 10 * 24 * 60 * 60:
        return 0
    score = 0
    if distinct > 1:
        score += 2
    if stats["non_decreasing_ratio"] >= 0.7:
        score += 2
    if stats["plus_one_ratio"] >= 0.5:
        score += 2
    return score


def _score_combat_phase_bool(stats: dict[str, Any]) -> int:
    if not stats["readable"]:
        return 0
    min_v = int(stats["min"])
    max_v = int(stats["max"])
    distinct = int(stats["distinct"])
    if min_v < 0 or max_v > 1:
        return 0
    score = 1
    if distinct == 2:
        score += 2
    return score


def _select_top(
    scores: list[dict[str, Any]],
    *,
    min_score: int,
) -> dict[str, Any] | None:
    filtered = [item for item in scores if int(item.get("score", 0)) >= min_score]
    if not filtered:
        return None
    filtered.sort(key=lambda x: (int(x["score"]), float(x.get("stats", {}).get("plus_one_ratio", 0.0))), reverse=True)
    return filtered[0]


def _write_single_address_snapshot_meta(
    *,
    out_base: Path,
    process_name: str,
    pid: int,
    field_name: str,
    address: int,
    value: int,
    source_notes: dict[str, Any],
) -> tuple[Path, Path]:
    records_path = out_base.with_suffix(".records.tsv")
    meta_path = out_base.with_suffix(".meta.json")
    records_path.write_text(f"{hex(address)}\\t{value}\\n", encoding="utf-8")
    payload = {
        "schema": "nordhold_memory_scan_snapshot_v1",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "process_name": process_name,
        "pid": pid,
        "value_type": "int32",
        "mode": "auto_deep_probe_select",
        "criteria": {
            "field": field_name,
            "source": "nordhold_combat_deep_probe",
            **source_notes,
        },
        "source_snapshot_meta": "",
        "records_path": str(records_path),
        "records_count": 1,
        "stats": {"selected": 1},
    }
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return meta_path, records_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous deep probe for optional combat memory fields.")
    parser.add_argument("--process", default="NordHold.exe")
    parser.add_argument("--candidates", type=Path, required=True, help="Calibration candidates JSON path.")
    parser.add_argument("--candidate-id", default="", help="Candidate id override.")
    parser.add_argument("--duration-s", type=int, default=120)
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument("--radius", type=int, default=0x1200)
    parser.add_argument("--max-addresses", type=int, default=12000)
    parser.add_argument(
        "--include-samples",
        action="store_true",
        help="Include full per-tick address samples in JSON report (large output).",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output JSON report path.")
    parser.add_argument(
        "--write-selected-meta-dir",
        type=Path,
        default=Path(""),
        help="Optional directory to write selected single-address snapshot metas.",
    )
    args = parser.parse_args()

    payload, selected_candidate, selected_id = _load_calibration_candidate(
        args.candidates.expanduser().resolve(), args.candidate_id
    )
    anchors = _extract_anchor_fields(selected_candidate)
    if not anchors:
        raise ValueError("No anchor fields with resolved addresses in selected candidate.")

    probe_addresses = _collect_probe_addresses(
        anchors,
        radius=max(0x100, int(args.radius)),
        max_addresses=max(100, int(args.max_addresses)),
    )

    backend = WindowsMemoryBackend()
    pid = backend.find_process_id(args.process)
    if pid is None:
        raise ProcessNotFoundError(f"Process not found: {args.process}")
    handle = backend.open_process(pid)
    try:
        samples, series = _sample_addresses(
            backend,
            handle,
            probe_addresses,
            duration_s=max(5, int(args.duration_s)),
            interval_ms=max(100, int(args.interval_ms)),
            include_samples=bool(args.include_samples),
        )
    finally:
        backend.close_process(handle)

    stats_by_address: dict[int, dict[str, Any]] = {}
    for addr, values in series.items():
        stats_by_address[addr] = _address_stats(values)

    enemies_scores = []
    combat_time_scores = []
    combat_phase_scores = []
    for addr, stats in stats_by_address.items():
        enemies_scores.append({"address": hex(addr), "score": _score_enemies_alive(stats), "stats": stats})
        combat_time_scores.append({"address": hex(addr), "score": _score_combat_time(stats), "stats": stats})
        combat_phase_scores.append({"address": hex(addr), "score": _score_combat_phase_bool(stats), "stats": stats})

    top_enemies = _select_top(enemies_scores, min_score=3)
    top_combat_time = _select_top(combat_time_scores, min_score=4)
    top_combat_phase = _select_top(combat_phase_scores, min_score=2)

    selected_meta: dict[str, Any] = {}
    meta_dir = args.write_selected_meta_dir.expanduser().resolve() if str(args.write_selected_meta_dir) else None
    if meta_dir is not None:
        meta_dir.mkdir(parents=True, exist_ok=True)
        for field_name, top in (
            ("enemies_alive", top_enemies),
            ("combat_time_s", top_combat_time),
            ("is_combat_phase", top_combat_phase),
        ):
            if top is None:
                continue
            addr = int(str(top["address"]), 16)
            final_value = int(top["stats"]["last"])
            base = meta_dir / f"{field_name}_auto_probe"
            meta_path, records_path = _write_single_address_snapshot_meta(
                out_base=base,
                process_name=args.process,
                pid=int(pid),
                field_name=field_name,
                address=addr,
                value=final_value,
                source_notes={"score": int(top["score"])},
            )
            selected_meta[field_name] = {
                "meta_path": str(meta_path),
                "records_path": str(records_path),
                "address": hex(addr),
                "value": final_value,
                "score": int(top["score"]),
            }

    report = {
        "schema": "nordhold_combat_deep_probe_v1",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "process_name": args.process,
        "pid": int(pid),
        "candidate_source_path": str(args.candidates.expanduser().resolve()),
        "selected_candidate_id": selected_id,
        "anchor_fields": [{"name": item.name, "address": hex(item.address)} for item in anchors],
        "probe_address_count": len(probe_addresses),
        "duration_s": max(5, int(args.duration_s)),
        "interval_ms": max(100, int(args.interval_ms)),
        "summary": {
            "top_enemies_alive": top_enemies,
            "top_combat_time_s": top_combat_time,
            "top_is_combat_phase": top_combat_phase,
            "selected_meta": selected_meta,
        },
        "sample_count": len(samples),
        "samples_included": bool(args.include_samples),
        "samples": samples if bool(args.include_samples) else [],
    }
    out_path = args.out.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"output={out_path}")
    print(f"candidate_id={selected_id}")
    print(f"probe_address_count={len(probe_addresses)}")
    print(f"top_enemies_alive={top_enemies['address'] if top_enemies else ''}")
    print(f"top_combat_time_s={top_combat_time['address'] if top_combat_time else ''}")
    print(f"top_is_combat_phase={top_combat_phase['address'] if top_combat_phase else ''}")
    if selected_meta:
        print(f"selected_meta_fields={','.join(selected_meta.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
