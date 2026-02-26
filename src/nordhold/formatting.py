from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Sequence

from .models import ValueType


def summarize_towers(towers: Sequence) -> str:
    counter = Counter(getattr(tower, "display_name", getattr(tower, "name", "Unknown")) for tower in towers)
    return ", ".join(f"{name} x{count}" for name, count in counter.items()) if counter else "none"


def summarize_modifiers(modifiers: Dict[str, Sequence]) -> str:
    if not modifiers:
        return "none"

    parts: List[str] = []
    for category, instances in modifiers.items():
        if not instances:
            continue
        counter = Counter(getattr(inst, "modifier", inst).name if hasattr(inst, "modifier") else getattr(inst, "name", "unknown") for inst in instances)
        joined = ", ".join(f"{name} x{count}" for name, count in counter.items())
        parts.append(f"{category}: {joined}")
    return " | ".join(parts) if parts else "none"


def format_contributions(contributions: Iterable) -> str:
    pieces: List[str] = []
    for item in contributions:
        effect = item.effect
        source = item.source
        if effect.value_type is ValueType.FLAT:
            pieces.append(f"{source}: {effect.value:+.2f}")
        elif effect.value_type is ValueType.PERCENT:
            pieces.append(f"{source}: {effect.value * 100:+.1f}%")
        elif effect.value_type is ValueType.MULTIPLIER:
            pieces.append(f"{source}: x{effect.value:.3f}")
    return "; ".join(pieces) if pieces else "none"


def format_lineup_details(result) -> str:
    lines: List[str] = []
    lines.append(f"Total DPS: {result.total_dps:.2f}")
    lines.append(f"Total Cost: {result.total_cost:.2f}")
    lines.append("")

    for entry in result.per_tower:
        lines.append(f"- {entry.variant.display_name}")
        lines.append(f"  DPS: {entry.dps:.2f}")
        lines.append(f"  Damage: {entry.damage.final_value:.2f} ({entry.damage.compact_summary()})")
        lines.append(f"    flat  : {format_contributions(entry.damage.flat)}")
        lines.append(f"    add % : {format_contributions(entry.damage.percent_add)}")
        lines.append(f"    mult %: {format_contributions(entry.damage.percent_mult)}")
        lines.append(f"    multi : {format_contributions(entry.damage.multipliers)}")
        lines.append(f"  Speed : {entry.attack_speed.final_value:.2f} ({entry.attack_speed.compact_summary()})")
        lines.append(f"    flat  : {format_contributions(entry.attack_speed.flat)}")
        lines.append(f"    add % : {format_contributions(entry.attack_speed.percent_add)}")
        lines.append(f"    mult %: {format_contributions(entry.attack_speed.percent_mult)}")
        lines.append(f"    multi : {format_contributions(entry.attack_speed.multipliers)}")
        if entry.applied_modifiers:
            modifier_names = ", ".join(inst.label for inst in entry.applied_modifiers)
        else:
            modifier_names = "none"
        lines.append(f"  Modifiers: {modifier_names}")
        lines.append("")

    return "\n".join(lines).rstrip()


def lineup_to_dict(result) -> Dict:
    return {
        "total_dps": result.total_dps,
        "total_cost": result.total_cost,
        "towers": [
            {
                "name": entry.variant.display_name,
                "damage": entry.damage.final_value,
                "attack_speed": entry.attack_speed.final_value,
                "dps": entry.dps,
                "damage_breakdown": {
                    "base": entry.damage.base,
                    "final": entry.damage.final_value,
                    "flat": [
                        {"source": item.source, "value": item.effect.value}
                        for item in entry.damage.flat
                    ],
                    "percent_add": [
                        {"source": item.source, "value": item.effect.value}
                        for item in entry.damage.percent_add
                    ],
                    "percent_mult": [
                        {"source": item.source, "value": item.effect.value}
                        for item in entry.damage.percent_mult
                    ],
                    "multipliers": [
                        {"source": item.source, "value": item.effect.value}
                        for item in entry.damage.multipliers
                    ],
                },
            }
            for entry in result.per_tower
        ],
        "modifiers": {
            category: [
                {"name": inst.modifier.name, "stack": inst.stack_index}
                for inst in instances
            ]
            for category, instances in result.modifier_selection.items()
        },
    }
