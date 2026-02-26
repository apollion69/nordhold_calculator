from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import product
from typing import Callable, Dict, Iterable, Iterator, List, MutableMapping, Sequence, Tuple

from .models import (
    Config,
    Modifier,
    StackMode,
    StatEffect,
    StatTarget,
    Tower,
    TowerUpgrade,
    ValueType,
)


@dataclass(slots=True, frozen=True)
class TowerVariant:
    tower: Tower
    level: int
    cost: float
    upgrade_cost: float
    upgrades: Tuple[TowerUpgrade, ...]
    upgrade_effects: Tuple[StatEffect, ...]
    tags: frozenset[str]

    @property
    def display_name(self) -> str:
        if not self.upgrades:
            return self.tower.name
        names = " -> ".join(upgrade.name for upgrade in self.upgrades)
        return f"{self.tower.name} [{names}]"


def _cumulative_variants(tower: Tower) -> Tuple[TowerVariant, ...]:
    variants: List[TowerVariant] = []
    current_effects: List[StatEffect] = []
    current_tags = set(tower.tags)
    total_cost = tower.cost
    upgrade_cost = 0.0

    variants.append(
        TowerVariant(
            tower=tower,
            level=0,
            cost=total_cost,
            upgrade_cost=upgrade_cost,
            upgrades=tuple(),
            upgrade_effects=tuple(),
            tags=frozenset(current_tags),
        )
    )

    for level, upgrade in enumerate(tower.upgrades, start=1):
        upgrade_cost += upgrade.cost
        total_cost = tower.cost + upgrade_cost
        current_effects.extend(upgrade.effects)
        current_tags.difference_update(upgrade.remove_tags)
        current_tags.update(upgrade.add_tags)

        variants.append(
            TowerVariant(
                tower=tower,
                level=level,
                cost=total_cost,
                upgrade_cost=upgrade_cost,
                upgrades=tuple(tower.upgrades[:level]),
                upgrade_effects=tuple(current_effects),
                tags=frozenset(current_tags),
            )
        )

    return tuple(variants)


@dataclass(slots=True, frozen=True)
class ModifierInstance:
    modifier: Modifier
    category: str
    stack_index: int

    @property
    def label(self) -> str:
        if self.stack_index <= 1:
            return f"{self.modifier.name} ({self.category})"
        return f"{self.modifier.name}#{self.stack_index} ({self.category})"


@dataclass(slots=True)
class StatContribution:
    source: str
    effect: StatEffect


@dataclass(slots=True)
class StatBreakdown:
    base: float
    base_override: StatContribution | None
    flat: List[StatContribution]
    percent_add: List[StatContribution]
    percent_mult: List[StatContribution]
    multipliers: List[StatContribution]
    final_value: float

    def compact_summary(self) -> str:
        add_pct = sum(entry.effect.value for entry in self.percent_add)
        mult_pct_factor = math.prod(1.0 + entry.effect.value for entry in self.percent_mult) if self.percent_mult else 1.0
        mult_pct = mult_pct_factor - 1.0
        multipliers_factor = math.prod(entry.effect.value for entry in self.multipliers) if self.multipliers else 1.0
        base = self.base_override.effect.value if self.base_override else self.base
        flat_total = sum(entry.effect.value for entry in self.flat)
        parts = [
            f"base {base:.2f}",
        ]
        if flat_total:
            parts.append(f"+flat {flat_total:+.2f}")
        if add_pct:
            parts.append(f"+add% {add_pct * 100:+.1f}%")
        if self.percent_mult:
            parts.append(f"*mult% {(1 + mult_pct):.3f} ({mult_pct * 100:+.1f}%)")
        if self.multipliers:
            parts.append(f"*mult {multipliers_factor:.3f}")
        return "; ".join(parts)


@dataclass(slots=True)
class TowerEvaluation:
    variant: TowerVariant
    damage: StatBreakdown
    attack_speed: StatBreakdown
    dps: float
    applied_modifiers: List[ModifierInstance]


@dataclass(slots=True)
class LineupEvaluation:
    towers: Tuple[TowerVariant, ...]
    modifier_selection: Dict[str, Tuple[ModifierInstance, ...]]
    per_tower: List[TowerEvaluation]
    total_dps: float
    total_cost: float


def _modifier_applies(modifier: Modifier, variant: TowerVariant) -> bool:
    if modifier.applies_to:
        tokens = set(variant.tags)
        tokens.add(variant.tower.name.lower())
        return bool(modifier.applies_to & tokens)
    return modifier.global_scope


def _stat_accumulator(base_value: float) -> Dict[str, List[StatContribution]]:
    return {
        "base_override": [],
        "flat": [],
        "percent_add": [],
        "percent_mult": [],
        "multipliers": [],
    }


def _apply_effect(
    accumulator: MutableMapping[str, List[StatContribution]],
    effect: StatEffect,
    source: str,
):
    contribution = StatContribution(source=source, effect=effect)

    if effect.stack_mode is StackMode.OVERRIDE:
        accumulator["base_override"].append(contribution)
        return

    if effect.value_type is ValueType.FLAT:
        accumulator["flat"].append(contribution)
        return

    if effect.value_type is ValueType.PERCENT:
        if effect.stack_mode is StackMode.ADD:
            accumulator["percent_add"].append(contribution)
            return
        if effect.stack_mode is StackMode.MULT:
            accumulator["percent_mult"].append(contribution)
            return
        raise ValueError(
            f"Unsupported stack '{effect.stack_mode.value}' for percent effect from {source}."
        )

    if effect.value_type is ValueType.MULTIPLIER:
        if effect.stack_mode is not StackMode.MULT:
            raise ValueError(
                f"Multiplier effect from {source} must use 'mult' stacking."
            )
        accumulator["multipliers"].append(contribution)
        return

    raise ValueError(f"Unsupported effect type '{effect.value_type.value}' from {source}.")


def _finalize_breakdown(
    base_value: float,
    accumulator: MutableMapping[str, List[StatContribution]],
) -> StatBreakdown:
    base_override = accumulator["base_override"][-1] if accumulator["base_override"] else None
    base = base_override.effect.value if base_override else base_value

    flat_total = sum(entry.effect.value for entry in accumulator["flat"])
    value = base + flat_total

    add_pct = sum(entry.effect.value for entry in accumulator["percent_add"])
    value *= 1.0 + add_pct

    if accumulator["percent_mult"]:
        value *= math.prod(1.0 + entry.effect.value for entry in accumulator["percent_mult"])

    if accumulator["multipliers"]:
        value *= math.prod(entry.effect.value for entry in accumulator["multipliers"])

    return StatBreakdown(
        base=base_value,
        base_override=base_override,
        flat=list(accumulator["flat"]),
        percent_add=list(accumulator["percent_add"]),
        percent_mult=list(accumulator["percent_mult"]),
        multipliers=list(accumulator["multipliers"]),
        final_value=value,
    )


def evaluate_tower(
    variant: TowerVariant,
    global_effects: Sequence[StatEffect],
    modifier_instances: Sequence[ModifierInstance],
) -> TowerEvaluation:
    damage_acc = _stat_accumulator(variant.tower.base_damage)
    speed_acc = _stat_accumulator(variant.tower.attack_speed)

    def apply_effects(effects: Sequence[StatEffect], source: str):
        for effect in effects:
            if effect.target is StatTarget.DAMAGE:
                _apply_effect(damage_acc, effect, source)
            elif effect.target is StatTarget.ATTACK_SPEED:
                _apply_effect(speed_acc, effect, source)

    # Upgrades first
    if variant.upgrade_effects:
        apply_effects(variant.upgrade_effects, source=variant.display_name)

    # Global effects
    if global_effects:
        apply_effects(global_effects, source="Global Effect")

    applied_instances: List[ModifierInstance] = []
    for instance in modifier_instances:
        modifier = instance.modifier
        if not _modifier_applies(modifier, variant):
            continue
        apply_effects(modifier.effects, source=instance.label)
        applied_instances.append(instance)

    damage_breakdown = _finalize_breakdown(variant.tower.base_damage, damage_acc)
    speed_breakdown = _finalize_breakdown(variant.tower.attack_speed, speed_acc)
    dps = damage_breakdown.final_value * speed_breakdown.final_value

    return TowerEvaluation(
        variant=variant,
        damage=damage_breakdown,
        attack_speed=speed_breakdown,
        dps=dps,
        applied_modifiers=applied_instances,
    )


def _build_modifier_instances(
    forced_modifiers: Sequence[Modifier],
    selection: Dict[str, Tuple[Modifier, ...]],
) -> Dict[str, Tuple[ModifierInstance, ...]]:
    result: Dict[str, Tuple[ModifierInstance, ...]] = {}

    if forced_modifiers:
        forced_instances = tuple(
            ModifierInstance(modifier=modifier, category=modifier.category, stack_index=index + 1)
            for index, modifier in enumerate(forced_modifiers)
        )
        result["forced"] = forced_instances

    for category, modifiers in selection.items():
        instances: List[ModifierInstance] = []
        stack_counters: Counter[str] = Counter()
        for modifier in modifiers:
            stack_counters[modifier.name] += 1
            instances.append(
                ModifierInstance(
                    modifier=modifier,
                    category=category,
                    stack_index=stack_counters[modifier.name],
                )
            )
        result[category] = tuple(instances)
    return result


def evaluate_lineup(
    lineup: Sequence[TowerVariant],
    modifier_selection: Dict[str, Tuple[Modifier, ...]],
    config: Config,
) -> LineupEvaluation:
    instance_map = _build_modifier_instances(config.forced_modifiers, modifier_selection)
    combined_instances: List[ModifierInstance] = []
    for instances in instance_map.values():
        combined_instances.extend(instances)

    per_tower: List[TowerEvaluation] = []
    total_cost = 0.0
    for variant in lineup:
        eval_result = evaluate_tower(
            variant=variant,
            global_effects=config.global_effects,
            modifier_instances=combined_instances,
        )
        per_tower.append(eval_result)
        total_cost += variant.cost

    modifier_cost = sum(instance.modifier.cost for instance in combined_instances)
    total_cost += modifier_cost

    total_dps = sum(entry.dps for entry in per_tower)
    selection_instances = {
        category: tuple(instance_map.get(category, ()))
        for category in instance_map.keys()
    }
    return LineupEvaluation(
        towers=tuple(lineup),
        modifier_selection=selection_instances,
        per_tower=per_tower,
        total_dps=total_dps,
        total_cost=total_cost,
    )


def _category_combinations(
    modifiers: Sequence[Modifier],
    limit: int,
) -> Iterator[Tuple[Modifier, ...]]:
    if not modifiers or limit <= 0:
        yield tuple()
        return

    current: List[Modifier] = []

    def backtrack(index: int, used: int, has_exclusive: bool):
        if index == len(modifiers):
            yield tuple(current)
            return

        modifier = modifiers[index]

        # Option: skip
        yield from backtrack(index + 1, used, has_exclusive)

        if has_exclusive or used >= limit:
            return

        max_use = min(modifier.max_stacks, limit - used)
        for count in range(1, max_use + 1):
            if modifier.exclusive and count > 1:
                break
            current.extend([modifier] * count)
            yield from backtrack(
                index + 1,
                used + count,
                has_exclusive or modifier.exclusive,
            )
            del current[-count:]

    yield from backtrack(0, 0, False)


def _generate_modifier_selections(config: Config) -> Iterator[Dict[str, Tuple[Modifier, ...]]]:
    if not config.modifiers:
        yield {}
        return

    categories = sorted(config.modifiers.keys())
    category_options: List[List[Tuple[Modifier, ...]]] = []
    for category in categories:
        modifiers = config.modifiers[category]
        limit = config.selection_limits.limit_for(category, default=len(modifiers))
        combos = list(_category_combinations(modifiers, limit))
        category_options.append(combos)

    for combination in product(*category_options):
        selection = {
            category: combination[idx]
            for idx, category in enumerate(categories)
        }
        yield selection


def _prepare_variants(config: Config) -> Tuple[Tuple[TowerVariant, ...], ...]:
    return tuple(_cumulative_variants(tower) for tower in config.towers)


def tower_variants_map(config: Config) -> Dict[str, Tuple[TowerVariant, ...]]:
    """Expose tower variants for UI/manual calculations."""
    return {tower.name: _cumulative_variants(tower) for tower in config.towers}


def tower_variant_for_level(tower: Tower, level: int) -> TowerVariant:
    variants = _cumulative_variants(tower)
    if not variants:
        raise ValueError(f"No variants generated for tower '{tower.name}'.")
    if level <= 0:
        return variants[0]
    if level >= len(variants):
        return variants[-1]
    return variants[level]


def _generate_lineups(config: Config) -> Iterator[Tuple[TowerVariant, ...]]:
    tower_variants = _prepare_variants(config)
    slots = config.tower_slots

    options: List[Tuple[int, TowerVariant]] = []
    for tower_index, variants in enumerate(tower_variants):
        for variant in variants:
            options.append((tower_index, variant))

    current: List[TowerVariant] = []
    tower_usage: Dict[int, int] = defaultdict(int)

    def backtrack(start: int, remaining: int):
        if remaining == 0:
            yield tuple(current)
            return
        if start >= len(options):
            return

        for option_index in range(start, len(options)):
            tower_index, variant = options[option_index]
            tower = variant.tower
            if tower_usage[tower_index] >= tower.max_count:
                continue
            current.append(variant)
            tower_usage[tower_index] += 1
            yield from backtrack(option_index, remaining - 1)
            tower_usage[tower_index] -= 1
            current.pop()

    yield from backtrack(0, slots)


ProgressCallback = Callable[[int, int], None]


def search_best_lineups(
    config: Config,
    top_n: int = 10,
    max_cost: float | None = None,
    progress_callback: ProgressCallback | None = None,
) -> List[LineupEvaluation]:
    lineups = list(_generate_lineups(config))
    if not lineups:
        raise RuntimeError(
            "Не удалось подобрать комбинации башен: проверьте 'tower_slots' и 'max_count'."
        )

    modifier_selections = list(_generate_modifier_selections(config))
    if not modifier_selections:
        modifier_selections = [{}]

    total_steps = len(lineups) * len(modifier_selections) if modifier_selections else len(lineups)
    completed = 0

    results: List[LineupEvaluation] = []
    for lineup in lineups:
        for selection in modifier_selections:
            evaluation = evaluate_lineup(lineup, selection, config)
            if max_cost is not None and evaluation.total_cost > max_cost:
                continue
            results.append(evaluation)
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, total_steps)

    results.sort(key=lambda entry: entry.total_dps, reverse=True)
    return results[:top_n]
