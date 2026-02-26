from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import (
    BuildAction,
    BuildPlan,
    DotEffect,
    EconomyDefinition,
    EconomyPolicy,
    EnemyDefinition,
    EvaluationResult,
    Modifier,
    Ruleset,
    ScenarioDefinition,
    TowerDefinition,
    TowerPlan,
    TowerStats,
    WaveDefinition,
    WaveResult,
    normalize_economy_totals,
)


EPS = 1e-9


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _apply_modifier(value: float, modifier: Modifier) -> float:
    if modifier.op == "add":
        return value + modifier.value
    if modifier.op == "mul":
        return value * modifier.value
    if modifier.op == "set":
        return modifier.value
    if modifier.op == "cap_max":
        return min(value, modifier.value)
    if modifier.op == "cap_min":
        return max(value, modifier.value)
    return value


def _apply_stat_modifiers(base: TowerStats, modifiers: Iterable[Modifier]) -> TowerStats:
    values: Dict[str, float] = {
        "damage": base.damage,
        "fire_rate": base.fire_rate,
        "crit_chance": base.crit_chance,
        "crit_multiplier": base.crit_multiplier,
        "accuracy": base.accuracy,
        "penetration": base.penetration,
        "barrier_damage_multiplier": base.barrier_damage_multiplier,
    }
    for modifier in modifiers:
        if modifier.target not in values:
            continue
        values[modifier.target] = _apply_modifier(values[modifier.target], modifier)

    return TowerStats(
        damage=max(0.0, values["damage"]),
        fire_rate=max(EPS, values["fire_rate"]),
        crit_chance=_clamp(values["crit_chance"], 0.0, 1.0),
        crit_multiplier=max(1.0, values["crit_multiplier"]),
        accuracy=_clamp(values["accuracy"], 0.0, 1.0),
        penetration=_clamp(values["penetration"], 0.0, 1.0),
        barrier_damage_multiplier=max(0.01, values["barrier_damage_multiplier"]),
    )


def _resolve_tower_stats(
    tower: TowerDefinition,
    level: int,
    global_modifiers: Sequence[Modifier],
) -> TowerStats:
    modifiers: List[Modifier] = []
    for upgrade in sorted(tower.upgrade_levels, key=lambda item: item.level):
        if upgrade.level > level:
            break
        modifiers.extend(upgrade.modifiers)
    modifiers.extend(global_modifiers)
    return _apply_stat_modifiers(tower.base_stats, modifiers)


def _hit_chance(stats: TowerStats, enemy: EnemyDefinition, rules: Ruleset) -> float:
    if rules.accuracy_block_model == "multiplicative":
        return _clamp(stats.accuracy * (1.0 - enemy.block), 0.0, 1.0)
    # linear_subtract: block is neutralized by equal/greater accuracy.
    return _clamp(1.0 - max(0.0, enemy.block - stats.accuracy), 0.0, 1.0)


def _effective_armor(enemy: EnemyDefinition, stats: TowerStats, rules: Ruleset) -> float:
    if rules.armor_penetration_model == "multiplicative":
        return _clamp(enemy.armor * (1.0 - stats.penetration), 0.0, 1.0)
    return _clamp(max(0.0, enemy.armor - stats.penetration), 0.0, 1.0)


def _armor_damage_factor(enemy: EnemyDefinition, stats: TowerStats, rules: Ruleset) -> float:
    return max(0.0, 1.0 - _effective_armor(enemy, stats, rules))


def _crit_factor_expected(stats: TowerStats) -> float:
    return (1.0 - stats.crit_chance) + (stats.crit_chance * stats.crit_multiplier)


@dataclass(slots=True)
class RuntimeTower:
    tower_id: str
    level: int
    focus_priorities: Tuple[str, ...]
    focus_until_death: bool


@dataclass(slots=True)
class RuntimeState:
    towers: List[RuntimeTower]
    active_modifier_ids: List[str]


@dataclass(slots=True)
class RuntimeEconomyState:
    total_workers: int
    workers_gold: int
    workers_essence: int
    workers_unassigned: int
    policy_id: str
    build_count: int


def _initial_runtime_state(build: BuildPlan) -> RuntimeState:
    towers: List[RuntimeTower] = []
    for plan in build.towers:
        for _ in range(max(0, plan.count)):
            towers.append(
                RuntimeTower(
                    tower_id=plan.tower_id,
                    level=max(0, plan.level),
                    focus_priorities=tuple(plan.focus_priorities),
                    focus_until_death=bool(plan.focus_until_death),
                )
            )
    return RuntimeState(towers=towers, active_modifier_ids=list(build.active_global_modifiers))


def _apply_action_to_state(state: RuntimeState, action: BuildAction) -> None:
    action_type = action.type.lower().strip()

    if action_type == "build":
        tower_id = str(action.payload.get("tower_id", action.target_id)).strip()
        if not tower_id:
            return
        count = int(action.payload.get("count", max(1, int(action.value) if action.value else 1)))
        level = int(action.payload.get("level", 0))
        focus_priorities = tuple(action.payload.get("focus_priorities", ["progress", "lowest_hp"]))
        focus_until_death = bool(action.payload.get("focus_until_death", False))
        for _ in range(max(0, count)):
            state.towers.append(
                RuntimeTower(
                    tower_id=tower_id,
                    level=max(0, level),
                    focus_priorities=focus_priorities,
                    focus_until_death=focus_until_death,
                )
            )
        return

    if action_type == "sell":
        target_id = action.target_id
        for idx, tower in enumerate(state.towers):
            if tower.tower_id == target_id:
                state.towers.pop(idx)
                break
        return

    if action_type == "upgrade":
        target_id = action.target_id
        delta = int(action.payload.get("levels", action.value if action.value else 1))
        for tower in state.towers:
            if tower.tower_id == target_id:
                tower.level = max(0, tower.level + delta)
                break
        return

    if action_type == "modifier":
        modifier_id = str(action.payload.get("modifier_id", action.target_id)).strip()
        if not modifier_id:
            return
        enable = bool(action.payload.get("enabled", action.value >= 0.0))
        if enable and modifier_id not in state.active_modifier_ids:
            state.active_modifier_ids.append(modifier_id)
        if (not enable) and modifier_id in state.active_modifier_ids:
            state.active_modifier_ids.remove(modifier_id)
        return

    if action_type == "targeting":
        target_id = action.target_id
        new_priorities = tuple(action.payload.get("focus_priorities", ["progress", "lowest_hp"]))
        sticky = bool(action.payload.get("focus_until_death", False))
        for tower in state.towers:
            if tower.tower_id == target_id:
                tower.focus_priorities = new_priorities
                tower.focus_until_death = sticky


def _runtime_for_wave(build: BuildPlan, wave_index: int) -> RuntimeState:
    state = _initial_runtime_state(build)
    for action in build.actions:
        if action.wave > wave_index:
            break
        _apply_action_to_state(state, action)
    return state


def _initial_economy_state(scenario: ScenarioDefinition) -> RuntimeEconomyState:
    economy = scenario.economy
    total_workers = max(0, economy.initial_workers)
    workers_gold = max(0, min(total_workers, economy.initial_workers_gold))
    workers_essence = max(0, min(total_workers - workers_gold, economy.initial_workers_essence))
    workers_unassigned = max(0, total_workers - workers_gold - workers_essence)
    policy_id = economy.default_policy_id if economy.default_policy_id in economy.policies else "balanced"
    return RuntimeEconomyState(
        total_workers=total_workers,
        workers_gold=workers_gold,
        workers_essence=workers_essence,
        workers_unassigned=workers_unassigned,
        policy_id=policy_id,
        build_count=0,
    )


def _resolve_economy_policy(economy: EconomyDefinition, policy_id: str) -> EconomyPolicy:
    if policy_id in economy.policies:
        return economy.policies[policy_id]
    if economy.default_policy_id in economy.policies:
        return economy.policies[economy.default_policy_id]
    return EconomyPolicy(id="balanced")


def _baseline_resources_for_wave(economy: EconomyDefinition, wave_index: int) -> Tuple[float, float]:
    for item in economy.wave_resource_baseline:
        if item.wave == wave_index:
            return item.gold, item.essence
    return economy.default_wave_gold, economy.default_wave_essence


def _apply_worker_distribution(state: RuntimeEconomyState, workers_gold: int, workers_essence: int) -> None:
    workers_gold = max(0, workers_gold)
    workers_essence = max(0, workers_essence)
    if workers_gold + workers_essence > state.total_workers:
        overflow = workers_gold + workers_essence - state.total_workers
        if workers_essence >= overflow:
            workers_essence -= overflow
        else:
            overflow -= workers_essence
            workers_essence = 0
            workers_gold = max(0, workers_gold - overflow)
    state.workers_gold = workers_gold
    state.workers_essence = workers_essence
    state.workers_unassigned = max(0, state.total_workers - workers_gold - workers_essence)


def _apply_assign_workers_action(state: RuntimeEconomyState, action: BuildAction) -> None:
    payload = action.payload if isinstance(action.payload, dict) else {}
    explicit_gold = payload.get("gold_workers", payload.get("gold"))
    explicit_essence = payload.get("essence_workers", payload.get("essence"))
    if explicit_gold is not None or explicit_essence is not None:
        target_gold = state.workers_gold if explicit_gold is None else int(explicit_gold)
        target_essence = state.workers_essence if explicit_essence is None else int(explicit_essence)
        _apply_worker_distribution(state, target_gold, target_essence)
        return

    resource = str(payload.get("resource", action.target_id)).lower().strip()
    delta = int(payload.get("count", action.value if action.value else 0))
    if resource not in {"gold", "essence"} or delta == 0:
        return

    if delta > 0:
        moved = min(state.workers_unassigned, delta)
        if resource == "gold":
            state.workers_gold += moved
        else:
            state.workers_essence += moved
        state.workers_unassigned -= moved
        return

    amount = min(state.workers_gold if resource == "gold" else state.workers_essence, abs(delta))
    if resource == "gold":
        state.workers_gold -= amount
    else:
        state.workers_essence -= amount
    state.workers_unassigned += amount


def _apply_economy_policy_action(state: RuntimeEconomyState, action: BuildAction, economy: EconomyDefinition) -> None:
    payload = action.payload if isinstance(action.payload, dict) else {}
    requested_policy = str(payload.get("policy_id", payload.get("policy", action.target_id))).strip()
    if requested_policy and requested_policy in economy.policies:
        state.policy_id = requested_policy


def _build_action_count(action: BuildAction) -> int:
    return max(0, int(action.payload.get("count", max(1, int(action.value) if action.value else 1))))


def _build_action_level(action: BuildAction) -> int:
    return max(0, int(action.payload.get("level", 0)))


def _build_action_tower_id(action: BuildAction) -> str:
    return str(action.payload.get("tower_id", action.target_id)).strip()


def _approx_build_cost(scenario: ScenarioDefinition, tower_id: str, level: int) -> float:
    tower = scenario.towers.get(tower_id)
    if tower is None:
        return 75.0 + (25.0 * max(0, level))

    upgrades = sorted(tower.upgrade_levels, key=lambda item: item.level)
    if not upgrades:
        return 75.0 + (25.0 * max(0, level))

    base = max(1.0, float(upgrades[0].cost))
    if level <= 1:
        return base

    extra = 0.0
    for upgrade in upgrades:
        if 1 < upgrade.level <= level:
            extra += max(0.0, upgrade.cost)
    return max(1.0, base + extra)


def _evaluate_economy_totals(scenario: ScenarioDefinition, build: BuildPlan) -> Dict[str, object]:
    economy = scenario.economy
    state = _initial_economy_state(scenario)
    actions_by_wave: Dict[int, List[BuildAction]] = {}
    for action in build.actions:
        actions_by_wave.setdefault(action.wave, []).append(action)

    baseline_gold_total = 0.0
    baseline_essence_total = 0.0
    worker_gold_income_total = 0.0
    worker_essence_income_total = 0.0
    build_spend_gold_total = 0.0
    build_inflation_gold_total = 0.0
    build_actions_total = 0

    for wave in scenario.waves:
        baseline_gold, baseline_essence = _baseline_resources_for_wave(economy, wave.index)
        baseline_gold_total += baseline_gold
        baseline_essence_total += baseline_essence

        policy = _resolve_economy_policy(economy, state.policy_id)
        worker_gold_income_total += float(state.workers_gold) * economy.worker_gold_income_per_wave * policy.worker_gold_multiplier
        worker_essence_income_total += float(state.workers_essence) * economy.worker_essence_income_per_wave * policy.worker_essence_multiplier

        for action in actions_by_wave.get(wave.index, []):
            action_type = action.type.lower().strip()
            if action_type == "assign_workers":
                _apply_assign_workers_action(state, action)
                continue

            if action_type == "economy_policy":
                _apply_economy_policy_action(state, action, economy)
                continue

            if action_type != "build":
                continue

            count = _build_action_count(action)
            if count <= 0:
                continue

            tower_id = _build_action_tower_id(action)
            level = _build_action_level(action)
            unit_cost = _approx_build_cost(scenario, tower_id, level)
            base_cost = unit_cost * float(count)

            inflation_multiplier = 1.0 + (max(0.0, economy.build_cost_inflation_rate) * float(state.build_count))
            inflation_multiplier = min(max(1.0, economy.build_cost_inflation_max_multiplier), inflation_multiplier)
            current_policy = _resolve_economy_policy(economy, state.policy_id)
            policy_multiplier = max(0.1, current_policy.build_cost_multiplier)
            total_cost = base_cost * inflation_multiplier * policy_multiplier

            build_spend_gold_total += total_cost
            build_inflation_gold_total += max(0.0, total_cost - base_cost)
            build_actions_total += count
            state.build_count += count

    gross_gold_income = baseline_gold_total + worker_gold_income_total
    gross_essence_income = baseline_essence_total + worker_essence_income_total
    return normalize_economy_totals(
        {
            "baseline_gold": baseline_gold_total,
            "baseline_essence": baseline_essence_total,
            "worker_gold_income": worker_gold_income_total,
            "worker_essence_income": worker_essence_income_total,
            "gross_gold_income": gross_gold_income,
            "gross_essence_income": gross_essence_income,
            "build_spend_gold": build_spend_gold_total,
            "build_inflation_gold": build_inflation_gold_total,
            "build_actions": build_actions_total,
            "net_gold": gross_gold_income - build_spend_gold_total,
            "net_essence": gross_essence_income,
            "policy_id": state.policy_id,
            "workers": {
                "total": state.total_workers,
                "gold": state.workers_gold,
                "essence": state.workers_essence,
                "unassigned": state.workers_unassigned,
            },
        }
    )


def _dot_expected_dps(dot: DotEffect, rules: Ruleset, global_damage_factor: float) -> float:
    total_ticks = max(1, int(dot.duration_s / max(EPS, dot.tick_interval_s)))
    total = dot.damage_per_tick * float(total_ticks)
    if rules.dot_scaling_policy == "global":
        total *= global_damage_factor
    return total / max(EPS, dot.duration_s)


def _expected_wave(
    scenario: ScenarioDefinition,
    wave: WaveDefinition,
    runtime: RuntimeState,
) -> WaveResult:
    enemy_counts: Dict[str, int] = {}
    for spawn in wave.spawns:
        enemy_counts[spawn.enemy_id] = enemy_counts.get(spawn.enemy_id, 0) + spawn.count

    total_enemies = sum(enemy_counts.values())
    if total_enemies <= 0:
        return WaveResult(
            wave=wave.index,
            potential_damage=0.0,
            combat_damage=0.0,
            effective_dps=0.0,
            clear_time_s=0.0,
            leaks=0.0,
            enemy_hp_pool=0.0,
            breakdown={},
        )

    active_modifiers: List[Modifier] = []
    for modifier_id in runtime.active_modifier_ids:
        modifier = scenario.global_modifiers.get(modifier_id)
        if modifier is not None:
            active_modifiers.extend(modifier.modifiers)

    per_tower_dps: Dict[str, float] = {}
    effective_dps = 0.0

    for runtime_tower in runtime.towers:
        tower_def = scenario.towers.get(runtime_tower.tower_id)
        if tower_def is None:
            continue
        stats = _resolve_tower_stats(tower_def, runtime_tower.level, active_modifiers)
        tower_mix_dps = 0.0
        for enemy_id, count in enemy_counts.items():
            enemy = scenario.enemies.get(enemy_id)
            if enemy is None:
                continue
            weight = count / float(total_enemies)
            hit = _hit_chance(stats, enemy, scenario.rules)
            armor_factor = _armor_damage_factor(enemy, stats, scenario.rules)
            direct_per_shot = stats.damage * _crit_factor_expected(stats) * hit * armor_factor
            enemy_dps = direct_per_shot * stats.fire_rate

            if enemy.barrier > 0.0:
                barrier_scale = (enemy.hp + enemy.barrier / max(EPS, stats.barrier_damage_multiplier)) / max(EPS, enemy.hp + enemy.barrier)
                enemy_dps *= barrier_scale

            dot_dps = 0.0
            for dot in tower_def.dot_effects:
                dot_dps += _dot_expected_dps(dot, scenario.rules, _crit_factor_expected(stats))
            tower_mix_dps += (enemy_dps + dot_dps) * weight

        key = tower_def.name
        per_tower_dps[key] = per_tower_dps.get(key, 0.0) + tower_mix_dps
        effective_dps += tower_mix_dps

    enemy_hp_pool = 0.0
    enemy_unit_pool = 0.0
    for enemy_id, count in enemy_counts.items():
        enemy = scenario.enemies.get(enemy_id)
        if enemy is None:
            continue
        enemy_hp_pool += (enemy.hp + enemy.barrier) * count
        enemy_unit_pool += enemy.hp * count

    potential_damage = effective_dps * wave.duration_s
    combat_damage = min(enemy_hp_pool, potential_damage)
    clear_time_s = enemy_hp_pool / max(EPS, effective_dps)
    leaks = max(0.0, enemy_hp_pool - potential_damage) / max(EPS, enemy_unit_pool)

    return WaveResult(
        wave=wave.index,
        potential_damage=potential_damage,
        combat_damage=combat_damage,
        effective_dps=effective_dps,
        clear_time_s=min(wave.duration_s, clear_time_s),
        leaks=leaks,
        enemy_hp_pool=enemy_hp_pool,
        breakdown=per_tower_dps,
    )


@dataclass(slots=True)
class _EnemyInstance:
    uid: int
    definition: EnemyDefinition
    spawn_time: float
    hp: float
    barrier: float
    dots: Dict[int, Dict[str, float]]
    alive: bool = True


@dataclass(slots=True)
class _TowerInstance:
    uid: int
    definition: TowerDefinition
    stats: TowerStats
    focus_priorities: Tuple[str, ...]
    focus_until_death: bool
    sticky_target_uid: int | None = None


def _target_score(enemy: _EnemyInstance, now: float, priority: str) -> float:
    progress = max(0.0, now - enemy.spawn_time) * max(0.0, enemy.definition.speed)
    hp_total = enemy.hp + enemy.barrier

    if priority == "progress" or priority == "closest_to_gate":
        return progress
    if priority == "lowest_hp":
        return -hp_total
    if priority == "highest_hp":
        return hp_total
    if priority == "fastest":
        return enemy.definition.speed
    if priority == "barrier":
        return enemy.barrier
    if priority == "boss_elite":
        return 1.0 if "boss" in enemy.definition.tags or "elite" in enemy.definition.tags else 0.0
    if priority == "healer":
        return 1.0 if "healer" in enemy.definition.tags else 0.0
    if priority == "summoner" or priority == "spawner":
        return 1.0 if "summoner" in enemy.definition.tags or "spawner" in enemy.definition.tags else 0.0
    return progress


def _pick_target(now: float, tower: _TowerInstance, enemies: Sequence[_EnemyInstance]) -> _EnemyInstance | None:
    alive = [enemy for enemy in enemies if enemy.alive and now >= enemy.spawn_time]
    if not alive:
        return None

    if tower.focus_until_death and tower.sticky_target_uid is not None:
        for candidate in alive:
            if candidate.uid == tower.sticky_target_uid:
                return candidate

    priorities = tower.focus_priorities or ("progress",)
    alive.sort(
        key=lambda enemy: tuple(_target_score(enemy, now, priority) for priority in priorities),
        reverse=True,
    )
    target = alive[0]
    if tower.focus_until_death:
        tower.sticky_target_uid = target.uid
    return target


def _apply_direct_damage(
    enemy: _EnemyInstance,
    tower: _TowerInstance,
    rules: Ruleset,
    rng: random.Random,
    sampled: bool,
) -> float:
    if not enemy.alive:
        return 0.0

    stats = tower.stats
    hit = _hit_chance(stats, enemy.definition, rules)
    if sampled and rng.random() > hit:
        return 0.0

    if sampled:
        critical = stats.crit_multiplier if rng.random() < stats.crit_chance else 1.0
    else:
        critical = _crit_factor_expected(stats)

    direct = stats.damage * critical
    armor_factor = _armor_damage_factor(enemy.definition, stats, rules)

    total_damage = 0.0
    if enemy.barrier > EPS:
        barrier_factor = armor_factor if rules.barrier_inherits_armor else 1.0
        barrier_damage = direct * stats.barrier_damage_multiplier * barrier_factor
        absorbed = min(enemy.barrier, barrier_damage)
        enemy.barrier -= absorbed
        total_damage += absorbed

        overflow = max(0.0, barrier_damage - absorbed)
        if overflow > EPS:
            hp_damage = overflow * armor_factor
            dealt = min(enemy.hp, hp_damage)
            enemy.hp -= dealt
            total_damage += dealt
    else:
        hp_damage = direct * armor_factor
        dealt = min(enemy.hp, hp_damage)
        enemy.hp -= dealt
        total_damage += dealt

    if enemy.hp <= EPS and enemy.barrier <= EPS:
        enemy.alive = False
    return total_damage


def _apply_regen(enemies: Sequence[_EnemyInstance], delta_s: float) -> None:
    if delta_s <= 0:
        return
    for enemy in enemies:
        if not enemy.alive:
            continue
        if enemy.definition.regen_per_s <= EPS:
            continue
        enemy.hp += enemy.definition.regen_per_s * delta_s
        enemy.hp = min(enemy.hp, enemy.definition.hp)


def _simulate_wave_combat(
    scenario: ScenarioDefinition,
    wave: WaveDefinition,
    runtime: RuntimeState,
    seed: int,
    sampled: bool,
) -> WaveResult:
    rng = random.Random(seed)

    active_modifiers: List[Modifier] = []
    for modifier_id in runtime.active_modifier_ids:
        modifier = scenario.global_modifiers.get(modifier_id)
        if modifier is not None:
            active_modifiers.extend(modifier.modifiers)

    towers: List[_TowerInstance] = []
    for idx, runtime_tower in enumerate(runtime.towers, start=1):
        tower_def = scenario.towers.get(runtime_tower.tower_id)
        if tower_def is None:
            continue
        stats = _resolve_tower_stats(tower_def, runtime_tower.level, active_modifiers)
        towers.append(
            _TowerInstance(
                uid=idx,
                definition=tower_def,
                stats=stats,
                focus_priorities=runtime_tower.focus_priorities,
                focus_until_death=runtime_tower.focus_until_death,
            )
        )

    enemies: List[_EnemyInstance] = []
    enemy_uid = 1
    enemy_hp_pool = 0.0
    for spawn in wave.spawns:
        enemy_def = scenario.enemies.get(spawn.enemy_id)
        if enemy_def is None:
            continue
        for index in range(spawn.count):
            at_s = spawn.at_s + (spawn.interval_s * index)
            enemies.append(
                _EnemyInstance(
                    uid=enemy_uid,
                    definition=enemy_def,
                    spawn_time=at_s,
                    hp=enemy_def.hp,
                    barrier=enemy_def.barrier,
                    dots={},
                )
            )
            enemy_uid += 1
            enemy_hp_pool += enemy_def.hp + enemy_def.barrier

    events: List[Tuple[float, int, str, Dict[str, int]]] = []
    serial = 0

    for tower in towers:
        heapq.heappush(events, (0.0, serial, "tower_attack", {"tower_uid": tower.uid}))
        serial += 1

    now = 0.0
    total_damage = 0.0
    clear_time = wave.duration_s

    while events:
        at_s, _, event_type, data = heapq.heappop(events)
        if at_s > wave.duration_s:
            break

        _apply_regen(enemies, at_s - now)
        now = at_s

        if event_type == "tower_attack":
            tower_uid = data["tower_uid"]
            tower = next((item for item in towers if item.uid == tower_uid), None)
            if tower is None:
                continue

            target = _pick_target(now, tower, enemies)
            if target is not None:
                total_damage += _apply_direct_damage(target, tower, scenario.rules, rng, sampled)

                for dot in tower.definition.dot_effects:
                    # lightweight DoT model: schedule ticks for each hit with per-effect stack cap.
                    active_count = sum(1 for dot_state in target.dots.values() if int(dot_state["effect_hash"]) == hash(dot.id))
                    if active_count >= max(1, dot.max_stacks):
                        continue

                    duration_end = now + dot.duration_s
                    tick_interval = max(EPS, dot.tick_interval_s)
                    dot_uid = serial + 100000
                    base_dot_damage = dot.damage_per_tick
                    if scenario.rules.dot_scaling_policy == "global":
                        base_dot_damage *= _crit_factor_expected(tower.stats)
                    target.dots[dot_uid] = {
                        "effect_hash": float(hash(dot.id)),
                        "damage": base_dot_damage,
                        "tick_interval": tick_interval,
                        "end": duration_end,
                    }
                    heapq.heappush(events, (now + tick_interval, serial, "dot_tick", {"enemy_uid": target.uid, "dot_uid": dot_uid}))
                    serial += 1

            next_attack = now + (1.0 / max(EPS, tower.stats.fire_rate))
            heapq.heappush(events, (next_attack, serial, "tower_attack", {"tower_uid": tower.uid}))
            serial += 1
            continue

        if event_type == "dot_tick":
            enemy_uid_ref = data["enemy_uid"]
            dot_uid = data["dot_uid"]
            enemy = next((item for item in enemies if item.uid == enemy_uid_ref), None)
            if enemy is None or not enemy.alive:
                continue
            dot_state = enemy.dots.get(dot_uid)
            if dot_state is None:
                continue
            if now > float(dot_state["end"]) + EPS:
                enemy.dots.pop(dot_uid, None)
                continue

            dealt = min(enemy.hp, float(dot_state["damage"]))
            enemy.hp -= dealt
            total_damage += dealt
            if enemy.hp <= EPS and enemy.barrier <= EPS:
                enemy.alive = False
                enemy.dots.clear()
                continue

            next_tick = now + float(dot_state["tick_interval"])
            if next_tick <= float(dot_state["end"]) + EPS:
                heapq.heappush(events, (next_tick, serial, "dot_tick", {"enemy_uid": enemy.uid, "dot_uid": dot_uid}))
                serial += 1
            else:
                enemy.dots.pop(dot_uid, None)

        if all(not enemy.alive or now < enemy.spawn_time for enemy in enemies):
            # wait for future spawn only; if no future spawn, wave is done.
            future_spawn_exists = any(now < enemy.spawn_time <= wave.duration_s for enemy in enemies)
            if not future_spawn_exists:
                clear_time = now
                break

    alive_count = sum(1 for enemy in enemies if enemy.alive and enemy.spawn_time <= wave.duration_s)
    leaks = float(alive_count)
    effective_dps = total_damage / max(EPS, wave.duration_s)

    breakdown: Dict[str, float] = {}
    if towers:
        per_tower_share = total_damage / float(len(towers))
        for tower in towers:
            breakdown[tower.definition.name] = breakdown.get(tower.definition.name, 0.0) + per_tower_share

    return WaveResult(
        wave=wave.index,
        potential_damage=total_damage,
        combat_damage=min(enemy_hp_pool, total_damage),
        effective_dps=effective_dps,
        clear_time_s=min(clear_time, wave.duration_s),
        leaks=leaks,
        enemy_hp_pool=enemy_hp_pool,
        breakdown=breakdown,
    )


def evaluate_timeline(
    scenario: ScenarioDefinition,
    build: BuildPlan,
    dataset_version: str,
    mode: str,
    seed: int,
    monte_carlo_runs: int,
) -> EvaluationResult:
    normalized_mode = mode.lower().strip()
    if normalized_mode not in {"expected", "combat", "monte_carlo"}:
        raise ValueError(f"Unsupported mode: {mode}")

    wave_results: List[WaveResult] = []

    for wave in scenario.waves:
        runtime = _runtime_for_wave(build, wave.index)
        expected = _expected_wave(scenario, wave, runtime)

        if normalized_mode == "expected":
            wave_results.append(expected)
            continue

        if normalized_mode == "combat":
            combat = _simulate_wave_combat(scenario, wave, runtime, seed + (wave.index * 997), sampled=True)
            # Keep deterministic expected potential side-by-side for UI.
            wave_results.append(
                WaveResult(
                    wave=wave.index,
                    potential_damage=expected.potential_damage,
                    combat_damage=combat.combat_damage,
                    effective_dps=combat.effective_dps,
                    clear_time_s=combat.clear_time_s,
                    leaks=combat.leaks,
                    enemy_hp_pool=combat.enemy_hp_pool,
                    breakdown=combat.breakdown,
                )
            )
            continue

        runs = max(1, monte_carlo_runs)
        samples: List[WaveResult] = []
        for run_index in range(runs):
            run_seed = seed + (wave.index * 1009) + (run_index * 37)
            samples.append(_simulate_wave_combat(scenario, wave, runtime, run_seed, sampled=True))

        avg_combat = sum(item.combat_damage for item in samples) / runs
        avg_dps = sum(item.effective_dps for item in samples) / runs
        avg_clear = sum(item.clear_time_s for item in samples) / runs
        avg_leaks = sum(item.leaks for item in samples) / runs

        breakdown: Dict[str, float] = {}
        for sample in samples:
            for key, value in sample.breakdown.items():
                breakdown[key] = breakdown.get(key, 0.0) + (value / runs)

        wave_results.append(
            WaveResult(
                wave=wave.index,
                potential_damage=expected.potential_damage,
                combat_damage=avg_combat,
                effective_dps=avg_dps,
                clear_time_s=avg_clear,
                leaks=avg_leaks,
                enemy_hp_pool=expected.enemy_hp_pool,
                breakdown=breakdown,
            )
        )

    economy_totals = _evaluate_economy_totals(scenario, build)

    return EvaluationResult(
        mode=normalized_mode,
        scenario_id=scenario.id,
        dataset_version=dataset_version,
        seed=seed,
        monte_carlo_runs=max(1, monte_carlo_runs if normalized_mode == "monte_carlo" else 1),
        wave_results=tuple(wave_results),
        economy_totals=economy_totals,
    )
