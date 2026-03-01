from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .calibration_candidates import (
    REQUIRED_MEMORY_FIELDS,
    calibration_candidate_recommendation,
    calibration_candidate_ids,
    choose_calibration_candidate_id,
    list_calibration_candidate_summaries,
    load_calibration_payload,
)
from .catalog import CatalogRepository
from .memory_reader import (
    MemoryProfile,
    MemoryProfileError,
    MemoryReader,
    MemoryReaderError,
    apply_calibration_candidate,
    load_memory_profile,
)
from .models import LiveSnapshot
from .replay import ReplayError, ReplayStore


class LiveBridgeError(RuntimeError):
    """Raised on live bridge connection or snapshot failures."""


OPTIONAL_MEMORY_FIELD_ALIASES: Dict[str, tuple[str, ...]] = {
    "combat_block_value": (
        "combat_block_value",
        "combat_block",
        "block_value",
        "block",
    ),
    "combat_block_percent": (
        "combat_block_percent",
        "combat_block_pct",
        "block_percent",
        "block_pct",
    ),
    "combat_block_flat": (
        "combat_block_flat",
        "combat_block_amount",
        "block_flat",
        "block_amount",
    ),
}

LIVE_RAW_MEMORY_NUMERIC_FIELDS: tuple[str, ...] = (
    "current_wave",
    "gold",
    "essence",
    "wood",
    "stone",
    "wheat",
    "workers_total",
    "workers_free",
    "tower_inflation_index",
    "base_hp_current",
    "base_hp_max",
    "leaks_total",
    "enemies_alive",
    "boss_hp_current",
    "boss_hp_max",
    "wave_elapsed_s",
    "wave_remaining_s",
    "barrier_hp_total",
    "enemy_regen_total_per_s",
)
LIVE_RAW_MEMORY_BOOL_FIELDS: tuple[str, ...] = (
    "boss_alive",
    "is_combat_phase",
)
LIVE_RAW_MEMORY_FIELD_ALIASES: Dict[str, tuple[str, ...]] = {
    "current_wave": ("current_wave", "wave"),
    "gold": ("gold",),
    "essence": ("essence",),
    "wood": ("wood",),
    "stone": ("stone",),
    "wheat": ("wheat",),
    "workers_total": ("workers_total", "workers", "population_total"),
    "workers_free": ("workers_free", "free_workers", "idle_workers", "population_free"),
    "tower_inflation_index": ("tower_inflation_index", "inflation_index", "build_cost_index"),
    "base_hp_current": ("base_hp_current", "base_hp", "player_hp", "current_hp", "base_health"),
    "base_hp_max": ("base_hp_max", "max_player_hp", "max_hp", "player_hp_max", "base_health_max"),
    "leaks_total": ("leaks_total", "leaks", "wave_leaks", "leak_count"),
    "enemies_alive": ("enemies_alive", "alive_enemies", "enemy_alive"),
    "boss_alive": ("boss_alive", "is_boss_alive", "boss_present"),
    "boss_hp_current": ("boss_hp_current", "boss_hp", "boss_health"),
    "boss_hp_max": ("boss_hp_max", "max_boss_hp", "boss_health_max", "boss_max_hp"),
    "wave_elapsed_s": ("wave_elapsed_s", "combat_time_s", "wave_time_s"),
    "wave_remaining_s": ("wave_remaining_s", "wave_time_left_s", "combat_time_remaining_s"),
    "barrier_hp_total": ("barrier_hp_total", "barrier_hp", "barrier_health", "shield_hp"),
    "enemy_regen_total_per_s": ("enemy_regen_total_per_s", "regen_per_s", "regen_ps", "hp_regen_per_s"),
    "is_combat_phase": ("is_combat_phase", "combat_phase", "in_combat"),
}
LIVE_RAW_MEMORY_NUMERIC_DEFAULTS: Dict[str, float] = {
    "current_wave": 0.0,
    "gold": 0.0,
    "essence": 0.0,
    "wood": 0.0,
    "stone": 0.0,
    "wheat": 0.0,
    "workers_total": 0.0,
    "workers_free": 0.0,
    "tower_inflation_index": 1.0,
    "base_hp_current": 0.0,
    "base_hp_max": 0.0,
    "leaks_total": 0.0,
    "enemies_alive": 0.0,
    "boss_hp_current": 0.0,
    "boss_hp_max": 0.0,
    "wave_elapsed_s": 0.0,
    "wave_remaining_s": 0.0,
    "barrier_hp_total": 0.0,
    "enemy_regen_total_per_s": 0.0,
}


class LiveBridge:
    def __init__(
        self,
        catalog: CatalogRepository,
        replay_store: ReplayStore,
        project_root: Optional[Path] = None,
        memory_reader: Optional[MemoryReader] = None,
    ):
        if project_root is None:
            project_root = Path(__file__).resolve().parents[3]
        self.project_root = project_root
        self.catalog = catalog
        self.replay_store = replay_store
        self.memory_reader = memory_reader or MemoryReader()

        self.connected = False
        self.mode = "synthetic"
        self.process_name = "NordHold.exe"
        self.poll_ms = 1000
        self.require_admin = True
        self.dataset_version = ""
        self.game_build = ""
        self.signature_profile = ""
        self.calibration_candidates_path = ""
        self.calibration_candidate = ""
        self.last_reason = "not_connected"
        self.replay_session_id = ""
        self._synthetic_wave = 1
        self._memory_profile: Optional[MemoryProfile] = None
        self._required_fields = REQUIRED_MEMORY_FIELDS
        self._available_calibration_candidate_ids: list[str] = []
        self._last_memory_values: Dict[str, float | int | bool] = {}
        self._last_error: Dict[str, str] = {}
        self._snapshot_failure_streak = 0
        self._snapshot_failures_total = 0
        self._snapshot_transient_failure_count = 0
        self._connect_failures_total = 0
        self._connect_transient_failure_count = 0
        self._connect_retry_success_total = 0
        self.autoconnect_enabled = False
        self.autoconnect_last_attempt_at = ""
        self.autoconnect_last_result: Dict[str, Any] = {}
        self.dataset_autorefresh = True

    def connect(
        self,
        process_name: str,
        poll_ms: int,
        require_admin: bool,
        dataset_version: Optional[str] = None,
        replay_session_id: str = "",
        signature_profile_id: str = "",
        calibration_candidates_path: str = "",
        calibration_candidate_id: str = "",
        autoconnect_enabled: Optional[bool] = None,
        dataset_autorefresh: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self.memory_reader.close()
        self._memory_profile = None
        self._available_calibration_candidate_ids = []
        self._last_memory_values = {}
        self._required_fields = REQUIRED_MEMORY_FIELDS
        self._clear_last_error()
        self._snapshot_failure_streak = 0
        self._snapshot_failures_total = 0
        self._snapshot_transient_failure_count = 0
        self._connect_failures_total = 0
        self._connect_transient_failure_count = 0
        self._connect_retry_success_total = 0
        explicit_connect_failure_reason = ""

        self.process_name = process_name or "NordHold.exe"
        self.poll_ms = max(200, int(poll_ms))
        self.require_admin = bool(require_admin)
        self.calibration_candidates_path = ""
        self.calibration_candidate = ""
        if autoconnect_enabled is not None:
            self.autoconnect_enabled = bool(autoconnect_enabled)
        if dataset_autorefresh is not None:
            self.dataset_autorefresh = bool(dataset_autorefresh)

        if dataset_version:
            meta = self.catalog.get_dataset_meta(dataset_version)
        else:
            meta = self.catalog.get_active_dataset_meta()
        self.dataset_version = meta.dataset_version
        self.game_build = meta.build_id

        signatures = self.catalog.load_memory_signatures(self.dataset_version)
        requested_profile_id = signature_profile_id.strip()
        profile: Optional[MemoryProfile] = None
        profile_load_error: Optional[MemoryProfileError] = None
        profile_id_attempts: list[str] = []
        if requested_profile_id:
            profile_id_attempts.append(requested_profile_id)
            if "@" in requested_profile_id:
                base_profile_id = requested_profile_id.split("@", 1)[0].strip()
                if base_profile_id and base_profile_id not in profile_id_attempts:
                    profile_id_attempts.append(base_profile_id)
            # Final fallback to auto profile selection by process name.
            profile_id_attempts.append("")
        else:
            profile_id_attempts.append("")

        for profile_id in profile_id_attempts:
            try:
                profile = load_memory_profile(
                    signatures_payload=signatures,
                    process_name=self.process_name,
                    profile_id=profile_id,
                )
            except MemoryProfileError as exc:
                profile_load_error = exc
                continue
            break

        if profile is None:
            exc = profile_load_error or MemoryProfileError("Unable to load memory signature profile.")
            self.connected = False
            self.mode = "degraded"
            self.last_reason = f"memory_profile_invalid:{exc}"
            self.replay_session_id = ""
            self._set_last_error("connect_profile_load", exc)
            return self.status()
        self._required_fields = tuple(profile.required_combat_fields) or REQUIRED_MEMORY_FIELDS

        requested_calibration_path = calibration_candidates_path.strip()
        requested_candidate_id = calibration_candidate_id.strip()
        explicit_calibration_request = bool(requested_calibration_path or requested_candidate_id)
        implicit_calibration_discovery = (
            not explicit_calibration_request and self._profile_has_unresolved_required_fields(profile)
        )

        if explicit_calibration_request or implicit_calibration_discovery:
            try:
                calibration_payload, resolved_path = self._load_calibration_payload(requested_calibration_path)
                self._available_calibration_candidate_ids = calibration_candidate_ids(calibration_payload)
                selected_candidate_id = choose_calibration_candidate_id(
                    calibration_payload,
                    preferred_candidate_id=requested_candidate_id,
                    required_fields=self._required_fields,
                )
                profile, selected_candidate = apply_calibration_candidate(
                    base_profile=profile,
                    calibration_payload=calibration_payload,
                    candidate_id=selected_candidate_id,
                )
            except MemoryProfileError as exc:
                if explicit_calibration_request:
                    self.connected = False
                    self.mode = "degraded"
                    self.last_reason = f"memory_profile_invalid:{exc}"
                    self.replay_session_id = ""
                    self._set_last_error("connect_calibration_apply", exc)
                    return self.status()
            else:
                self.calibration_candidates_path = str(resolved_path)
                self.calibration_candidate = selected_candidate

        self._required_fields = tuple(profile.required_combat_fields) or REQUIRED_MEMORY_FIELDS
        self._memory_profile = profile
        self.signature_profile = profile.id
        self.poll_ms = max(200, self.poll_ms or profile.poll_ms)
        if profile.required_admin:
            self.require_admin = True

        has_process = self._process_exists(self.process_name)
        if has_process:
            if self.require_admin and not self._is_admin_context():
                self.connected = False
                self.mode = "degraded"
                self.last_reason = "process_found_but_admin_required"
                return self.status()
            else:
                try:
                    self._last_memory_values = self._connect_open_and_read_with_single_retry(profile)
                except MemoryProfileError as exc:
                    self.memory_reader.close()
                    self.connected = False
                    self.mode = "degraded"
                    self.last_reason = f"memory_profile_invalid:{exc}"
                    explicit_connect_failure_reason = self.last_reason
                    self._set_last_error("connect_profile_validate", exc)
                except MemoryReaderError as exc:
                    self.memory_reader.close()
                    self.connected = False
                    self.mode = "degraded"
                    self.last_reason = f"memory_connect_failed:{exc}"
                    explicit_connect_failure_reason = self.last_reason
                    self._set_last_error("connect_memory_open", exc)
                else:
                    self.connected = True
                    self.mode = "memory"
                    self.last_reason = "ok"
                    self.replay_session_id = ""
                    self._clear_last_error()
                    return self.status()

        if replay_session_id:
            try:
                self.replay_store.load_session(replay_session_id)
            except ReplayError:
                self.connected = False
                self.mode = "degraded"
                self.last_reason = "memory_unavailable_replay_session_not_found"
                self.replay_session_id = ""
            else:
                self.connected = False
                self.mode = "replay"
                self.last_reason = "using_replay_fallback"
                self.replay_session_id = replay_session_id
                self._clear_last_error()
            return self.status()

        if explicit_connect_failure_reason:
            self.connected = False
            self.mode = "degraded"
            self.last_reason = explicit_connect_failure_reason
            self.replay_session_id = ""
            return self.status()

        self.connected = False
        self.mode = "degraded"
        self.last_reason = "memory_unavailable_no_replay"
        self.replay_session_id = ""
        return self.status()

    def autoconnect(
        self,
        *,
        process_name: str = "NordHold.exe",
        poll_ms: int = 1000,
        require_admin: bool = True,
        dataset_version: str = "",
        dataset_autorefresh: bool = True,
        replay_session_id: str = "",
        signature_profile_id: str = "",
        calibration_candidates_path: str = "",
        calibration_candidate_id: str = "",
    ) -> Dict[str, Any]:
        self.autoconnect_enabled = True
        self.dataset_autorefresh = bool(dataset_autorefresh)
        self.autoconnect_last_attempt_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        requested_path = calibration_candidates_path.strip()
        requested_candidate = calibration_candidate_id.strip()
        explicit_calibration_request = bool(requested_path or requested_candidate)
        selected_path = requested_path
        selected_candidate_id = requested_candidate
        recommendation_reason = ""
        candidate_attempt_order: list[str] = []

        try:
            calibration_payload, resolved_path = self._load_calibration_payload(requested_path)
            selected_path = str(resolved_path)
            candidate_ids = calibration_candidate_ids(calibration_payload)
            selected_candidate_id = choose_calibration_candidate_id(
                calibration_payload,
                preferred_candidate_id=requested_candidate,
                required_fields=REQUIRED_MEMORY_FIELDS,
            )
            recommendation_reason = str(
                calibration_candidate_recommendation(
                    calibration_payload,
                    preferred_candidate_id=selected_candidate_id,
                    required_fields=REQUIRED_MEMORY_FIELDS,
                ).get("reason", "")
            )
            if selected_candidate_id:
                candidate_attempt_order.append(selected_candidate_id)
            for candidate_id in candidate_ids:
                candidate_id_value = str(candidate_id).strip()
                if candidate_id_value and candidate_id_value not in candidate_attempt_order:
                    candidate_attempt_order.append(candidate_id_value)
        except MemoryProfileError:
            if explicit_calibration_request:
                raise

        if not candidate_attempt_order:
            if selected_candidate_id:
                candidate_attempt_order = [selected_candidate_id]
            else:
                candidate_attempt_order = [""]

        requested_dataset_version = dataset_version.strip()
        selected_dataset_version: Optional[str] = (
            None if self.dataset_autorefresh else (requested_dataset_version or None)
        )

        status: Dict[str, Any] = {}
        attempts: list[Dict[str, Any]] = []
        selected_candidate_id_final = ""
        fallback_used = False

        for index, attempt_candidate_id in enumerate(candidate_attempt_order):
            status = self.connect(
                process_name=process_name,
                poll_ms=poll_ms,
                require_admin=require_admin,
                dataset_version=selected_dataset_version,
                replay_session_id=replay_session_id,
                signature_profile_id=signature_profile_id,
                calibration_candidates_path=selected_path,
                calibration_candidate_id=attempt_candidate_id,
                autoconnect_enabled=True,
                dataset_autorefresh=self.dataset_autorefresh,
            )
            final_candidate = str(status.get("calibration_candidate", "")).strip()
            selected_candidate_id_final = final_candidate or str(attempt_candidate_id).strip()
            attempts.append(
                {
                    "index": index + 1,
                    "candidate_id": str(attempt_candidate_id),
                    "selected_candidate_id": selected_candidate_id_final,
                    "mode": str(status.get("mode", "")),
                    "reason": str(status.get("reason", "")),
                    "memory_connected": bool(status.get("memory_connected", False)),
                }
            )
            if status.get("mode") == "memory":
                fallback_used = index > 0
                break

        if not status:
            status = self.status()
        if not selected_candidate_id_final:
            selected_candidate_id_final = str(status.get("calibration_candidate", "")).strip()
        if len(attempts) > 1:
            fallback_used = True

        self.autoconnect_last_result = {
            "ok": status.get("mode") == "memory",
            "mode": status.get("mode", ""),
            "reason": status.get("reason", ""),
            "dataset_version": status.get("dataset_version", ""),
            "calibration_candidates_path": status.get("calibration_candidates_path", ""),
            "calibration_candidate": status.get("calibration_candidate", ""),
            "candidate_selection": {
                "selected_candidate_id": selected_candidate_id,
                "resolved_candidates_path": selected_path,
                "recommendation_reason": recommendation_reason,
            },
            "attempts": attempts,
            "selected_candidate_id_final": selected_candidate_id_final,
            "fallback_used": bool(fallback_used),
        }
        return self.status()

    def status(self) -> Dict[str, Any]:
        coverage = self._field_coverage()
        return {
            "status": "connected" if self.connected else "degraded",
            "mode": self.mode,
            "process_name": self.process_name,
            "poll_ms": self.poll_ms,
            "require_admin": self.require_admin,
            "dataset_version": self.dataset_version,
            "game_build": self.game_build,
            "signature_profile": self.signature_profile,
            "calibration_candidates_path": self.calibration_candidates_path,
            "calibration_candidate": self.calibration_candidate,
            "reason": self.last_reason,
            "replay_session_id": self.replay_session_id,
            "memory_connected": self.memory_reader.connected,
            "required_field_resolution": self._required_field_resolution(),
            "field_coverage": coverage,
            "calibration_quality": self._calibration_quality(coverage),
            "active_required_fields": self._active_required_fields(),
            "calibration_candidate_ids": list(self._available_calibration_candidate_ids),
            "last_memory_values": dict(self._last_memory_values),
            "last_error": dict(self._last_error),
            "snapshot_failure_streak": int(self._snapshot_failure_streak),
            "snapshot_failures_total": int(self._snapshot_failures_total),
            "snapshot_transient_failure_count": int(self._snapshot_transient_failure_count),
            "connect_failures_total": int(self._connect_failures_total),
            "connect_transient_failure_count": int(self._connect_transient_failure_count),
            "connect_retry_success_total": int(self._connect_retry_success_total),
            "autoconnect_enabled": self.autoconnect_enabled,
            "autoconnect_last_attempt_at": self.autoconnect_last_attempt_at,
            "autoconnect_last_result": dict(self.autoconnect_last_result),
            "dataset_autorefresh": self.dataset_autorefresh,
        }

    def snapshot(self) -> LiveSnapshot:
        now = time.time()
        if self.mode == "memory" and self.connected and self._memory_profile is not None:
            try:
                values = self.memory_reader.read_fields(self._memory_profile)
            except MemoryReaderError as exc:
                self._snapshot_failures_total += 1
                self._snapshot_failure_streak += 1
                if self._is_transient_memory_error(str(exc)):
                    self._snapshot_transient_failure_count += 1
                    try:
                        values = self._reopen_and_read_memory_fields(self._memory_profile)
                    except MemoryReaderError as retry_exc:
                        self.memory_reader.close()
                        self.connected = False
                        self.mode = "degraded"
                        self.last_reason = f"memory_snapshot_failed:{retry_exc}"
                        self._set_last_error("snapshot_memory_read", retry_exc)
                    else:
                        self.connected = True
                        self.mode = "memory"
                        self.last_reason = "ok"
                        self._snapshot_failure_streak = 0
                        self._last_memory_values = self._normalize_raw_memory_values(values)
                        self._clear_last_error()
                        return self._snapshot_from_memory_values(now=now, values=self._last_memory_values)
                else:
                    self.memory_reader.close()
                    self.connected = False
                    self.mode = "degraded"
                    self.last_reason = f"memory_snapshot_failed:{exc}"
                    self._set_last_error("snapshot_memory_read", exc)
            else:
                self._snapshot_failure_streak = 0
                self._last_memory_values = self._normalize_raw_memory_values(values)
                self._clear_last_error()
                return self._snapshot_from_memory_values(now=now, values=self._last_memory_values)

        if self.mode == "replay" and self.replay_session_id:
            replay_snapshot = self.replay_store.latest_snapshot(self.replay_session_id)
            return self._snapshot_with_live_raw_memory_contract(replay_snapshot)

        return self._snapshot_with_live_raw_memory_contract(
            LiveSnapshot(
                timestamp=now,
                wave=self._synthetic_wave,
                gold=0.0,
                essence=0.0,
                build={"towers": []},
                source_mode="synthetic",
            )
        )

    def inspect_calibration_candidates(self, calibration_candidates_path: str = "") -> Dict[str, Any]:
        payload, resolved_path = self._load_calibration_payload(calibration_candidates_path)
        summaries = list_calibration_candidate_summaries(payload)
        recommendation = calibration_candidate_recommendation(payload)
        active_candidate_id = str(recommendation.get("active_candidate_id", "")).strip()
        recommended_candidate_id = str(recommendation.get("recommended_candidate_id", "")).strip()
        return {
            "path": str(resolved_path),
            "active_candidate_id": active_candidate_id,
            "recommended_candidate_id": recommended_candidate_id,
            "recommended_candidate_support": recommendation,
            "candidate_ids": [item["id"] for item in summaries],
            "candidates": summaries,
        }

    def _snapshot_from_memory_values(self, now: float, values: Dict[str, Any]) -> LiveSnapshot:
        raw_values = self._normalize_raw_memory_values(values)
        wave = int(raw_values.get("current_wave", raw_values.get("wave", self._synthetic_wave)))
        gold = float(raw_values.get("gold", 0.0))
        essence = float(raw_values.get("essence", 0.0))
        combat_block = self._combat_block_payload(raw_values)
        self._synthetic_wave = max(1, wave)
        snapshot = LiveSnapshot(
            timestamp=now,
            wave=max(1, wave),
            gold=gold,
            essence=essence,
            build={
                "towers": [],
                "raw_memory_fields": raw_values,
                "combat": {"block": combat_block},
            },
            source_mode="memory",
        )
        return self._snapshot_with_live_raw_memory_contract(snapshot)

    def _snapshot_with_live_raw_memory_contract(self, snapshot: LiveSnapshot) -> LiveSnapshot:
        build = dict(snapshot.build if isinstance(snapshot.build, dict) else {})
        raw_payload = build.get("raw_memory_fields")
        if isinstance(raw_payload, dict):
            normalized_raw = self._normalize_raw_memory_values(raw_payload)
        else:
            normalized_raw = self._normalize_raw_memory_values({})
        build["raw_memory_fields"] = normalized_raw
        return LiveSnapshot(
            timestamp=snapshot.timestamp,
            wave=snapshot.wave,
            gold=snapshot.gold,
            essence=snapshot.essence,
            build=build,
            source_mode=snapshot.source_mode,
        )

    def _field_coverage(self) -> Dict[str, int]:
        fields = self._memory_profile.fields if self._memory_profile is not None else {}
        required_total = len(self._required_fields)
        required_resolved = 0
        for field_name in self._required_fields:
            spec = fields.get(field_name)
            if spec is not None and spec.resolved:
                required_resolved += 1

        optional_field_names = [name for name in fields if name not in self._required_fields]
        optional_total = len(optional_field_names)
        optional_resolved = sum(1 for name in optional_field_names if fields[name].resolved)
        return {
            "required_total": required_total,
            "required_resolved": required_resolved,
            "optional_total": optional_total,
            "optional_resolved": optional_resolved,
        }

    def _calibration_quality(self, coverage: Dict[str, int]) -> str:
        required_total = int(coverage.get("required_total", 0))
        required_resolved = int(coverage.get("required_resolved", 0))
        optional_total = int(coverage.get("optional_total", 0))
        optional_resolved = int(coverage.get("optional_resolved", 0))

        if required_total > 0 and required_resolved == required_total:
            if optional_total == 0 or optional_resolved == optional_total:
                return "full"
            return "partial"
        if required_resolved > 0 or optional_resolved > 0:
            return "partial"
        return "minimal"

    def _active_required_fields(self) -> list[str]:
        # These are the currently enforced required fields for the active mode/profile.
        return [str(field_name) for field_name in self._required_fields]

    def _normalize_raw_memory_values(
        self,
        values: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized: Dict[str, Any] = dict(values)
        for canonical_name, aliases in OPTIONAL_MEMORY_FIELD_ALIASES.items():
            if canonical_name in normalized:
                continue
            normalized[canonical_name] = self._resolve_numeric_field(
                source=normalized,
                aliases=aliases,
                default=0.0,
            )
        self._ensure_live_raw_memory_contract_fields(normalized)
        return normalized

    def _ensure_live_raw_memory_contract_fields(self, values: Dict[str, Any]) -> None:
        source_values = dict(values)
        for field_name in LIVE_RAW_MEMORY_NUMERIC_FIELDS:
            aliases = LIVE_RAW_MEMORY_FIELD_ALIASES.get(field_name, (field_name,))
            default_value = float(LIVE_RAW_MEMORY_NUMERIC_DEFAULTS.get(field_name, 0.0))
            numeric_value = self._resolve_numeric_field(source=source_values, aliases=aliases, default=default_value)
            values[field_name] = 0 if numeric_value == 0.0 and default_value == 0.0 else numeric_value

        # If leaks are not available as a direct field, infer them from base HP.
        leaks_aliases = LIVE_RAW_MEMORY_FIELD_ALIASES.get("leaks_total", ("leaks_total",))
        has_direct_leaks_value = any(alias in source_values for alias in leaks_aliases)
        if not has_direct_leaks_value:
            base_hp_current = int(float(values.get("base_hp_current", 0.0)))
            base_hp_max = int(float(values.get("base_hp_max", 0.0)))
            if base_hp_max > 0:
                values["leaks_total"] = max(0, base_hp_max - max(0, base_hp_current))

        for field_name in LIVE_RAW_MEMORY_BOOL_FIELDS:
            aliases = LIVE_RAW_MEMORY_FIELD_ALIASES.get(field_name, (field_name,))
            values[field_name] = self._resolve_bool_field(source=source_values, aliases=aliases, default=False)

        # If combat-phase boolean is missing, infer it from enemy count as best-effort fallback.
        combat_phase_aliases = LIVE_RAW_MEMORY_FIELD_ALIASES.get("is_combat_phase", ("is_combat_phase",))
        has_direct_combat_phase = any(alias in source_values for alias in combat_phase_aliases)
        if not has_direct_combat_phase:
            enemies_alive = int(float(values.get("enemies_alive", 0.0)))
            values["is_combat_phase"] = enemies_alive > 0

    def _combat_block_payload(self, values: Dict[str, Any]) -> Dict[str, float]:
        return {
            "value": float(self._resolve_numeric_field(source=values, aliases=("combat_block_value",), default=0.0)),
            "percent": float(
                self._resolve_numeric_field(source=values, aliases=("combat_block_percent",), default=0.0)
            ),
            "flat": float(self._resolve_numeric_field(source=values, aliases=("combat_block_flat",), default=0.0)),
        }

    def _resolve_numeric_field(
        self,
        *,
        source: Dict[str, Any],
        aliases: tuple[str, ...],
        default: float,
    ) -> float:
        for field_name in aliases:
            if field_name not in source:
                continue
            raw_value = source.get(field_name)
            if isinstance(raw_value, bool):
                return float(int(raw_value))
            if isinstance(raw_value, (int, float)):
                return float(raw_value)
            try:
                return float(str(raw_value).strip())
            except (TypeError, ValueError):
                continue
        return float(default)

    def _resolve_bool_field(
        self,
        *,
        source: Dict[str, Any],
        aliases: tuple[str, ...],
        default: bool,
    ) -> bool:
        for field_name in aliases:
            if field_name not in source:
                continue
            raw_value = source.get(field_name)
            if isinstance(raw_value, bool):
                return raw_value
            if isinstance(raw_value, (int, float)):
                return float(raw_value) != 0.0
            text = str(raw_value).strip().lower()
            if text in {"1", "true", "yes", "y", "on", "t"}:
                return True
            if text in {"0", "false", "no", "n", "off", "f", ""}:
                return False
        return bool(default)

    def _required_field_resolution(self) -> Dict[str, Dict[str, Any]]:
        details: Dict[str, Dict[str, Any]] = {}
        fields = self._memory_profile.fields if self._memory_profile is not None else {}
        for field_name in self._required_fields:
            spec = fields.get(field_name)
            if spec is None:
                details[field_name] = {
                    "present": False,
                    "resolved": False,
                    "source": "",
                    "type": "",
                    "address": "",
                    "offsets": [],
                    "relative_to_module": False,
                }
                continue
            details[field_name] = {
                "present": True,
                "resolved": bool(spec.resolved),
                "source": spec.source,
                "type": spec.value_type,
                "address": hex(int(spec.address)),
                "offsets": [hex(int(offset)) for offset in spec.offsets],
                "relative_to_module": bool(spec.relative_to_module),
            }
        return details

    def _set_last_error(self, stage: str, error: Exception) -> None:
        self._last_error = {
            "stage": stage,
            "type": type(error).__name__,
            "message": str(error),
        }

    def _clear_last_error(self) -> None:
        self._last_error = {}

    def _reopen_and_read_memory_fields(self, profile: MemoryProfile) -> Dict[str, Any]:
        self.memory_reader.close()
        self.memory_reader.open(self.process_name, profile)
        return self.memory_reader.read_fields(profile)

    def _connect_open_and_read_with_single_retry(self, profile: MemoryProfile) -> Dict[str, Any]:
        profile.ensure_resolved()
        try:
            self.memory_reader.open(self.process_name, profile)
            return self._normalize_raw_memory_values(self.memory_reader.read_fields(profile))
        except MemoryReaderError as exc:
            self._connect_failures_total += 1
            if self._is_transient_memory_error(str(exc)):
                self._connect_transient_failure_count += 1
                try:
                    values = self._reopen_and_read_memory_fields(profile)
                except MemoryReaderError as retry_exc:
                    self._connect_failures_total += 1
                    raise
                self._connect_retry_success_total += 1
                return self._normalize_raw_memory_values(values)
            raise

    def _is_transient_memory_error(self, message: str) -> bool:
        text = str(message).lower()
        return "winerr=299" in text and "readprocessmemory failed" in text

    def _profile_has_unresolved_required_fields(self, profile: MemoryProfile) -> bool:
        for field_name in self._required_fields:
            spec = profile.fields.get(field_name)
            if spec is None or not spec.resolved:
                return True
        return False

    def _process_exists(self, process_name: str) -> bool:
        system = platform.system().lower()
        try:
            if "windows" in system:
                output = subprocess.check_output(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"Get-Process -Name '{process_name.replace('.exe','')}' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id"],
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return bool(output.strip())

            output = subprocess.check_output(["ps", "-eo", "comm"], text=True)
            return process_name in output
        except Exception:
            return False

    def _is_admin_context(self) -> bool:
        if platform.system().lower() != "windows":
            return True
        try:
            output = subprocess.check_output(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "[Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent() | ForEach-Object { $_.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }"],
                stderr=subprocess.STDOUT,
                text=True,
            )
            return output.strip().lower().startswith("true")
        except Exception:
            return False

    def _load_calibration_payload(self, calibration_candidates_path: str | None) -> tuple[Dict[str, Any], Path]:
        return load_calibration_payload(
            calibration_candidates_path,
            project_root=self.project_root,
        )
