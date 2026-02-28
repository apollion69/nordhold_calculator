from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Optional

ProvenanceType = Literal["online", "local_extract", "memory", "manual"]


class ModelError(ValueError):
    """Raised for malformed realtime model payloads."""


def _require(payload: Dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ModelError(f"Missing required field: {key}")
    return payload[key]


def _stable_float(value: float, digits: int = 10) -> float:
    rounded = round(float(value), digits)
    # Normalize signed zero to keep deterministic JSON across runtimes.
    return 0.0 if rounded == 0.0 else rounded


def _stabilize_numeric_payload(payload: Any, digits: int = 10) -> Any:
    if isinstance(payload, float):
        return _stable_float(payload, digits=digits)
    if isinstance(payload, list):
        return [_stabilize_numeric_payload(item, digits=digits) for item in payload]
    if isinstance(payload, tuple):
        return [_stabilize_numeric_payload(item, digits=digits) for item in payload]
    if isinstance(payload, dict):
        return {key: _stabilize_numeric_payload(value, digits=digits) for key, value in payload.items()}
    return payload


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_economy_totals(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    workers_source = source.get("workers", {})
    workers = workers_source if isinstance(workers_source, dict) else {}

    baseline_gold = _to_float(source.get("baseline_gold", 0.0))
    baseline_essence = _to_float(source.get("baseline_essence", 0.0))
    worker_gold_income = _to_float(source.get("worker_gold_income", 0.0))
    worker_essence_income = _to_float(source.get("worker_essence_income", 0.0))
    gross_gold_income = _to_float(source.get("gross_gold_income", baseline_gold + worker_gold_income))
    gross_essence_income = _to_float(source.get("gross_essence_income", baseline_essence + worker_essence_income))
    build_spend_gold = _to_float(source.get("build_spend_gold", 0.0))
    build_inflation_gold = _to_float(source.get("build_inflation_gold", 0.0))
    build_actions = max(0, _to_int(source.get("build_actions", 0)))

    total_workers = max(0, _to_int(workers.get("total", 0)))
    workers_gold = max(0, _to_int(workers.get("gold", 0)))
    workers_essence = max(0, _to_int(workers.get("essence", 0)))
    workers_unassigned = max(0, _to_int(workers.get("unassigned", total_workers - workers_gold - workers_essence)))

    if total_workers <= 0:
        total_workers = workers_gold + workers_essence + workers_unassigned
    if workers_gold + workers_essence + workers_unassigned > total_workers:
        workers_unassigned = max(0, total_workers - workers_gold - workers_essence)

    return {
        "baseline_gold": baseline_gold,
        "baseline_essence": baseline_essence,
        "worker_gold_income": worker_gold_income,
        "worker_essence_income": worker_essence_income,
        "gross_gold_income": gross_gold_income,
        "gross_essence_income": gross_essence_income,
        "build_spend_gold": build_spend_gold,
        "build_inflation_gold": build_inflation_gold,
        "build_actions": build_actions,
        "net_gold": _to_float(source.get("net_gold", gross_gold_income - build_spend_gold)),
        "net_essence": _to_float(source.get("net_essence", gross_essence_income)),
        "policy_id": str(source.get("policy_id", "balanced")),
        "workers": {
            "total": total_workers,
            "gold": workers_gold,
            "essence": workers_essence,
            "unassigned": workers_unassigned,
        },
    }


@dataclass(slots=True, frozen=True)
class Modifier:
    target: str
    op: Literal["add", "mul", "set", "cap_max", "cap_min"]
    value: float

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Modifier":
        target = str(_require(payload, "target"))
        op = str(_require(payload, "op")).lower()
        if op not in {"add", "mul", "set", "cap_max", "cap_min"}:
            raise ModelError(f"Unsupported modifier op: {op}")
        value = float(_require(payload, "value"))
        return cls(target=target, op=op, value=value)


@dataclass(slots=True, frozen=True)
class DotEffect:
    id: str
    damage_per_tick: float
    tick_interval_s: float
    duration_s: float
    max_stacks: int = 1
    stacking: Literal["refresh_duration", "add_stacks", "replace_if_stronger"] = "refresh_duration"
    provenance: ProvenanceType = "manual"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "DotEffect":
        return cls(
            id=str(_require(payload, "id")),
            damage_per_tick=float(_require(payload, "damage_per_tick")),
            tick_interval_s=float(_require(payload, "tick_interval_s")),
            duration_s=float(_require(payload, "duration_s")),
            max_stacks=int(payload.get("max_stacks", 1)),
            stacking=str(payload.get("stacking", "refresh_duration")),
            provenance=str(payload.get("provenance", "manual")),
        )


@dataclass(slots=True, frozen=True)
class TowerStats:
    damage: float
    fire_rate: float
    crit_chance: float
    crit_multiplier: float
    accuracy: float
    penetration: float
    barrier_damage_multiplier: float

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TowerStats":
        return cls(
            damage=float(_require(payload, "damage")),
            fire_rate=float(_require(payload, "fire_rate")),
            crit_chance=float(payload.get("crit_chance", 0.0)),
            crit_multiplier=float(payload.get("crit_multiplier", 1.5)),
            accuracy=float(payload.get("accuracy", 1.0)),
            penetration=float(payload.get("penetration", 0.0)),
            barrier_damage_multiplier=float(payload.get("barrier_damage_multiplier", 1.0)),
        )


@dataclass(slots=True, frozen=True)
class UpgradeLevel:
    level: int
    cost: float
    modifiers: tuple[Modifier, ...]
    provenance: ProvenanceType = "manual"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UpgradeLevel":
        modifiers = tuple(Modifier.from_dict(item) for item in payload.get("modifiers", []))
        return cls(
            level=int(_require(payload, "level")),
            cost=float(payload.get("cost", 0.0)),
            modifiers=modifiers,
            provenance=str(payload.get("provenance", "manual")),
        )


@dataclass(slots=True, frozen=True)
class TowerDefinition:
    id: str
    name: str
    base_stats: TowerStats
    tags: tuple[str, ...]
    upgrade_levels: tuple[UpgradeLevel, ...]
    dot_effects: tuple[DotEffect, ...] = tuple()
    provenance: ProvenanceType = "manual"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TowerDefinition":
        return cls(
            id=str(_require(payload, "id")),
            name=str(_require(payload, "name")),
            base_stats=TowerStats.from_dict(_require(payload, "base_stats")),
            tags=tuple(str(item) for item in payload.get("tags", [])),
            upgrade_levels=tuple(UpgradeLevel.from_dict(item) for item in payload.get("upgrade_levels", [])),
            dot_effects=tuple(DotEffect.from_dict(item) for item in payload.get("dot_effects", [])),
            provenance=str(payload.get("provenance", "manual")),
        )


@dataclass(slots=True, frozen=True)
class GlobalModifier:
    id: str
    name: str
    modifiers: tuple[Modifier, ...]
    provenance: ProvenanceType = "manual"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "GlobalModifier":
        return cls(
            id=str(_require(payload, "id")),
            name=str(_require(payload, "name")),
            modifiers=tuple(Modifier.from_dict(item) for item in payload.get("modifiers", [])),
            provenance=str(payload.get("provenance", "manual")),
        )


@dataclass(slots=True, frozen=True)
class EnemyDefinition:
    id: str
    name: str
    hp: float
    armor: float
    block: float
    barrier: float
    regen_per_s: float
    speed: float
    tags: tuple[str, ...]
    provenance: ProvenanceType = "manual"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EnemyDefinition":
        return cls(
            id=str(_require(payload, "id")),
            name=str(_require(payload, "name")),
            hp=float(_require(payload, "hp")),
            armor=float(payload.get("armor", 0.0)),
            block=float(payload.get("block", 0.0)),
            barrier=float(payload.get("barrier", 0.0)),
            regen_per_s=float(payload.get("regen_per_s", 0.0)),
            speed=float(payload.get("speed", 0.0)),
            tags=tuple(str(item) for item in payload.get("tags", [])),
            provenance=str(payload.get("provenance", "manual")),
        )


@dataclass(slots=True, frozen=True)
class SpawnDefinition:
    at_s: float
    enemy_id: str
    count: int
    interval_s: float

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SpawnDefinition":
        return cls(
            at_s=float(_require(payload, "at_s")),
            enemy_id=str(_require(payload, "enemy_id")),
            count=int(_require(payload, "count")),
            interval_s=float(payload.get("interval_s", 0.0)),
        )


@dataclass(slots=True, frozen=True)
class WaveDefinition:
    index: int
    duration_s: float
    spawns: tuple[SpawnDefinition, ...]
    provenance: ProvenanceType = "manual"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "WaveDefinition":
        return cls(
            index=int(_require(payload, "index")),
            duration_s=float(_require(payload, "duration_s")),
            spawns=tuple(SpawnDefinition.from_dict(item) for item in payload.get("spawns", [])),
            provenance=str(payload.get("provenance", "manual")),
        )


@dataclass(slots=True, frozen=True)
class Ruleset:
    accuracy_block_model: Literal["linear_subtract", "multiplicative"] = "linear_subtract"
    armor_penetration_model: Literal["linear_subtract", "multiplicative"] = "linear_subtract"
    barrier_inherits_armor: bool = False
    dot_scaling_policy: Literal["source_only", "global"] = "source_only"
    critical_model: Literal["expected", "sampled"] = "expected"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Ruleset":
        return cls(
            accuracy_block_model=str(payload.get("accuracy_block_model", "linear_subtract")),
            armor_penetration_model=str(payload.get("armor_penetration_model", "linear_subtract")),
            barrier_inherits_armor=bool(payload.get("barrier_inherits_armor", False)),
            dot_scaling_policy=str(payload.get("dot_scaling_policy", "source_only")),
            critical_model=str(payload.get("critical_model", "expected")),
        )


@dataclass(slots=True, frozen=True)
class EconomyPolicy:
    id: str
    worker_gold_multiplier: float = 1.0
    worker_essence_multiplier: float = 1.0
    build_cost_multiplier: float = 1.0

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EconomyPolicy":
        return cls(
            id=str(_require(payload, "id")),
            worker_gold_multiplier=float(payload.get("worker_gold_multiplier", 1.0)),
            worker_essence_multiplier=float(payload.get("worker_essence_multiplier", 1.0)),
            build_cost_multiplier=float(payload.get("build_cost_multiplier", 1.0)),
        )


@dataclass(slots=True, frozen=True)
class WaveResourceBaseline:
    wave: int
    gold: float = 0.0
    essence: float = 0.0

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "WaveResourceBaseline":
        return cls(
            wave=int(_require(payload, "wave")),
            gold=float(payload.get("gold", 0.0)),
            essence=float(payload.get("essence", 0.0)),
        )


@dataclass(slots=True, frozen=True)
class EconomyDefinition:
    default_wave_gold: float = 0.0
    default_wave_essence: float = 0.0
    wave_resource_baseline: tuple[WaveResourceBaseline, ...] = tuple()
    initial_workers: int = 0
    initial_workers_gold: int = 0
    initial_workers_essence: int = 0
    worker_gold_income_per_wave: float = 0.0
    worker_essence_income_per_wave: float = 0.0
    build_cost_inflation_rate: float = 0.0
    build_cost_inflation_max_multiplier: float = 2.0
    default_policy_id: str = "balanced"
    policies: Dict[str, EconomyPolicy] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EconomyDefinition":
        wave_resource_baseline = tuple(
            sorted(
                (WaveResourceBaseline.from_dict(item) for item in payload.get("wave_resource_baseline", [])),
                key=lambda item: item.wave,
            )
        )
        policies = {
            policy.id: policy
            for policy in (EconomyPolicy.from_dict(item) for item in payload.get("policies", []))
        }
        if "balanced" not in policies:
            policies["balanced"] = EconomyPolicy(id="balanced")

        default_policy_id = str(payload.get("default_policy_id", payload.get("default_policy", "balanced")))
        if default_policy_id not in policies:
            default_policy_id = "balanced"

        return cls(
            default_wave_gold=float(payload.get("default_wave_gold", 0.0)),
            default_wave_essence=float(payload.get("default_wave_essence", 0.0)),
            wave_resource_baseline=wave_resource_baseline,
            initial_workers=int(payload.get("initial_workers", 0)),
            initial_workers_gold=int(payload.get("initial_workers_gold", 0)),
            initial_workers_essence=int(payload.get("initial_workers_essence", 0)),
            worker_gold_income_per_wave=float(payload.get("worker_gold_income_per_wave", 0.0)),
            worker_essence_income_per_wave=float(payload.get("worker_essence_income_per_wave", 0.0)),
            build_cost_inflation_rate=float(payload.get("build_cost_inflation_rate", 0.0)),
            build_cost_inflation_max_multiplier=float(payload.get("build_cost_inflation_max_multiplier", 2.0)),
            default_policy_id=default_policy_id,
            policies=policies,
        )


@dataclass(slots=True, frozen=True)
class ScenarioDefinition:
    id: str
    name: str
    description: str
    rules: Ruleset
    towers: Dict[str, TowerDefinition]
    enemies: Dict[str, EnemyDefinition]
    waves: tuple[WaveDefinition, ...]
    global_modifiers: Dict[str, GlobalModifier]
    economy: EconomyDefinition = field(default_factory=EconomyDefinition)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ScenarioDefinition":
        towers = {
            tower.id: tower
            for tower in (TowerDefinition.from_dict(item) for item in payload.get("towers", []))
        }
        enemies = {
            enemy.id: enemy
            for enemy in (EnemyDefinition.from_dict(item) for item in payload.get("enemies", []))
        }
        global_modifiers = {
            modifier.id: modifier
            for modifier in (GlobalModifier.from_dict(item) for item in payload.get("global_modifiers", []))
        }
        waves = tuple(sorted((WaveDefinition.from_dict(item) for item in payload.get("waves", [])), key=lambda x: x.index))
        return cls(
            id=str(_require(payload, "id")),
            name=str(_require(payload, "name")),
            description=str(payload.get("description", "")),
            rules=Ruleset.from_dict(payload.get("rules", {})),
            towers=towers,
            enemies=enemies,
            waves=waves,
            global_modifiers=global_modifiers,
            economy=EconomyDefinition.from_dict(payload.get("economy", {})),
        )


@dataclass(slots=True, frozen=True)
class TowerPlan:
    tower_id: str
    count: int
    level: int
    focus_priorities: tuple[str, ...] = ("progress", "lowest_hp")
    focus_until_death: bool = False

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TowerPlan":
        return cls(
            tower_id=str(_require(payload, "tower_id")),
            count=int(payload.get("count", 1)),
            level=int(payload.get("level", 0)),
            focus_priorities=tuple(str(item) for item in payload.get("focus_priorities", ["progress", "lowest_hp"])),
            focus_until_death=bool(payload.get("focus_until_death", False)),
        )


@dataclass(slots=True, frozen=True)
class BuildAction:
    wave: int
    at_s: float
    type: str
    target_id: str = ""
    value: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "BuildAction":
        return cls(
            wave=int(_require(payload, "wave")),
            at_s=float(payload.get("at_s", 0.0)),
            type=str(_require(payload, "type")),
            target_id=str(payload.get("target_id", "")),
            value=float(payload.get("value", 0.0)),
            payload=dict(payload.get("payload", {})),
        )


@dataclass(slots=True, frozen=True)
class BuildPlan:
    scenario_id: str
    towers: tuple[TowerPlan, ...]
    active_global_modifiers: tuple[str, ...] = tuple()
    actions: tuple[BuildAction, ...] = tuple()

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "BuildPlan":
        actions = tuple(
            sorted(
                (BuildAction.from_dict(item) for item in payload.get("actions", [])),
                key=lambda action: (action.wave, action.at_s),
            )
        )
        return cls(
            scenario_id=str(_require(payload, "scenario_id")),
            towers=tuple(TowerPlan.from_dict(item) for item in payload.get("towers", [])),
            active_global_modifiers=tuple(str(item) for item in payload.get("active_global_modifiers", [])),
            actions=actions,
        )


@dataclass(slots=True, frozen=True)
class WaveResult:
    wave: int
    potential_damage: float
    combat_damage: float
    effective_dps: float
    clear_time_s: float
    leaks: float
    enemy_hp_pool: float
    breakdown: Dict[str, float]


@dataclass(slots=True, frozen=True)
class EvaluationResult:
    mode: str
    scenario_id: str
    dataset_version: str
    seed: int
    monte_carlo_runs: int
    wave_results: tuple[WaveResult, ...]
    economy_totals: Dict[str, Any] = field(default_factory=dict)

    @property
    def totals(self) -> Dict[str, Any]:
        potential = sum(item.potential_damage for item in self.wave_results)
        combat = sum(item.combat_damage for item in self.wave_results)
        leaks = sum(item.leaks for item in self.wave_results)
        return {
            "potential_damage": potential,
            "combat_damage": combat,
            "leaks": leaks,
            "economy": normalize_economy_totals(self.economy_totals),
        }

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("economy_totals", None)
        payload["wave_results"] = [asdict(item) for item in self.wave_results]
        payload["totals"] = self.totals
        return _stabilize_numeric_payload(payload)


@dataclass(slots=True, frozen=True)
class ReplaySnapshot:
    timestamp: float
    wave: int
    gold: float = 0.0
    essence: float = 0.0
    build: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ReplaySession:
    session_id: str
    source: str
    snapshots: tuple[ReplaySnapshot, ...]


@dataclass(slots=True, frozen=True)
class LiveSnapshot:
    timestamp: float
    wave: int
    gold: float
    essence: float
    build: Dict[str, Any]
    source_mode: Literal["memory", "replay", "synthetic"]


def ensure_unique_ids(items: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise ModelError(f"Duplicate {label} id: {item}")
        seen.add(item)
