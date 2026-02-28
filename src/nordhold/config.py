from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .models import (
    Config,
    Modifier,
    SelectionLimits,
    StatEffect,
    Tower,
)


class ConfigError(RuntimeError):
    """Raised when configuration file is invalid."""


def _read_raw(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    if suffix == ".json":
        return json.loads(text)

    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ConfigError(
                "YAML config requested, but PyYAML не установлен. "
                "Установите пакет `pyyaml` или используйте JSON."
            ) from exc
        return yaml.safe_load(text)

    raise ConfigError(f"Unsupported config format '{suffix}'. Use .json или .yaml/.yml.")


def _load_effects(payload: Iterable[Dict[str, Any]]) -> Sequence[StatEffect]:
    effects: List[StatEffect] = []
    for entry in payload:
        try:
            effects.append(StatEffect.from_dict(entry))
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    return tuple(effects)


def _load_towers(payload: Iterable[Dict[str, Any]]) -> Sequence[Tower]:
    towers: List[Tower] = []
    for raw in payload:
        try:
            towers.append(Tower.from_dict(raw))
        except ValueError as exc:
            name = raw.get("name", "<unknown>")
            raise ConfigError(f"Invalid tower definition '{name}': {exc}") from exc
    return tuple(towers)


def _load_modifiers(
    payload: Dict[str, Iterable[Dict[str, Any]]],
) -> Dict[str, Sequence[Modifier]]:
    result: Dict[str, Sequence[Modifier]] = {}
    for category, entries in payload.items():
        modifiers: List[Modifier] = []
        for raw in entries:
            try:
                modifiers.append(Modifier.from_dict(category, raw))
            except ValueError as exc:
                name = raw.get("name", "<unknown>")
                raise ConfigError(
                    f"Invalid modifier '{name}' в категории '{category}': {exc}"
                ) from exc
        result[category] = tuple(modifiers)
    return result


def _load_forced_modifiers(payload: Iterable[Dict[str, Any]]) -> Sequence[Modifier]:
    forced: List[Modifier] = []
    for raw in payload:
        category = str(raw.get("category", "forced")).strip() or "forced"
        try:
            forced.append(Modifier.from_dict(category, raw))
        except ValueError as exc:
            name = raw.get("name", "<unknown>")
            raise ConfigError(f"Invalid forced modifier '{name}': {exc}") from exc
    return tuple(forced)


def load_config(path: Path | str) -> Config:
    path = Path(path)
    payload = _read_raw(path)

    if not isinstance(payload, dict):
        raise ConfigError("Config root must be an object (JSON/YAML mapping).")

    try:
        tower_slots = int(payload.get("tower_slots", 0))
    except (TypeError, ValueError) as exc:
        raise ConfigError("Field 'tower_slots' must be integer.") from exc

    if tower_slots <= 0:
        raise ConfigError("Config must define a positive integer 'tower_slots'.")

    towers_payload = payload.get("towers", [])
    modifiers_payload = payload.get("modifiers", {})
    selection_limits_payload = payload.get("selection_limits", {})
    forced_modifiers_payload = payload.get("forced_modifiers", [])
    global_effects_payload = payload.get("global_effects", [])

    towers = _load_towers(towers_payload)
    if not towers:
        raise ConfigError("Config must contain at least one tower definition.")

    modifiers = _load_modifiers(modifiers_payload)
    selection_limits = SelectionLimits(
        per_category={
            str(category): int(limit)
            for category, limit in selection_limits_payload.items()
        }
    )
    forced_modifiers = _load_forced_modifiers(forced_modifiers_payload)
    global_effects = _load_effects(global_effects_payload)

    return Config(
        towers=towers,
        modifiers=modifiers,
        tower_slots=tower_slots,
        selection_limits=selection_limits,
        forced_modifiers=forced_modifiers,
        global_effects=global_effects,
    )
