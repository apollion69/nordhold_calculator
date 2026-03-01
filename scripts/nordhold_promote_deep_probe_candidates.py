#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import hashlib
from datetime import datetime, timezone
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nordhold.realtime.calibration_candidates import (
    OPTIONAL_COMBAT_FIELDS,
    REQUIRED_MEMORY_FIELDS,
    build_calibration_candidates_from_snapshots,
    calibration_candidate_recommendation,
    resolve_combat_field_sets,
)

WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(slots=True, frozen=True)
class PromotionInputs:
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    required_snapshot_meta_paths: dict[str, Path]
    optional_snapshot_meta_paths: dict[str, Path]
    profile_id: str
    active_candidate_id: str
    selected_optional_fields: tuple[str, ...]


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def _hash_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(131072)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _iter_path_candidates(raw_path: str, *, base_paths: tuple[Path, ...]) -> list[Path]:
    text = str(raw_path).strip()
    if not text:
        return []

    normalized = text.replace("\\", "/")
    out: list[Path] = []
    seen: set[Path] = set()

    def _append(candidate: Path) -> None:
        expanded = candidate.expanduser()
        if not expanded.is_absolute():
            return
        resolved = expanded.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        out.append(resolved)

    given = Path(text).expanduser()
    if given.is_absolute():
        _append(given)

    normalized_path = Path(normalized).expanduser()
    if normalized_path.is_absolute():
        _append(normalized_path)

    if WINDOWS_ABS_PATH_RE.match(text):
        drive = text[0].lower()
        tail = normalized[2:].lstrip("/")
        _append(Path(f"/mnt/{drive}/{tail}"))

    for base in base_paths:
        base_resolved = base.expanduser().resolve()
        rel_given = Path(text).expanduser()
        if not rel_given.is_absolute():
            _append(base_resolved / rel_given)
        rel_normalized = Path(normalized).expanduser()
        if not rel_normalized.is_absolute():
            _append(base_resolved / rel_normalized)

    return out


def _resolve_existing_path(raw_path: str, *, label: str, base_paths: tuple[Path, ...]) -> Path:
    candidates = _iter_path_candidates(raw_path, base_paths=base_paths)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    tried = ", ".join(str(item) for item in candidates) if candidates else "<none>"
    raise ValueError(f"{label} was not found. Tried: {tried}")


def _resolve_probe_source_path(
    *,
    report_payload: dict[str, Any],
    report_path: Path,
    project_root: Path,
    override: str,
) -> Path:
    raw_source = override.strip() if override.strip() else str(report_payload.get("candidate_source_path", "")).strip()
    if not raw_source:
        raise ValueError(
            "Probe report does not provide 'candidate_source_path'. "
            "Set --candidate-source explicitly."
        )
    return _resolve_existing_path(
        raw_source,
        label="candidate source payload",
        base_paths=(Path.cwd(), report_path.parent, project_root),
    )


def _string_map(payload: Any, *, label: str) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object.")
    out: dict[str, str] = {}
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip()
        if not key:
            continue
        value = str(raw_value).strip()
        if not value:
            continue
        out[key] = value
    return out


def _selected_meta_from_report(report_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summary = report_payload.get("summary", {})
    if not isinstance(summary, dict):
        raise ValueError("Probe report field 'summary' must be an object.")
    selected = summary.get("selected_meta", {})
    if selected in ("", None):
        return {}
    if not isinstance(selected, dict):
        raise ValueError("Probe report field 'summary.selected_meta' must be an object.")
    out: dict[str, dict[str, Any]] = {}
    for raw_field, raw_item in selected.items():
        field_name = str(raw_field).strip()
        if not field_name:
            continue
        if not isinstance(raw_item, dict):
            raise ValueError(
                f"Probe report selected_meta entry for field '{field_name}' must be an object."
            )
        out[field_name] = raw_item
    return out


def _extract_profile_id(
    source_payload: dict[str, Any],
    *,
    preferred_candidate_ids: tuple[str, ...],
) -> str:
    profile_id = str(source_payload.get("profile_id", "")).strip()
    if profile_id:
        return profile_id

    raw_candidates = source_payload.get("candidates", [])
    if not isinstance(raw_candidates, list):
        return ""

    by_id: dict[str, dict[str, Any]] = {}
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("id", "")).strip()
        if candidate_id:
            by_id[candidate_id] = item

    for candidate_id in preferred_candidate_ids:
        candidate = by_id.get(candidate_id)
        if not isinstance(candidate, dict):
            continue
        preferred_profile = str(
            candidate.get("profile_id", candidate.get("base_profile_id", ""))
        ).strip()
        if preferred_profile:
            return preferred_profile

    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        candidate_profile = str(item.get("profile_id", item.get("base_profile_id", ""))).strip()
        if candidate_profile:
            return candidate_profile
    return ""


def _candidate_has_required_addresses(
    candidate: dict[str, Any],
    *,
    required_fields: tuple[str, ...],
) -> bool:
    raw_fields = candidate.get("fields", {})
    if not isinstance(raw_fields, dict):
        return False
    for field_name in required_fields:
        field_payload = raw_fields.get(field_name)
        if not isinstance(field_payload, dict):
            return False
        if "address" not in field_payload:
            return False
        raw_address = str(field_payload.get("address", "")).strip()
        if not raw_address:
            return False
        try:
            if int(raw_address, 0) <= 0:
                return False
        except ValueError:
            return False
    return True


def _normalize_candidates_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    raw_candidates = payload.get("candidates", [])
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("Generated payload does not contain candidates.")
    normalized: list[dict[str, Any]] = []
    candidate_ids: list[str] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        normalized.append(item)
        candidate_id = str(item.get("id", "")).strip()
        if candidate_id:
            candidate_ids.append(candidate_id)
    if not normalized:
        raise ValueError("Generated payload has no candidate dictionary entries.")
    return normalized, candidate_ids


def _pick_source_legacy_candidate(
    source_payload: dict[str, Any],
    report_payload: dict[str, Any],
    *,
    required_fields: tuple[str, ...],
) -> str:
    candidates = _iter_candidate_payloads(source_payload.get("candidates", []))
    if not candidates:
        raise ValueError("Source payload has no legacy candidates.")

    preferred = [
        str(report_payload.get("selected_candidate_id", "")).strip(),
        str(report_payload.get("candidate_id", "")).strip(),
        str(report_payload.get("winner_candidate_id", "")).strip(),
        str(source_payload.get("active_candidate_id", source_payload.get("active_candidate", ""))).strip(),
        str(source_payload.get("recommended_candidate_id", "")).strip(),
        str(report_payload.get("selected", "")),
    ]
    for candidate_id in preferred:
        if not candidate_id:
            continue
        candidate = candidates.get(candidate_id)
        if candidate and _candidate_has_required_addresses(candidate, required_fields=required_fields):
            return candidate_id

    for candidate_id, candidate in candidates.items():
        if _candidate_has_required_addresses(candidate, required_fields=required_fields):
            return candidate_id
    raise ValueError("Source legacy payload has no candidate with resolved required fields.")


def _iter_candidate_payloads(raw_candidates: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_candidates, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("id", "")).strip()
        if not candidate_id:
            continue
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        out[candidate_id] = item
    return out


def _source_payload_has_refresh_meta(
    source_payload: dict[str, Any],
    required_fields: tuple[str, ...],
) -> bool:
    try:
        raw_meta_paths = _string_map(
            source_payload.get("source_snapshot_meta_paths", {}),
            label="Source payload field 'source_snapshot_meta_paths'",
        )
    except ValueError:
        return False
    for field_name in required_fields:
        if not raw_meta_paths.get(field_name, "").strip():
            return False
    return True


def _build_legacy_promoted_payload(
    *,
    source_payload: dict[str, Any],
    report_payload: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    required_fields, optional_fields = resolve_combat_field_sets(
        source_payload,
        required_fields=REQUIRED_MEMORY_FIELDS,
        optional_fields=OPTIONAL_COMBAT_FIELDS,
    )
    raw_candidates = source_payload.get("candidates", [])
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("Source payload has no legacy candidates.")

    normalized_candidates, candidate_ids = _normalize_candidates_payload(source_payload)

    preferred_candidate_id = _pick_source_legacy_candidate(
        source_payload,
        report_payload,
        required_fields=required_fields,
    )
    if not preferred_candidate_id:
        preferred_candidate_id = candidate_ids[0]

    payload: dict[str, Any] = {
        **{key: value for key, value in source_payload.items()},
        "required_fields": list(required_fields),
        "optional_fields": list(optional_fields),
        "required_combat_fields": list(required_fields),
        "optional_combat_fields": list(optional_fields),
        "combat_field_sets": {
            "required": list(required_fields),
            "optional": list(optional_fields),
            "optional_with_snapshot_meta": [],
        },
        "active_candidate_id": preferred_candidate_id,
        "candidates": normalized_candidates,
    }
    payload["generated_at_utc"] = _now_utc()
    payload["generated_at"] = payload["generated_at_utc"]

    recommendation = calibration_candidate_recommendation(
        payload,
        preferred_candidate_id=preferred_candidate_id,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )
    payload["recommended_candidate_id"] = recommendation["recommended_candidate_id"]
    payload["recommended_candidate_support"] = recommendation
    payload.setdefault("schema", "nordhold_memory_calibration_candidates_v2")
    payload.setdefault(
        "schema_compatibility",
        ["nordhold_memory_calibration_candidates_v1", "nordhold_memory_calibration_candidates_v2"],
    )
    payload.setdefault("memory_schema_compatibility", ["live_memory_v1", "live_memory_v2"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _build_promotion_inputs(
    *,
    report_payload: dict[str, Any],
    report_path: Path,
    source_payload: dict[str, Any],
    source_payload_path: Path,
    project_root: Path,
    active_candidate_id_override: str,
) -> PromotionInputs:
    required_fields, optional_fields = resolve_combat_field_sets(
        source_payload,
        required_fields=REQUIRED_MEMORY_FIELDS,
        optional_fields=OPTIONAL_COMBAT_FIELDS,
    )

    raw_meta_paths = _string_map(
        source_payload.get("source_snapshot_meta_paths", {}),
        label="Source payload field 'source_snapshot_meta_paths'",
    )

    path_base = (Path.cwd(), report_path.parent, source_payload_path.parent, project_root)
    required_meta_paths: dict[str, Path] = {}
    missing_required: list[str] = []
    for field_name in required_fields:
        raw_path = raw_meta_paths.get(field_name, "")
        if not raw_path:
            missing_required.append(field_name)
            continue
        try:
            required_meta_paths[field_name] = _resolve_existing_path(
                raw_path,
                label=f"Required field '{field_name}' snapshot meta path",
                base_paths=path_base,
            )
        except ValueError:
            missing_required.append(field_name)

    if missing_required:
        joined = ", ".join(missing_required)
        raise ValueError(
            "Missing required snapshot meta path(s) in source payload "
            f"'source_snapshot_meta_paths': {joined}"
        )

    optional_meta_paths: dict[str, Path] = {}
    for field_name in optional_fields:
        raw_path = raw_meta_paths.get(field_name, "")
        if not raw_path:
            continue
        try:
            optional_meta_paths[field_name] = _resolve_existing_path(
                raw_path,
                label=f"Optional field '{field_name}' snapshot meta path",
                base_paths=path_base,
            )
        except ValueError:
            continue

    selected_optional_fields: list[str] = []
    for field_name, selected_entry in _selected_meta_from_report(report_payload).items():
        if field_name in required_fields:
            raise ValueError(
                f"Probe report selected optional field '{field_name}' conflicts with required fields."
            )
        raw_meta_path = str(selected_entry.get("meta_path", "")).strip()
        if not raw_meta_path:
            raise ValueError(
                f"Probe report selected_meta entry '{field_name}' has empty 'meta_path'."
            )
        optional_meta_paths[field_name] = _resolve_existing_path(
            raw_meta_path,
            label=f"Probe-selected field '{field_name}' snapshot meta path",
            base_paths=path_base,
        )
        selected_optional_fields.append(field_name)

    selected_unique = tuple(dict.fromkeys(selected_optional_fields))
    merged_optional_fields = tuple(dict.fromkeys((*optional_fields, *selected_unique)))
    source_active = str(
        source_payload.get("active_candidate_id", source_payload.get("active_candidate", ""))
    ).strip()
    source_recommended = str(source_payload.get("recommended_candidate_id", "")).strip()
    active_candidate_id = active_candidate_id_override.strip() or source_active or source_recommended
    profile_id = _extract_profile_id(
        source_payload,
        preferred_candidate_ids=(active_candidate_id, source_active, source_recommended),
    )

    return PromotionInputs(
        required_fields=required_fields,
        optional_fields=merged_optional_fields,
        required_snapshot_meta_paths=required_meta_paths,
        optional_snapshot_meta_paths=optional_meta_paths,
        profile_id=profile_id,
        active_candidate_id=active_candidate_id,
        selected_optional_fields=selected_unique,
    )


def _ensure_active_candidate_fallback(
    *,
    payload: dict[str, Any],
    output_path: Path,
    required_fields: tuple[str, ...],
    optional_fields: tuple[str, ...],
) -> dict[str, Any]:
    raw_candidates = payload.get("candidates", [])
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("Generated payload does not contain candidates.")

    candidate_ids = [str(item.get("id", "")).strip() for item in raw_candidates if isinstance(item, dict)]
    candidate_ids = [item for item in candidate_ids if item]
    if not candidate_ids:
        raise ValueError("Generated payload has no candidate ids.")

    active_id = str(payload.get("active_candidate_id", "")).strip()
    if active_id and active_id in candidate_ids:
        return payload

    fallback_id = candidate_ids[0]
    payload["active_candidate_id"] = fallback_id
    recommendation = calibration_candidate_recommendation(
        payload,
        preferred_candidate_id=fallback_id,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )
    payload["recommended_candidate_id"] = recommendation["recommended_candidate_id"]
    payload["recommended_candidate_support"] = recommendation
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _extract_dataset_field(payload: dict[str, Any], *, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(payload.get(key, "")).strip()
        if value:
            return value
    return ""


def _apply_refresh_metadata(
    payload: dict[str, Any],
    *,
    source_payload: dict[str, Any],
    report_payload: dict[str, Any],
    source_path: Path,
    report_path: Path,
    output_path: Path,
) -> None:
    build_id = _extract_dataset_field(source_payload, keys=("build_id", "game_build"))
    dataset_version = _extract_dataset_field(source_payload, keys=("dataset_version", "game_dataset_version"))
    refresh_timestamp = _now_utc()
    metadata = {
        "generated_at": refresh_timestamp,
        "generated_at_utc": refresh_timestamp,
        "dataset_version": dataset_version,
        "build_id": build_id,
        "build": build_id,
        "game_version": dataset_version,
        "source_candidates_path": str(source_path),
        "source_payload_hash_sha256": _hash_sha256(source_path),
        "source_report_path": str(report_path),
        "probe_report_hash_sha256": _hash_sha256(report_path),
        "probe_runtime": _extract_dataset_field(report_payload, keys=("runtime_version", "runtime", "script_version")),
    }
    payload["refresh_metadata"] = metadata
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["refresh_metadata"]["refreshed_candidates_hash_sha256"] = _hash_sha256(output_path)
    payload["hash"] = _hash_sha256(output_path)
    payload["generated_at"] = refresh_timestamp
    payload["generated_at_utc"] = refresh_timestamp
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Promote deep-probe optional fields by rebuilding calibration candidates "
            "from source snapshot metadata plus probe-selected metadata."
        )
    )
    parser.add_argument(
        "--probe-report",
        type=Path,
        required=True,
        help="Path to combat_deep_probe_*_report.json.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output candidates JSON path.",
    )
    parser.add_argument(
        "--candidate-source",
        default="",
        help="Optional override path to source candidates payload. Defaults to report.candidate_source_path.",
    )
    parser.add_argument(
        "--active-candidate-id",
        default="",
        help="Optional active candidate id override.",
    )
    parser.add_argument(
        "--max-per-field",
        type=int,
        default=4,
        help="Maximum addresses per field snapshot.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=256,
        help="Maximum generated candidates.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.max_per_field <= 0:
        parser.error("--max-per-field must be > 0")
    if args.max_candidates <= 0:
        parser.error("--max-candidates must be > 0")

    try:
        project_root = Path(__file__).resolve().parents[1]
        report_path = args.probe_report.expanduser().resolve()
        output_path = args.out.expanduser().resolve()

        report_payload = _read_json_object(report_path, label="Probe report")
        source_payload_path = _resolve_probe_source_path(
            report_payload=report_payload,
            report_path=report_path,
            project_root=project_root,
            override=str(args.candidate_source),
        )
        source_payload = _read_json_object(source_payload_path, label="Source candidates payload")

        required_fields, optional_fields = resolve_combat_field_sets(
            source_payload,
            required_fields=REQUIRED_MEMORY_FIELDS,
            optional_fields=OPTIONAL_COMBAT_FIELDS,
        )
        use_snapshot_build = _source_payload_has_refresh_meta(
            source_payload,
            required_fields=required_fields,
        )
        selected_optional_text = ""

        if use_snapshot_build:
            try:
                inputs = _build_promotion_inputs(
                    report_payload=report_payload,
                    report_path=report_path,
                    source_payload=source_payload,
                    source_payload_path=source_payload_path,
                    project_root=project_root,
                    active_candidate_id_override=str(args.active_candidate_id),
                )
                payload = build_calibration_candidates_from_snapshots(
                    project_root=project_root,
                    field_snapshot_meta_paths=inputs.required_snapshot_meta_paths,
                    output_path=output_path,
                    profile_id=inputs.profile_id,
                    max_records_per_field=int(args.max_per_field),
                    max_candidates=int(args.max_candidates),
                    active_candidate_id=inputs.active_candidate_id,
                    required_fields=inputs.required_fields,
                    optional_fields=inputs.optional_fields,
                    optional_field_snapshot_meta_paths=inputs.optional_snapshot_meta_paths,
                )
                selected_optional_text = ",".join(inputs.selected_optional_fields)
            except ValueError as exc:
                if "Missing required snapshot meta path(s) in source payload 'source_snapshot_meta_paths'" not in str(exc):
                    raise
                use_snapshot_build = False

        if not use_snapshot_build:
            payload = _build_legacy_promoted_payload(
                source_payload=source_payload,
                report_payload=report_payload,
                output_path=output_path,
            )
        payload = _ensure_active_candidate_fallback(
            payload=payload,
            output_path=output_path,
            required_fields=required_fields,
            optional_fields=optional_fields,
        )
        _apply_refresh_metadata(
            payload=payload,
            source_payload=source_payload,
            report_payload=report_payload,
            source_path=source_payload_path,
            report_path=report_path,
            output_path=output_path,
        )

        print(f"output={output_path}")
        print(f"candidates={len(payload.get('candidates', []))}")
        print(f"combination_space={payload.get('combination_space', 0)}")
        print(f"selected_optional_fields={selected_optional_text}")
        print(f"active_candidate_id={payload.get('active_candidate_id', '')}")
        print(f"recommended_candidate_id={payload.get('recommended_candidate_id', '')}")
        return 0
    except Exception as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
