"""Nordhold damage calculator package."""

from .calculator import (
    TowerVariant,
    evaluate_lineup,
    evaluate_tower,
    search_best_lineups,
    tower_variant_for_level,
    tower_variants_map,
)
from .config import ConfigError, load_config
from .formatting import format_lineup_details, summarize_modifiers, summarize_towers
try:
    from .gui import run_app
except Exception:  # pragma: no cover - optional GUI dependency in headless envs
    def run_app() -> None:
        raise RuntimeError(
            "GUI dependencies are unavailable in this environment. "
            "Run on desktop Python with tkinter support."
        )
from .models import (
    Config,
    Modifier,
    SelectionLimits,
    StackMode,
    StatEffect,
    StatTarget,
    Tower,
    TowerUpgrade,
    ValueType,
)
from .realtime import (
    CatalogRepository,
    ReplayStore,
    evaluate_timeline,
)

__all__ = [
    "evaluate_lineup",
    "evaluate_tower",
    "search_best_lineups",
    "tower_variants_map",
    "tower_variant_for_level",
    "load_config",
    "ConfigError",
    "run_app",
    "format_lineup_details",
    "summarize_towers",
    "summarize_modifiers",
    "Config",
    "Modifier",
    "SelectionLimits",
    "StackMode",
    "StatEffect",
    "StatTarget",
    "Tower",
    "TowerUpgrade",
    "ValueType",
    "TowerVariant",
    "evaluate_timeline",
    "CatalogRepository",
    "ReplayStore",
]
