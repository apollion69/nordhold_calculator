from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Set


class StackMode(str, Enum):
    ADD = "add"
    MULT = "mult"
    OVERRIDE = "override"


class ValueType(str, Enum):
    FLAT = "flat"
    PERCENT = "percent"
    MULTIPLIER = "multiplier"


class StatTarget(str, Enum):
    DAMAGE = "damage"
    ATTACK_SPEED = "attack_speed"


def _normalize_tags(raw: Optional[Iterable[str]]) -> Set[str]:
    if not raw:
        return set()
    return {str(tag).strip().lower() for tag in raw if str(tag).strip()}


def _normalize_target(value: str) -> StatTarget:
    try:
        return StatTarget(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported stat target '{value}'.") from exc


def _normalize_stack_mode(value: str) -> StackMode:
    try:
        return StackMode(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported stack mode '{value}'. Use add, mult или override.") from exc


def _normalize_value_type(value: str) -> ValueType:
    try:
        return ValueType(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported value type '{value}'. Use flat, percent, multiplier.") from exc


@dataclass(slots=True, frozen=True)
class StatEffect:
    target: StatTarget
    value_type: ValueType
    value: float
    stack_mode: StackMode = StackMode.ADD
    note: str = ""

    @classmethod
    def from_dict(cls, payload: Dict) -> "StatEffect":
        try:
            target = _normalize_target(str(payload["target"]).lower())
            value_type = _normalize_value_type(str(payload["value_type"]).lower())
            value = float(payload["value"])
        except KeyError as exc:
            raise ValueError(f"Missing field in effect definition: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid effect definition: {exc}") from exc

        stack_mode = _normalize_stack_mode(str(payload.get("stack", StackMode.ADD)).lower())
        note = str(payload.get("note", ""))
        return cls(target=target, value_type=value_type, value=value, stack_mode=stack_mode, note=note)


@dataclass(slots=True, frozen=True)
class TowerUpgrade:
    name: str
    cost: float
    effects: Sequence[StatEffect] = field(default_factory=tuple)
    add_tags: Set[str] = field(default_factory=set)
    remove_tags: Set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, payload: Dict) -> "TowerUpgrade":
        try:
            name = str(payload["name"])
            cost = float(payload.get("cost", 0.0))
        except KeyError as exc:
            raise ValueError(f"Missing field in tower upgrade: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid tower upgrade definition: {exc}") from exc

        effects_payload = payload.get("effects", [])
        effects = tuple(StatEffect.from_dict(item) for item in effects_payload)
        add_tags = _normalize_tags(payload.get("add_tags"))
        remove_tags = _normalize_tags(payload.get("remove_tags"))
        return cls(
            name=name,
            cost=cost,
            effects=effects,
            add_tags=add_tags,
            remove_tags=remove_tags,
        )


@dataclass(slots=True)
class Tower:
    name: str
    base_damage: float
    attack_speed: float
    tags: Set[str] = field(default_factory=set)
    max_count: int = 1
    cost: float = 0.0
    notes: str = ""
    upgrades: Sequence[TowerUpgrade] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: Dict) -> "Tower":
        try:
            name = str(payload["name"])
            base_damage = float(payload["base_damage"])
            attack_speed = float(payload["attack_speed"])
        except KeyError as exc:
            raise ValueError(f"Missing field in tower definition: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid tower definition for '{payload.get('name', '<unknown>')}': {exc}") from exc

        tags = _normalize_tags(payload.get("tags"))
        upgrades_payload = payload.get("upgrades", [])
        upgrades = tuple(TowerUpgrade.from_dict(entry) for entry in upgrades_payload)

        return cls(
            name=name,
            base_damage=base_damage,
            attack_speed=attack_speed,
            tags=tags,
            max_count=int(payload.get("max_count", 1)),
            cost=float(payload.get("cost", 0.0)),
            notes=str(payload.get("notes", "")),
            upgrades=upgrades,
        )


@dataclass(slots=True)
class Modifier:
    name: str
    category: str
    effects: Sequence[StatEffect]
    applies_to: Set[str] = field(default_factory=set)
    global_scope: bool = True
    exclusive: bool = False
    max_stacks: int = 1
    cost: float = 0.0
    notes: str = ""

    @classmethod
    def from_dict(cls, category: str, payload: Dict) -> "Modifier":
        try:
            name = str(payload["name"])
        except KeyError as exc:
            raise ValueError(f"Missing name in modifier for category '{category}': {exc}") from exc

        effects_payload = payload.get("effects")
        if not effects_payload:
            raise ValueError(f"Modifier '{name}' in category '{category}' must define non-empty 'effects'.")

        effects = tuple(StatEffect.from_dict(item) for item in effects_payload)

        applies_to = _normalize_tags(payload.get("applies_to"))
        global_scope = bool(payload.get("global_scope", True))
        exclusive = bool(payload.get("exclusive", False))
        max_stacks = int(payload.get("max_stacks", 1))
        if max_stacks < 1:
            raise ValueError(f"Modifier '{name}' in category '{category}' must have max_stacks >= 1.")

        return cls(
            name=name,
            category=category,
            effects=effects,
            applies_to=applies_to,
            global_scope=global_scope,
            exclusive=exclusive,
            max_stacks=max_stacks,
            cost=float(payload.get("cost", 0.0)),
            notes=str(payload.get("notes", "")),
        )


@dataclass(slots=True)
class SelectionLimits:
    per_category: Dict[str, int] = field(default_factory=dict)

    def limit_for(self, category: str, default: int) -> int:
        value = self.per_category.get(category)
        if value is None:
            return default
        return max(0, int(value))


@dataclass(slots=True)
class Config:
    towers: Sequence[Tower]
    modifiers: Dict[str, Sequence[Modifier]]
    tower_slots: int
    selection_limits: SelectionLimits
    forced_modifiers: Sequence[Modifier] = field(default_factory=tuple)
    global_effects: Sequence[StatEffect] = field(default_factory=tuple)

    @classmethod
    def empty(cls) -> "Config":
        return cls(
            towers=tuple(),
            modifiers={},
            tower_slots=0,
            selection_limits=SelectionLimits(),
        )
