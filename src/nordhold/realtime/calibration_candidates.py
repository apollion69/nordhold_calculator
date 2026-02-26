from __future__ import annotations

import datetime as dt
import itertools
import json
import math
from pathlib import Path
from typing import Any, Dict, Sequence

from .memory_reader import (
    DEFAULT_OPTIONAL_COMBAT_FIELDS,
    DEFAULT_REQUIRED_COMBAT_FIELDS,
    MemoryProfileError,
)

REQUIRED_COMBAT_FIELDS: tuple[str, ...] = DEFAULT_REQUIRED_COMBAT_FIELDS
OPTIONAL_COMBAT_FIELDS: tuple[str, ...] = DEFAULT_OPTIONAL_COMBAT_FIELDS

# Backward-compatible alias used by existing code/tests.
REQUIRED_MEMORY_FIELDS: tuple[str, ...] = REQUIRED_COMBAT_FIELDS

DEFAULT_CALIBRATION_CANDIDATES_GLOB = "memory_calibration_candidates*.json"
CALIBRATION_CANDIDATES_SCHEMA_V1 = "nordhold_memory_calibration_candidates_v1"
CALIBRATION_CANDIDATES_SCHEMA_V2 = "nordhold_memory_calibration_candidates_v2"
CALIBRATION_CANDIDATE_ALGORITHM = (
    "preferred_if_valid_else_max_required_resolved_then_active_candidate_id_then_original_order"
)


def _parse_int(value: Any, label: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        try:
            return int(text, 0)
        except ValueError as exc:
            raise MemoryProfileError(f"Invalid integer for {label}: {value}") from exc
    raise MemoryProfileError(f"Invalid integer type for {label}: {type(value).__name__}")


def _address_to_hex(value: Any) -> str:
    return hex(_parse_int(value, "address"))


def _normalize_field_names(
    fields: Sequence[str] | None,
    *,
    label: str,
    allow_empty: bool,
    fallback: Sequence[str] | None = None,
) -> tuple[str, ...]:
    items: list[str] = []
    seen: set[str] = set()

    if fields is None:
        source = list(fallback or [])
    else:
        source = list(fields)

    for index, item in enumerate(source):
        name = str(item).strip()
        if not name:
            raise MemoryProfileError(f"{label}[{index}] must be non-empty.")
        if name in seen:
            continue
        seen.add(name)
        items.append(name)

    if items:
        return tuple(items)
    if allow_empty:
        return tuple()
    raise MemoryProfileError(f"{label} must include at least one field.")


def resolve_combat_field_sets(
    calibration_payload: Dict[str, Any] | None,
    *,
    required_fields: Sequence[str] = REQUIRED_MEMORY_FIELDS,
    optional_fields: Sequence[str] = OPTIONAL_COMBAT_FIELDS,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    payload = calibration_payload if isinstance(calibration_payload, dict) else {}
    raw_required = payload.get("required_combat_fields", payload.get("required_fields", None))
    raw_optional = payload.get("optional_combat_fields", payload.get("optional_fields", None))

    required = _normalize_field_names(
        list(raw_required) if isinstance(raw_required, (list, tuple)) else None,
        label="required_combat_fields",
        allow_empty=False,
        fallback=required_fields,
    )
    optional = _normalize_field_names(
        list(raw_optional) if isinstance(raw_optional, (list, tuple)) else None,
        label="optional_combat_fields",
        allow_empty=True,
        fallback=optional_fields,
    )
    optional_without_required = tuple(name for name in optional if name not in required)
    return required, optional_without_required


def _resolve_records_path(
    *,
    project_root: Path,
    meta_path: Path,
    meta_payload: Dict[str, Any],
) -> Path:
    raw_records = str(meta_payload.get("records_path", "")).strip()
    candidates: list[Path] = []

    if raw_records:
        normalized = raw_records.replace("\\", "/")
        record_path = Path(normalized)
        if record_path.is_absolute():
            candidates.append(record_path)
        else:
            candidates.append((project_root / record_path).resolve())
            candidates.append((meta_path.parent / record_path).resolve())

    if meta_path.name.endswith(".meta.json"):
        stem = meta_path.name[: -len(".meta.json")]
        candidates.append(meta_path.with_name(f"{stem}.records.tsv"))
    else:
        candidates.append(meta_path.with_suffix(".records.tsv"))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise MemoryProfileError(
        f"Snapshot records file was not found for meta '{meta_path}'. "
        f"Tried: {', '.join(str(path) for path in candidates)}"
    )


def _read_snapshot_addresses(
    *,
    project_root: Path,
    meta_path: Path,
    max_records_per_field: int,
) -> tuple[list[int], str, Path]:
    try:
        meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MemoryProfileError(f"Snapshot meta file not found: {meta_path}") from exc
    except json.JSONDecodeError as exc:
        raise MemoryProfileError(f"Snapshot meta is not valid JSON: {meta_path}: {exc}") from exc

    if not isinstance(meta_payload, dict):
        raise MemoryProfileError(f"Snapshot meta must be a JSON object: {meta_path}")

    value_type = str(meta_payload.get("value_type", "int32")).strip().lower()
    if value_type not in {"int32", "float32"}:
        raise MemoryProfileError(
            f"Snapshot '{meta_path}' has unsupported value_type '{value_type}'. "
            "Supported scanner value types: int32|float32."
        )

    records_path = _resolve_records_path(
        project_root=project_root,
        meta_path=meta_path,
        meta_payload=meta_payload,
    )

    addresses: list[int] = []
    seen: set[int] = set()
    with records_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            row = line.strip()
            if not row or row.startswith("#"):
                continue
            parts = row.split("\t")
            if len(parts) < 1:
                continue
            address = _parse_int(parts[0], f"{records_path}:{line_number}:address")
            if address in seen:
                continue
            seen.add(address)
            addresses.append(address)
            if max_records_per_field > 0 and len(addresses) >= max_records_per_field:
                break

    if not addresses:
        raise MemoryProfileError(f"Snapshot records have no candidate addresses: {records_path}")
    return addresses, value_type, records_path


def _field_has_resolved_address(field_payload: Any) -> bool:
    if not isinstance(field_payload, dict):
        return False
    if "address" not in field_payload:
        return False
    raw_address = field_payload.get("address")
    if str(raw_address).strip() == "":
        return False
    try:
        return _parse_int(raw_address, "field.address") != 0
    except MemoryProfileError:
        return False


def _candidate_quality(
    *,
    fields_payload: Dict[str, Any],
    required_fields: tuple[str, ...],
    optional_fields: tuple[str, ...],
) -> Dict[str, Any]:
    missing_required: list[str] = []
    unresolved_required: list[str] = []
    resolved_required: list[str] = []
    resolved_optional: list[str] = []

    for field_name in required_fields:
        raw_spec = fields_payload.get(field_name)
        if not isinstance(raw_spec, dict):
            missing_required.append(field_name)
            continue
        if _field_has_resolved_address(raw_spec):
            resolved_required.append(field_name)
        else:
            unresolved_required.append(field_name)

    for field_name in optional_fields:
        raw_spec = fields_payload.get(field_name)
        if _field_has_resolved_address(raw_spec):
            resolved_optional.append(field_name)

    required_total = len(required_fields)
    optional_total = len(optional_fields)
    resolved_required_count = len(resolved_required)
    resolved_optional_count = len(resolved_optional)

    return {
        "valid": resolved_required_count == required_total,
        "required_fields_total": required_total,
        "resolved_required_count": resolved_required_count,
        "resolved_required_fields": resolved_required_count,
        "required_resolution_ratio": (
            float(resolved_required_count) / float(required_total) if required_total > 0 else 0.0
        ),
        "missing_required_field_names": missing_required,
        "unresolved_required_field_names": unresolved_required,
        "resolved_required_field_names": resolved_required,
        "optional_fields_total": optional_total,
        "resolved_optional_count": resolved_optional_count,
        "resolved_optional_fields": resolved_optional_count,
        "optional_resolution_ratio": (
            float(resolved_optional_count) / float(optional_total) if optional_total > 0 else 0.0
        ),
        "resolved_optional_field_names": resolved_optional,
    }


def _iter_candidate_entries(calibration_payload: Dict[str, Any]) -> list[tuple[str, Dict[str, Any], int]]:
    if not isinstance(calibration_payload, dict):
        raise MemoryProfileError("Calibration payload must be a JSON object.")

    raw_candidates = calibration_payload.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raise MemoryProfileError("Calibration payload has invalid 'candidates' list.")

    entries: list[tuple[str, Dict[str, Any], int]] = []
    seen_ids: set[str] = set()
    for index, candidate in enumerate(raw_candidates, start=1):
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("id", "")).strip() or f"candidate_{index}"
        if candidate_id in seen_ids:
            raise MemoryProfileError(f"Calibration payload has duplicate candidate id: {candidate_id}")
        seen_ids.add(candidate_id)
        entries.append((candidate_id, candidate, index))

    if not entries:
        raise MemoryProfileError("Calibration payload has no candidate entries.")
    return entries


def build_calibration_candidates_from_snapshots(
    *,
    project_root: Path,
    field_snapshot_meta_paths: Dict[str, Path],
    output_path: Path,
    profile_id: str = "",
    candidate_prefix: str = "artifact_combo",
    max_records_per_field: int = 5,
    max_candidates: int = 256,
    active_candidate_id: str = "",
    required_admin: bool = False,
    required_fields: Sequence[str] = REQUIRED_MEMORY_FIELDS,
    optional_fields: Sequence[str] = OPTIONAL_COMBAT_FIELDS,
    optional_field_snapshot_meta_paths: Dict[str, Path] | None = None,
) -> Dict[str, Any]:
    if max_records_per_field <= 0:
        raise MemoryProfileError("max_records_per_field must be > 0.")
    if max_candidates <= 0:
        raise MemoryProfileError("max_candidates must be > 0.")

    selected_required_fields = _normalize_field_names(
        tuple(required_fields),
        label="required_fields",
        allow_empty=False,
    )
    declared_optional_fields = _normalize_field_names(
        tuple(optional_fields),
        label="optional_fields",
        allow_empty=True,
    )

    missing = [name for name in selected_required_fields if name not in field_snapshot_meta_paths]
    if missing:
        raise MemoryProfileError(
            f"Missing snapshot meta path(s) for required field(s): {', '.join(missing)}"
        )

    normalized_optional_meta: Dict[str, Path] = {}
    raw_optional_meta = optional_field_snapshot_meta_paths or {}
    for raw_name, raw_path in raw_optional_meta.items():
        field_name = str(raw_name).strip()
        if not field_name:
            raise MemoryProfileError("optional_field_snapshot_meta_paths contains an empty field name.")
        if field_name in selected_required_fields:
            raise MemoryProfileError(
                f"Optional field '{field_name}' conflicts with required field set."
            )
        normalized_optional_meta[field_name] = raw_path

    selected_optional_fields = tuple(normalized_optional_meta.keys())
    effective_optional_fields = tuple(
        name
        for name in itertools.chain(declared_optional_fields, selected_optional_fields)
        if name not in selected_required_fields
    )
    effective_optional_fields = tuple(dict.fromkeys(effective_optional_fields))

    selected_fields = selected_required_fields + selected_optional_fields
    addresses_by_field: Dict[str, list[int]] = {}
    value_type_by_field: Dict[str, str] = {}
    records_by_field: Dict[str, Path] = {}
    meta_by_field: Dict[str, str] = {}

    for field_name in selected_required_fields:
        raw_meta_path = field_snapshot_meta_paths[field_name].expanduser()
        meta_path = raw_meta_path if raw_meta_path.is_absolute() else (project_root / raw_meta_path).resolve()
        addresses, value_type, records_path = _read_snapshot_addresses(
            project_root=project_root,
            meta_path=meta_path,
            max_records_per_field=max_records_per_field,
        )
        addresses_by_field[field_name] = addresses
        value_type_by_field[field_name] = value_type
        records_by_field[field_name] = records_path
        meta_by_field[field_name] = str(meta_path)

    for field_name in selected_optional_fields:
        raw_meta_path = normalized_optional_meta[field_name].expanduser()
        meta_path = raw_meta_path if raw_meta_path.is_absolute() else (project_root / raw_meta_path).resolve()
        addresses, value_type, records_path = _read_snapshot_addresses(
            project_root=project_root,
            meta_path=meta_path,
            max_records_per_field=max_records_per_field,
        )
        addresses_by_field[field_name] = addresses
        value_type_by_field[field_name] = value_type
        records_by_field[field_name] = records_path
        meta_by_field[field_name] = str(meta_path)

    combination_space = math.prod(len(addresses_by_field[name]) for name in selected_fields)
    candidates: list[Dict[str, Any]] = []
    combination_truncated = False

    for index, combo in enumerate(
        itertools.product(*(addresses_by_field[name] for name in selected_fields)),
        start=1,
    ):
        if len(candidates) >= max_candidates:
            combination_truncated = True
            break

        fields_payload: Dict[str, Any] = {}
        for field_name, address in zip(selected_fields, combo):
            fields_payload[field_name] = {
                "source": "address",
                "type": value_type_by_field[field_name],
                "address": hex(int(address)),
                "relative_to_module": False,
            }

        candidate: Dict[str, Any] = {
            "id": f"{candidate_prefix}_{index}",
            "required_admin": bool(required_admin),
            "fields": fields_payload,
        }
        if profile_id.strip():
            candidate["profile_id"] = profile_id.strip()
        candidates.append(candidate)

    if not candidates:
        raise MemoryProfileError("No calibration candidates were generated from provided snapshots.")

    active_id = active_candidate_id.strip() or candidates[0]["id"]
    payload: Dict[str, Any] = {
        "schema": CALIBRATION_CANDIDATES_SCHEMA_V2,
        "schema_compatibility": [CALIBRATION_CANDIDATES_SCHEMA_V1, CALIBRATION_CANDIDATES_SCHEMA_V2],
        "memory_schema_compatibility": ["live_memory_v1", "live_memory_v2"],
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "required_fields": list(selected_required_fields),
        "optional_fields": list(effective_optional_fields),
        "required_combat_fields": list(selected_required_fields),
        "optional_combat_fields": list(effective_optional_fields),
        "combat_field_sets": {
            "required": list(selected_required_fields),
            "optional": list(effective_optional_fields),
            "optional_with_snapshot_meta": list(selected_optional_fields),
        },
        "source_snapshot_meta_paths": meta_by_field,
        "source_snapshot_records_paths": {name: str(path) for name, path in records_by_field.items()},
        "selected_addresses_per_field": {name: len(addresses_by_field[name]) for name in selected_fields},
        "combination_space": combination_space,
        "combination_truncated": combination_truncated,
        "active_candidate_id": active_id,
        "candidates": candidates,
    }

    recommendation = calibration_candidate_recommendation(
        payload,
        preferred_candidate_id=active_id,
        required_fields=selected_required_fields,
        optional_fields=effective_optional_fields,
    )
    payload["recommended_candidate_id"] = recommendation["recommended_candidate_id"]
    payload["recommended_candidate_support"] = recommendation

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def list_calibration_candidate_summaries(
    calibration_payload: Dict[str, Any],
    *,
    required_fields: Sequence[str] = REQUIRED_MEMORY_FIELDS,
    optional_fields: Sequence[str] = OPTIONAL_COMBAT_FIELDS,
) -> list[Dict[str, Any]]:
    required_combat_fields, optional_combat_fields = resolve_combat_field_sets(
        calibration_payload,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )
    summary_fields = required_combat_fields + tuple(
        name for name in optional_combat_fields if name not in required_combat_fields
    )

    summaries: list[Dict[str, Any]] = []
    for candidate_id, candidate, _ in _iter_candidate_entries(calibration_payload):
        raw_fields = candidate.get("fields")
        fields_payload = raw_fields if isinstance(raw_fields, dict) else {}
        address_map: Dict[str, str] = {}
        for field_name in summary_fields:
            raw_field_payload = fields_payload.get(field_name)
            if isinstance(raw_field_payload, dict) and "address" in raw_field_payload:
                try:
                    address_map[field_name] = _address_to_hex(raw_field_payload.get("address"))
                except MemoryProfileError:
                    address_map[field_name] = str(raw_field_payload.get("address", ""))
            else:
                address_map[field_name] = ""

        quality = _candidate_quality(
            fields_payload=fields_payload,
            required_fields=required_combat_fields,
            optional_fields=optional_combat_fields,
        )
        summaries.append(
            {
                "id": candidate_id,
                "profile_id": str(candidate.get("profile_id", candidate.get("base_profile_id", ""))).strip(),
                "fields": address_map,
                "candidate_quality": quality,
            }
        )

    return summaries


def calibration_candidate_recommendation(
    calibration_payload: Dict[str, Any],
    *,
    preferred_candidate_id: str = "",
    required_fields: Sequence[str] = REQUIRED_MEMORY_FIELDS,
    optional_fields: Sequence[str] = OPTIONAL_COMBAT_FIELDS,
) -> Dict[str, Any]:
    summaries = list_calibration_candidate_summaries(
        calibration_payload,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )
    required_combat_fields, optional_combat_fields = resolve_combat_field_sets(
        calibration_payload,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )
    preferred = preferred_candidate_id.strip()
    active_id = str(
        calibration_payload.get("active_candidate_id", calibration_payload.get("active_candidate", ""))
    ).strip()

    scores: list[Dict[str, Any]] = []
    for index, summary in enumerate(summaries, start=1):
        quality = summary.get("candidate_quality", {})
        resolved_required = int(
            quality.get(
                "resolved_required_count",
                quality.get("resolved_required_fields", 0),
            )
        )
        is_valid = bool(quality.get("valid", False))
        score = {
            "id": summary["id"],
            "valid": is_valid,
            "resolved_required_fields": resolved_required,
            "is_active_candidate": summary["id"] == active_id,
            "original_order": index,
        }
        scores.append(score)

    if not scores:
        raise MemoryProfileError("Calibration payload has no candidate entries.")

    by_id = {item["id"]: item for item in scores}

    recommended_id = ""
    reason = ""
    if preferred and preferred in by_id and bool(by_id[preferred]["valid"]):
        recommended_id = preferred
        reason = "preferred_candidate_valid"
    else:
        max_resolved_required = max(int(item["resolved_required_fields"]) for item in scores)
        contenders = [item for item in scores if int(item["resolved_required_fields"]) == max_resolved_required]
        active_contender = next((item for item in contenders if bool(item["is_active_candidate"])), None)
        if active_contender is not None:
            recommended_id = str(active_contender["id"])
            reason = "max_required_resolved_active_candidate_tiebreak"
        else:
            recommended_id = str(contenders[0]["id"])
            reason = "max_required_resolved_original_order_tiebreak"

    return {
        "algorithm": CALIBRATION_CANDIDATE_ALGORITHM,
        "preferred_candidate_id": preferred,
        "active_candidate_id": active_id,
        "required_combat_fields": list(required_combat_fields),
        "optional_combat_fields": list(optional_combat_fields),
        "recommended_candidate_id": recommended_id,
        "reason": reason,
        "candidate_scores": scores,
    }


def choose_calibration_candidate_id(
    calibration_payload: Dict[str, Any],
    *,
    preferred_candidate_id: str = "",
    required_fields: Sequence[str] = REQUIRED_MEMORY_FIELDS,
    optional_fields: Sequence[str] = OPTIONAL_COMBAT_FIELDS,
) -> str:
    recommendation = calibration_candidate_recommendation(
        calibration_payload,
        preferred_candidate_id=preferred_candidate_id,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )
    selected = str(recommendation.get("recommended_candidate_id", "")).strip()
    if not selected:
        raise MemoryProfileError("Calibration payload has no candidate entries.")
    return selected


def _calibration_project_roots(project_root: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[Path] = set()

    def _add(candidate: Path) -> None:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        roots.append(resolved)

    _add(project_root)
    primary = roots[0]
    if primary.name.lower() == "_internal":
        _add(primary.parent)

    # Bundled EXE layouts often place "_internal" under runtime/dist while
    # worklogs stay in the source project root. Walk a few ancestors to locate
    # nearby project roots automatically without requiring manual absolute paths.
    for base_root in tuple(roots):
        for ancestor in list(base_root.parents)[:6]:
            if (ancestor / "worklogs").exists() or (ancestor / "data" / "versions" / "index.json").exists():
                _add(ancestor)

    return tuple(roots)


def discover_latest_calibration_candidates_path(
    *,
    project_root: Path,
    pattern: str = DEFAULT_CALIBRATION_CANDIDATES_GLOB,
) -> Path:
    roots = _calibration_project_roots(project_root)
    matches: list[Path] = []
    seen_matches: set[Path] = set()

    for root in roots:
        worklogs_root = root / "worklogs"
        if not worklogs_root.exists():
            continue
        for candidate in worklogs_root.rglob(pattern):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved in seen_matches:
                continue
            seen_matches.add(resolved)
            matches.append(resolved)

    if not matches:
        searched = ", ".join(str(root / "worklogs" / pattern) for root in roots)
        raise MemoryProfileError(
            "Calibration file was not provided and auto-discovery found no matches. "
            f"Searched: {searched}"
        )

    def _sort_key(path: Path) -> tuple[int, str]:
        try:
            modified_ns = path.stat().st_mtime_ns
        except OSError:
            modified_ns = -1
        return modified_ns, str(path)

    return max(matches, key=_sort_key)


def resolve_calibration_payload_path(
    calibration_candidates_path: str | None,
    *,
    project_root: Path,
) -> Path:
    raw_value = str(calibration_candidates_path or "").strip()
    if not raw_value:
        return discover_latest_calibration_candidates_path(project_root=project_root)

    raw_path = Path(raw_value).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve()

    candidates = [(root / raw_path).resolve() for root in _calibration_project_roots(project_root)]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_calibration_payload(
    calibration_candidates_path: str | None,
    *,
    project_root: Path,
) -> tuple[Dict[str, Any], Path]:
    raw_path = resolve_calibration_payload_path(
        calibration_candidates_path,
        project_root=project_root,
    )

    if not raw_path.exists():
        raise MemoryProfileError(f"Calibration file not found: {raw_path}")

    try:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MemoryProfileError(f"Calibration file is not valid JSON: {raw_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MemoryProfileError(f"Calibration file must contain a JSON object: {raw_path}")
    return payload, raw_path


def calibration_candidate_ids(
    calibration_payload: Dict[str, Any],
    *,
    required_fields: Sequence[str] = REQUIRED_MEMORY_FIELDS,
    optional_fields: Sequence[str] = OPTIONAL_COMBAT_FIELDS,
) -> list[str]:
    return [
        item["id"]
        for item in list_calibration_candidate_summaries(
            calibration_payload,
            required_fields=required_fields,
            optional_fields=optional_fields,
        )
    ]
