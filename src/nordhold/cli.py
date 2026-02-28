from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .calculator import LineupEvaluation, search_best_lineups
from .config import ConfigError, load_config
from .formatting import (
    format_lineup_details,
    lineup_to_dict,
    summarize_modifiers,
    summarize_towers,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nordhold-calculator",
        description=(
            "Подбор сильнейших комбинаций башен, баннеров, артефактов, способностей героя и оракула."
        ),
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Путь к JSON/YAML конфигурации с параметрами Nordhold.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Сколько лучших комбинаций показать (по суммарному DPS).",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=None,
        help="Отсеивать варианты дороже указанного бюджета (учитываются башни, апгрейды и модификаторы).",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Формат вывода результатов.",
    )
    parser.add_argument(
        "--per-tower",
        action="store_true",
        help="Показывать детали по каждой башне (только для табличного вывода).",
    )
    return parser


def _print_table(results: Sequence[LineupEvaluation], show_per_tower: bool) -> None:
    if not results:
        print("Комбинации не найдены.")
        return

    header = f"{'Rank':<6}{'Total DPS':<14}{'Total Cost':<14}Towers / Modifiers"
    print(header)
    print("-" * len(header))

    for idx, result in enumerate(results, start=1):
        towers_summary = summarize_towers(result.towers)
        modifiers_summary = summarize_modifiers(result.modifier_selection)
        print(f"{idx:<6}{result.total_dps:<14.2f}{result.total_cost:<14.2f}{towers_summary}")
        if modifiers_summary != "none":
            print(f"{'':<6}{'':<14}{'':<14}{modifiers_summary}")
        if show_per_tower:
            details = format_lineup_details(result)
            indented = "\n".join(f"    {line}" if line else "" for line in details.splitlines())
            print(indented)
        print()


def _print_json(results: Sequence[LineupEvaluation]) -> None:
    payload = [lineup_to_dict(result) for result in results]
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        parser.error(str(exc))
    except Exception as exc:  # pragma: no cover - unexpected errors
        parser.error(f"Не удалось загрузить конфигурацию: {exc}")

    try:
        results = search_best_lineups(config, top_n=args.top, max_cost=args.max_cost)
    except Exception as exc:
        parser.error(f"Не удалось выполнить расчёт: {exc}")
        return 2

    if args.format == "json":
        _print_json(results)
    else:
        _print_table(results, show_per_tower=args.per_tower)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
