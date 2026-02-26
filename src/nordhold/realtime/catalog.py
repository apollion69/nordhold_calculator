from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .models import ModelError, ScenarioDefinition


class CatalogError(RuntimeError):
    """Raised when versioned catalog cannot be loaded."""


@dataclass(slots=True, frozen=True)
class DatasetMeta:
    dataset_version: str
    game_version: str
    build_id: str
    catalog_path: Path
    memory_signatures_path: Path


class CatalogRepository:
    """Loads versioned Nordhold datasets from local project storage."""

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parents[3]
        self.project_root = project_root
        self.versions_index_path = self.project_root / "data" / "versions" / "index.json"

    def _read_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise CatalogError(f"Required file not found: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CatalogError(f"Invalid JSON in {path}: {exc}") from exc

    def get_active_dataset_meta(self) -> DatasetMeta:
        payload = self._read_json(self.versions_index_path)
        active = payload.get("active_version")
        if not active:
            raise CatalogError("versions/index.json does not define 'active_version'.")
        return self.get_dataset_meta(str(active))

    def get_dataset_meta(self, dataset_version: str) -> DatasetMeta:
        payload = self._read_json(self.versions_index_path)
        versions = payload.get("versions", [])
        for item in versions:
            if str(item.get("id")) != dataset_version:
                continue
            catalog_rel = str(item.get("catalog_path", "")).strip()
            signatures_rel = str(item.get("memory_signatures_path", "")).strip()
            if not catalog_rel or not signatures_rel:
                raise CatalogError(f"Version {dataset_version} is missing catalog/signatures paths.")
            return DatasetMeta(
                dataset_version=dataset_version,
                game_version=str(item.get("game_version", dataset_version)),
                build_id=str(item.get("build_id", "unknown")),
                catalog_path=self.project_root / catalog_rel,
                memory_signatures_path=self.project_root / signatures_rel,
            )
        raise CatalogError(f"Dataset version not found: {dataset_version}")

    def load_scenario(self, scenario_id: str, dataset_version: Optional[str] = None) -> tuple[DatasetMeta, ScenarioDefinition]:
        meta = self.get_dataset_meta(dataset_version) if dataset_version else self.get_active_dataset_meta()
        payload = self._read_json(meta.catalog_path)
        for item in payload.get("scenarios", []):
            if str(item.get("id")) == scenario_id:
                try:
                    scenario = ScenarioDefinition.from_dict(item)
                except ModelError as exc:
                    raise CatalogError(f"Scenario '{scenario_id}' is invalid: {exc}") from exc
                return meta, scenario
        raise CatalogError(f"Scenario not found: {scenario_id}")

    def load_memory_signatures(self, dataset_version: Optional[str] = None) -> Dict[str, Any]:
        meta = self.get_dataset_meta(dataset_version) if dataset_version else self.get_active_dataset_meta()
        return self._read_json(meta.memory_signatures_path)
