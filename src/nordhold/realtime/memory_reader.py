from __future__ import annotations

import ctypes
import platform
import struct
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

FieldSource = Literal["address", "pointer_chain"]
FieldType = Literal["int32", "uint32", "float32", "float64"]


class MemoryReaderError(RuntimeError):
    """Base exception for memory reader failures."""


class MemoryProfileError(MemoryReaderError):
    """Raised when memory signature profile is malformed or unresolved."""


class ProcessNotFoundError(MemoryReaderError):
    """Raised when target process is not found."""


class MemoryPermissionError(MemoryReaderError):
    """Raised when process handle cannot be opened due permissions."""


class MemoryReadError(MemoryReaderError):
    """Raised when a memory read operation fails."""


SUPPORTED_MEMORY_SIGNATURE_SCHEMAS: tuple[str, ...] = (
    "live_memory_v1",
    "live_memory_v2",
)
DEFAULT_REQUIRED_COMBAT_FIELDS: tuple[str, ...] = ("current_wave", "gold", "essence")
DEFAULT_OPTIONAL_COMBAT_FIELDS: tuple[str, ...] = (
    "lives",
    "player_hp",
    "max_player_hp",
    "enemies_alive",
    "combat_time_s",
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


def _parse_field_names(
    value: Any,
    *,
    label: str,
    fallback: tuple[str, ...],
    allow_empty: bool,
) -> tuple[str, ...]:
    if value is None:
        return fallback

    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        raise MemoryProfileError(
            f"{label} must be a string or list of strings, got {type(value).__name__}."
        )

    out: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_items):
        name = str(item).strip()
        if not name:
            raise MemoryProfileError(f"{label}[{index}] must be non-empty.")
        if name in seen:
            continue
        seen.add(name)
        out.append(name)

    if out:
        return tuple(out)
    if allow_empty:
        return tuple()
    if fallback:
        return fallback
    raise MemoryProfileError(f"{label} must include at least one field.")


def _resolve_combat_field_sets(
    *,
    payload: Dict[str, Any],
    default_required_fields: tuple[str, ...],
    default_optional_fields: tuple[str, ...],
    label_prefix: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    required_fields = _parse_field_names(
        payload.get("required_combat_fields", payload.get("required_fields", None)),
        label=f"{label_prefix}.required_combat_fields",
        fallback=default_required_fields,
        allow_empty=False,
    )
    optional_fields = _parse_field_names(
        payload.get("optional_combat_fields", payload.get("optional_fields", None)),
        label=f"{label_prefix}.optional_combat_fields",
        fallback=default_optional_fields,
        allow_empty=True,
    )
    optional_without_required = tuple(name for name in optional_fields if name not in required_fields)
    return required_fields, optional_without_required


@dataclass(slots=True, frozen=True)
class MemoryFieldSpec:
    name: str
    source: FieldSource
    value_type: FieldType
    address: int = 0
    offsets: tuple[int, ...] = tuple()
    relative_to_module: bool = False

    @classmethod
    def from_dict(cls, name: str, payload: Dict[str, Any]) -> "MemoryFieldSpec":
        source = str(payload.get("source", "address")).strip().lower()
        if source not in {"address", "pointer_chain"}:
            raise MemoryProfileError(
                f"Unsupported field source '{source}' in field '{name}'. Supported: address|pointer_chain."
            )

        value_type = str(payload.get("type", "int32")).strip().lower()
        if value_type not in {"int32", "uint32", "float32", "float64"}:
            raise MemoryProfileError(
                f"Unsupported field type '{value_type}' in field '{name}'. Supported: int32|uint32|float32|float64."
            )

        base_address = payload.get("address", payload.get("base_address", 0))
        address = _parse_int(base_address, f"{name}.address")

        raw_offsets = payload.get("offsets", [])
        offsets = tuple(_parse_int(item, f"{name}.offsets[]") for item in raw_offsets)

        return cls(
            name=name,
            source=source,  # type: ignore[arg-type]
            value_type=value_type,  # type: ignore[arg-type]
            address=address,
            offsets=offsets,
            relative_to_module=bool(payload.get("relative_to_module", False)),
        )

    @property
    def resolved(self) -> bool:
        # In this context address==0 means signature was not resolved yet.
        return self.address != 0


@dataclass(slots=True, frozen=True)
class MemoryProfile:
    id: str
    process_name: str
    module_name: str
    poll_ms: int
    required_admin: bool
    pointer_size: int
    required_combat_fields: tuple[str, ...]
    optional_combat_fields: tuple[str, ...]
    fields: Dict[str, MemoryFieldSpec]

    @classmethod
    def from_dict(
        cls,
        payload: Dict[str, Any],
        default_process_name: str,
        *,
        default_required_combat_fields: tuple[str, ...] = DEFAULT_REQUIRED_COMBAT_FIELDS,
        default_optional_combat_fields: tuple[str, ...] = DEFAULT_OPTIONAL_COMBAT_FIELDS,
    ) -> "MemoryProfile":
        profile_id = str(payload.get("id", "")).strip()
        if not profile_id:
            raise MemoryProfileError("Signature profile missing non-empty 'id'.")

        process_name = str(payload.get("process_name", default_process_name)).strip() or default_process_name
        module_name = str(payload.get("module_name", process_name)).strip() or process_name
        poll_ms = max(200, int(payload.get("poll_ms", 1000)))
        required_admin = bool(payload.get("required_admin", True))
        pointer_size = int(payload.get("pointer_size", payload.get("pointer_size_bytes", 0)) or 0)
        if pointer_size not in {0, 4, 8}:
            raise MemoryProfileError(
                f"Signature profile '{profile_id}' has invalid pointer_size={pointer_size}; expected 4 or 8."
            )

        raw_fields = payload.get("fields")
        if not isinstance(raw_fields, dict) or not raw_fields:
            raise MemoryProfileError(f"Signature profile '{profile_id}' has empty or invalid 'fields'.")

        fields: Dict[str, MemoryFieldSpec] = {}
        for field_name, field_payload in raw_fields.items():
            if not isinstance(field_payload, dict):
                raise MemoryProfileError(f"Field '{field_name}' in profile '{profile_id}' must be an object.")
            fields[str(field_name)] = MemoryFieldSpec.from_dict(str(field_name), field_payload)

        required_combat_fields, optional_combat_fields = _resolve_combat_field_sets(
            payload=payload,
            default_required_fields=default_required_combat_fields,
            default_optional_fields=default_optional_combat_fields,
            label_prefix=f"profile '{profile_id}'",
        )

        return cls(
            id=profile_id,
            process_name=process_name,
            module_name=module_name,
            poll_ms=poll_ms,
            required_admin=required_admin,
            pointer_size=pointer_size,
            required_combat_fields=required_combat_fields,
            optional_combat_fields=optional_combat_fields,
            fields=fields,
        )

    def ensure_required_fields(self, required: Optional[tuple[str, ...]] = None) -> None:
        fields = required if required is not None else self.required_combat_fields
        missing = [name for name in fields if name not in self.fields]
        if missing:
            raise MemoryProfileError(f"Signature profile '{self.id}' missing required fields: {', '.join(missing)}")

    def ensure_resolved(self, required: Optional[tuple[str, ...]] = None) -> None:
        fields = required if required is not None else self.required_combat_fields
        self.ensure_required_fields(required=fields)
        unresolved = [name for name in fields if not self.fields[name].resolved]
        if unresolved:
            raise MemoryProfileError(
                f"Signature profile '{self.id}' unresolved fields: {', '.join(unresolved)}"
            )


def load_memory_profile(
    signatures_payload: Dict[str, Any],
    process_name: str,
    profile_id: str = "",
) -> MemoryProfile:
    if not isinstance(signatures_payload, dict):
        raise MemoryProfileError("memory_signatures payload must be a JSON object.")

    schema_version = str(signatures_payload.get("schema_version", "live_memory_v1")).strip() or "live_memory_v1"
    if schema_version not in SUPPORTED_MEMORY_SIGNATURE_SCHEMAS:
        raise MemoryProfileError(
            f"Unsupported memory_signatures schema_version '{schema_version}'. "
            f"Supported: {', '.join(SUPPORTED_MEMORY_SIGNATURE_SCHEMAS)}"
        )

    default_required_fields, default_optional_fields = _resolve_combat_field_sets(
        payload=signatures_payload,
        default_required_fields=DEFAULT_REQUIRED_COMBAT_FIELDS,
        default_optional_fields=DEFAULT_OPTIONAL_COMBAT_FIELDS,
        label_prefix=f"memory_signatures[{schema_version}]",
    )

    raw_profiles = signatures_payload.get("profiles", [])
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise MemoryProfileError("memory_signatures payload has no profiles.")

    parsed_profiles: list[MemoryProfile] = []
    for item in raw_profiles:
        if not isinstance(item, dict):
            continue
        parsed_profiles.append(
            MemoryProfile.from_dict(
                item,
                default_process_name=process_name,
                default_required_combat_fields=default_required_fields,
                default_optional_combat_fields=default_optional_fields,
            )
        )

    if not parsed_profiles:
        raise MemoryProfileError("memory_signatures payload contains no valid profiles.")

    if profile_id:
        for profile in parsed_profiles:
            if profile.id == profile_id:
                return profile
        raise MemoryProfileError(f"Requested signature profile not found: {profile_id}")

    requested = process_name.strip().lower()
    if requested:
        for profile in parsed_profiles:
            if profile.process_name.strip().lower() == requested:
                return profile

    return parsed_profiles[0]


def _parse_pointer_size(value: Any, label: str) -> int:
    pointer_size = _parse_int(value, label)
    if pointer_size not in {0, 4, 8}:
        raise MemoryProfileError(f"Invalid pointer_size for {label}: {pointer_size}; expected 4 or 8.")
    return pointer_size


def _field_payload_from_spec(spec: MemoryFieldSpec) -> Dict[str, Any]:
    return {
        "source": spec.source,
        "type": spec.value_type,
        "address": spec.address,
        "offsets": list(spec.offsets),
        "relative_to_module": spec.relative_to_module,
    }


def _candidate_target_profile(candidate_payload: Dict[str, Any]) -> str:
    return str(candidate_payload.get("profile_id", candidate_payload.get("base_profile_id", ""))).strip()


def apply_calibration_candidate(
    base_profile: MemoryProfile,
    calibration_payload: Dict[str, Any],
    candidate_id: str = "",
) -> tuple[MemoryProfile, str]:
    if not isinstance(calibration_payload, dict):
        raise MemoryProfileError("Calibration payload must be an object.")

    raw_candidates = calibration_payload.get("candidates", [])
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise MemoryProfileError("Calibration payload has no candidates.")

    candidates: list[tuple[str, Dict[str, Any]]] = []
    seen_ids: set[str] = set()
    for index, raw_candidate in enumerate(raw_candidates, start=1):
        if not isinstance(raw_candidate, dict):
            continue
        cid = str(raw_candidate.get("id", "")).strip() or f"candidate_{index}"
        if cid in seen_ids:
            raise MemoryProfileError(f"Calibration payload has duplicate candidate id: {cid}")
        seen_ids.add(cid)
        candidates.append((cid, raw_candidate))

    if not candidates:
        raise MemoryProfileError("Calibration payload has no valid candidate objects.")

    compatible_by_id: Dict[str, Dict[str, Any]] = {}
    compatible_list: list[Dict[str, Any]] = []
    for cid, payload in candidates:
        target_profile = _candidate_target_profile(payload)
        if target_profile and target_profile != base_profile.id:
            continue
        candidate_payload = dict(payload)
        candidate_payload["id"] = cid
        compatible_by_id[cid] = payload
        compatible_list.append(candidate_payload)

    if not compatible_list:
        raise MemoryProfileError(
            f"Calibration payload has no candidates compatible with active profile '{base_profile.id}'."
        )

    active_candidate_id = str(
        calibration_payload.get("active_candidate_id", calibration_payload.get("active_candidate", ""))
    ).strip()
    requested_id = candidate_id.strip()

    from .calibration_candidates import choose_calibration_candidate_id

    selected_id = choose_calibration_candidate_id(
        {
            "active_candidate_id": active_candidate_id,
            "candidates": compatible_list,
        },
        preferred_candidate_id=requested_id,
        required_fields=base_profile.required_combat_fields,
        optional_fields=base_profile.optional_combat_fields,
    )
    selected_payload = compatible_by_id[selected_id]

    raw_fields = selected_payload.get("fields")
    if not isinstance(raw_fields, dict) or not raw_fields:
        raise MemoryProfileError(f"Calibration candidate '{selected_id}' has empty or invalid 'fields'.")

    merged_fields: Dict[str, MemoryFieldSpec] = {}
    for field_name, base_spec in base_profile.fields.items():
        override = raw_fields.get(field_name)
        if override is None:
            merged_fields[field_name] = base_spec
            continue
        if not isinstance(override, dict):
            raise MemoryProfileError(
                f"Calibration candidate '{selected_id}' field override '{field_name}' must be an object."
            )
        merged_payload = _field_payload_from_spec(base_spec)
        merged_payload.update(override)
        merged_fields[field_name] = MemoryFieldSpec.from_dict(field_name, merged_payload)

    for field_name, override in raw_fields.items():
        name = str(field_name)
        if name in merged_fields:
            continue
        if not isinstance(override, dict):
            raise MemoryProfileError(
                f"Calibration candidate '{selected_id}' field override '{name}' must be an object."
            )
        merged_fields[name] = MemoryFieldSpec.from_dict(name, override)

    raw_pointer_size = selected_payload.get("pointer_size", selected_payload.get("pointer_size_bytes", None))
    pointer_size = base_profile.pointer_size
    if raw_pointer_size is not None:
        pointer_size = _parse_pointer_size(raw_pointer_size, f"candidate '{selected_id}'.pointer_size")

    raw_poll_ms = selected_payload.get("poll_ms", base_profile.poll_ms)
    poll_ms = max(200, _parse_int(raw_poll_ms, f"candidate '{selected_id}'.poll_ms"))

    process_name = str(selected_payload.get("process_name", base_profile.process_name)).strip() or base_profile.process_name
    module_name = str(selected_payload.get("module_name", base_profile.module_name)).strip() or base_profile.module_name
    required_admin = bool(selected_payload.get("required_admin", base_profile.required_admin))
    profile_id = str(selected_payload.get("result_profile_id", "")).strip() or f"{base_profile.id}@{selected_id}"
    required_combat_fields, optional_combat_fields = _resolve_combat_field_sets(
        payload=selected_payload,
        default_required_fields=base_profile.required_combat_fields,
        default_optional_fields=base_profile.optional_combat_fields,
        label_prefix=f"candidate '{selected_id}'",
    )

    calibrated_profile = MemoryProfile(
        id=profile_id,
        process_name=process_name,
        module_name=module_name,
        poll_ms=poll_ms,
        required_admin=required_admin,
        pointer_size=pointer_size,
        required_combat_fields=required_combat_fields,
        optional_combat_fields=optional_combat_fields,
        fields=merged_fields,
    )
    return calibrated_profile, selected_id


def _value_size(value_type: FieldType) -> int:
    if value_type in {"int32", "uint32", "float32"}:
        return 4
    if value_type == "float64":
        return 8
    raise MemoryProfileError(f"Unsupported value type: {value_type}")


def _decode_value(payload: bytes, value_type: FieldType) -> float | int:
    if value_type == "int32":
        return struct.unpack("<i", payload)[0]
    if value_type == "uint32":
        return struct.unpack("<I", payload)[0]
    if value_type == "float32":
        return struct.unpack("<f", payload)[0]
    if value_type == "float64":
        return struct.unpack("<d", payload)[0]
    raise MemoryProfileError(f"Unsupported value type: {value_type}")


class WindowsMemoryBackend:
    PROCESS_VM_READ = 0x0010
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self):
        self._system = platform.system().lower()
        self._kernel32 = None
        if self._system == "windows":
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def supports_memory_read(self) -> bool:
        return self._system == "windows" and self._kernel32 is not None

    def find_process_id(self, process_name: str) -> Optional[int]:
        name = process_name.replace(".exe", "").strip()
        if not name:
            return None
        safe_name = name.replace("'", "''")
        try:
            output = subprocess.check_output(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    f"Get-Process -Name '{safe_name}' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id",
                ],
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception:
            return None
        text = output.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    def open_process(self, pid: int) -> int:
        if self._kernel32 is None:
            raise MemoryReaderError("kernel32 is unavailable.")
        access = self.PROCESS_VM_READ | self.PROCESS_QUERY_INFORMATION | self.PROCESS_QUERY_LIMITED_INFORMATION
        handle = self._kernel32.OpenProcess(access, False, pid)
        if not handle:
            winerr = ctypes.get_last_error()
            raise MemoryPermissionError(f"OpenProcess failed for pid={pid}, winerr={winerr}")
        return int(handle)

    def close_process(self, handle: int) -> None:
        if self._kernel32 is None or not handle:
            return
        self._kernel32.CloseHandle(ctypes.c_void_p(handle))

    def read_memory(self, handle: int, address: int, size: int) -> bytes:
        if self._kernel32 is None:
            raise MemoryReaderError("kernel32 is unavailable.")
        if address <= 0:
            raise MemoryReadError(f"Invalid read address: {hex(address)}")
        buffer = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t(0)
        ok = self._kernel32.ReadProcessMemory(
            ctypes.c_void_p(handle),
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read),
        )
        if not ok or read.value != size:
            winerr = ctypes.get_last_error()
            raise MemoryReadError(
                f"ReadProcessMemory failed: addr={hex(address)} size={size} read={read.value} winerr={winerr}"
            )
        return buffer.raw[:size]

    def get_module_base(self, pid: int, module_name: str) -> Optional[int]:
        safe_module_name = module_name.replace("'", "''")
        try:
            output = subprocess.check_output(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "$p=Get-Process -Id "
                        f"{pid} -ErrorAction SilentlyContinue; "
                        "if ($p) { "
                        "$m = $p.Modules | Where-Object { $_.ModuleName -eq "
                        f"'{safe_module_name}'" " } | Select-Object -First 1; "
                        "if ($m) { $m.BaseAddress } "
                        "}"
                    ),
                ],
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception:
            return None

        text = output.strip()
        if not text:
            return None

        for candidate in (text, text.lower()):
            try:
                return int(candidate, 0)
            except ValueError:
                continue
        return None


class MemoryReader:
    def __init__(self, backend: Optional[Any] = None):
        self.backend = backend or WindowsMemoryBackend()
        self.handle: int = 0
        self.pid: int = 0
        self.module_base: int = 0
        self.native_pointer_size = struct.calcsize("P")
        self.pointer_size = self.native_pointer_size

    @property
    def connected(self) -> bool:
        return self.handle != 0

    def open(self, process_name: str, profile: MemoryProfile) -> None:
        self.close()
        self.pointer_size = self.native_pointer_size

        if not self.backend.supports_memory_read():
            raise MemoryReaderError("memory_reader_not_supported_platform")

        pid = self.backend.find_process_id(process_name or profile.process_name)
        if pid is None:
            raise ProcessNotFoundError(f"Process not found: {process_name or profile.process_name}")

        handle = self.backend.open_process(pid)
        module_base = 0
        if profile.module_name:
            base = self.backend.get_module_base(pid, profile.module_name)
            module_base = int(base or 0)

        self.pid = pid
        self.handle = handle
        self.module_base = module_base
        if profile.pointer_size in {4, 8}:
            self.pointer_size = profile.pointer_size

    def close(self) -> None:
        if self.handle:
            try:
                self.backend.close_process(self.handle)
            except Exception:
                pass
        self.handle = 0
        self.pid = 0
        self.module_base = 0
        self.pointer_size = self.native_pointer_size

    def _read_pointer(self, address: int) -> int:
        raw = self.backend.read_memory(self.handle, address, self.pointer_size)
        if self.pointer_size == 8:
            return int(struct.unpack("<Q", raw)[0])
        return int(struct.unpack("<I", raw)[0])

    def _resolve_address(self, spec: MemoryFieldSpec) -> int:
        address = int(spec.address)
        if spec.relative_to_module:
            address += int(self.module_base)

        if spec.source == "address":
            return address

        if spec.source == "pointer_chain":
            if not spec.offsets:
                return self._read_pointer(address)
            current = address
            for offset in spec.offsets:
                ptr = self._read_pointer(current)
                current = int(ptr + offset)
            return current

        raise MemoryProfileError(f"Unsupported field source: {spec.source}")

    def read_fields(self, profile: MemoryProfile) -> Dict[str, float | int]:
        if not self.connected:
            raise MemoryReaderError("memory_reader_not_connected")

        values: Dict[str, float | int] = {}
        for name, spec in profile.fields.items():
            address = self._resolve_address(spec)
            size = _value_size(spec.value_type)
            raw = self.backend.read_memory(self.handle, address, size)
            values[name] = _decode_value(raw, spec.value_type)
        return values
