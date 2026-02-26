from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List, Sequence

from .engine import evaluate_timeline
from .models import BuildPlan, EvaluationResult, ScenarioDefinition, TowerDefinition, TowerStats


def _scale_tower_stat(base: TowerStats, parameter: str, factor: float) -> TowerStats:
    if parameter == "tower_damage_scale":
        return replace(base, damage=base.damage * factor)
    if parameter == "tower_fire_rate_scale":
        return replace(base, fire_rate=base.fire_rate * factor)
    if parameter == "tower_accuracy_scale":
        return replace(base, accuracy=max(0.0, min(1.0, base.accuracy * factor)))
    return base


def _scaled_scenario(scenario: ScenarioDefinition, parameter: str, factor: float) -> ScenarioDefinition:
    towers: Dict[str, TowerDefinition] = {}
    for tower_id, tower in scenario.towers.items():
        towers[tower_id] = replace(tower, base_stats=_scale_tower_stat(tower.base_stats, parameter, factor))
    return replace(scenario, towers=towers)


def _extract_scalar_totals(payload: Dict[str, Any]) -> Dict[str, float]:
    totals = payload.get("totals", payload)
    totals = totals if isinstance(totals, dict) else {}
    economy = totals.get("economy", {})
    economy = economy if isinstance(economy, dict) else {}
    return {
        "combat_damage": float(totals.get("combat_damage", 0.0)),
        "potential_damage": float(totals.get("potential_damage", 0.0)),
        "leaks": float(totals.get("leaks", 0.0)),
        "net_gold": float(economy.get("net_gold", 0.0)),
        "net_essence": float(economy.get("net_essence", 0.0)),
    }


def compare_builds(
    scenario: ScenarioDefinition,
    dataset_version: str,
    builds: Sequence[BuildPlan],
    mode: str,
    seed: int,
    monte_carlo_runs: int,
) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    for index, build in enumerate(builds, start=1):
        result = evaluate_timeline(
            scenario=scenario,
            build=build,
            dataset_version=dataset_version,
            mode=mode,
            seed=seed + index,
            monte_carlo_runs=monte_carlo_runs,
        )
        entries.append(
            {
                "index": index,
                "scenario_id": build.scenario_id,
                "totals": result.totals,
                "mode": result.mode,
            }
        )

    entries.sort(key=lambda item: item["totals"]["combat_damage"], reverse=True)
    return {"ranked": entries}


def sensitivity_analysis(
    scenario: ScenarioDefinition,
    dataset_version: str,
    build: BuildPlan,
    parameter: str,
    values: Iterable[float],
    mode: str,
    seed: int,
    monte_carlo_runs: int,
) -> Dict[str, Any]:
    baseline = evaluate_timeline(
        scenario=scenario,
        build=build,
        dataset_version=dataset_version,
        mode=mode,
        seed=seed,
        monte_carlo_runs=monte_carlo_runs,
    )

    baseline_combat = baseline.totals["combat_damage"]
    points: List[Dict[str, Any]] = []
    for value in values:
        factor = float(value)
        adjusted = _scaled_scenario(scenario, parameter, factor)
        result = evaluate_timeline(
            scenario=adjusted,
            build=build,
            dataset_version=dataset_version,
            mode=mode,
            seed=seed,
            monte_carlo_runs=monte_carlo_runs,
        )
        combat = result.totals["combat_damage"]
        delta_pct = 0.0
        if abs(baseline_combat) > 1e-9:
            delta_pct = ((combat - baseline_combat) / baseline_combat) * 100.0
        points.append(
            {
                "factor": factor,
                "combat_damage": combat,
                "delta_pct_vs_baseline": delta_pct,
            }
        )

    return {
        "parameter": parameter,
        "baseline": baseline.totals,
        "points": points,
    }


def forecast_from_history(history: Sequence[Dict[str, Any]], latest: EvaluationResult | None = None) -> Dict[str, Any]:
    if not history and latest is None:
        return {
            "samples": 0,
            "expected_combat_damage": 0.0,
            "expected_potential_damage": 0.0,
            "expected_leaks": 0.0,
            "success_probability": 0.0,
        }

    combat_values: List[float] = []
    potential_values: List[float] = []
    leak_values: List[float] = []

    for item in history:
        totals = _extract_scalar_totals(item)
        combat_values.append(totals["combat_damage"])
        potential_values.append(totals["potential_damage"])
        leak_values.append(totals["leaks"])

    if latest is not None:
        totals = _extract_scalar_totals({"totals": latest.totals})
        combat_values.append(totals["combat_damage"])
        potential_values.append(totals["potential_damage"])
        leak_values.append(totals["leaks"])

    samples = len(combat_values)
    expected_combat = sum(combat_values) / max(1, samples)
    expected_potential = sum(potential_values) / max(1, samples)
    expected_leaks = sum(leak_values) / max(1, samples)

    if expected_potential <= 1e-9:
        success_probability = 0.0
    else:
        leak_ratio = min(1.0, max(0.0, expected_leaks / max(1.0, expected_potential)))
        success_probability = max(0.0, min(1.0, 1.0 - leak_ratio))

    return {
        "samples": samples,
        "expected_combat_damage": expected_combat,
        "expected_potential_damage": expected_potential,
        "expected_leaks": expected_leaks,
        "success_probability": success_probability,
    }
