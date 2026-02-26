from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .calculator import evaluate_lineup, search_best_lineups, tower_variants_map
from .config import Config, ConfigError, load_config
from .formatting import lineup_to_dict
from .realtime import (
    CatalogError,
    CatalogRepository,
    BuildPlan,
    MemoryProfileError,
    ModelError,
    ReplayError,
    ReplayStore,
    compare_builds,
    evaluate_timeline,
    forecast_from_history,
    sensitivity_analysis,
)
from .realtime.live_bridge import LiveBridge


app = FastAPI(
    title="Nordhold Damage API",
    description="API for legacy lineup evaluation and realtime wave simulation.",
    version="1.0.0",
)


def _resolve_project_root() -> Path:
    env_root = os.environ.get("NORDHOLD_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates = (
            exe_dir,
            exe_dir / "_internal",
            exe_dir.parent,
        )
        for candidate in candidates:
            if (candidate / "data" / "versions" / "index.json").exists():
                return candidate
        return exe_dir

    return Path(__file__).resolve().parents[2]


def _resolve_web_dist(project_root: Path) -> Path:
    env_web_dist = os.environ.get("NORDHOLD_WEB_DIST", "").strip()
    if env_web_dist:
        return Path(env_web_dist).expanduser().resolve()
    return project_root / "web" / "dist"


_PROJECT_ROOT = _resolve_project_root()
_WEB_DIST = _resolve_web_dist(_PROJECT_ROOT)
if (_WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_WEB_DIST / "assets")), name="web-assets")


# ---------------------------------------------------------------------------
# Legacy API (kept for compatibility)
# ---------------------------------------------------------------------------
class TowerRequest(BaseModel):
    name: str = Field(..., description="Tower name from config.")
    level: int = Field(0, ge=0, description="Upgrade depth.")
    count: int = Field(1, ge=1, description="Tower count.")


class SimulationRequest(BaseModel):
    config: str = Field(..., description="Path to JSON/YAML config.")
    towers: List[TowerRequest] = Field(..., description="Tower list.")
    modifiers: Dict[str, List[str]] = Field(default_factory=dict)


def _load_config(path_str: str) -> Config:
    path = Path(path_str).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Config not found: {path}")
    try:
        return load_config(path)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _build_lineup(config: Config, towers: List[TowerRequest]):
    if not towers:
        raise HTTPException(status_code=400, detail="Tower list cannot be empty.")

    variants_map = tower_variants_map(config)
    lineup = []

    for item in towers:
        variants = variants_map.get(item.name)
        if not variants:
            raise HTTPException(status_code=400, detail=f"Tower '{item.name}' not found.")
        index = min(item.level, len(variants) - 1)
        variant = variants[index]
        if item.count > variant.tower.max_count:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Tower '{item.name}' max count is {variant.tower.max_count}, requested {item.count}."
                ),
            )
        lineup.extend([variant] * item.count)

    if not lineup:
        raise HTTPException(status_code=400, detail="No towers left after parsing payload.")
    return lineup


def _build_modifier_selection(config: Config, modifiers_payload: Dict[str, List[str]]):
    selection = {}
    for category, names in modifiers_payload.items():
        available = {modifier.name: modifier for modifier in config.modifiers.get(category, [])}
        if not available:
            raise HTTPException(
                status_code=400,
                detail=f"Modifier category '{category}' is missing in config.",
            )

        chosen = []
        counters = defaultdict(int)
        for name in names:
            modifier = available.get(name)
            if modifier is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Modifier '{name}' not found in category '{category}'.",
                )
            counters[name] += 1
            if counters[name] > modifier.max_stacks:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Modifier '{name}' in category '{category}' supports max "
                        f"{modifier.max_stacks} stacks."
                    ),
                )
            chosen.append(modifier)

        limit = config.selection_limits.limit_for(category, default=len(available))
        if limit > 0 and len(chosen) > limit:
            raise HTTPException(
                status_code=400,
                detail=f"Category '{category}' limit is {limit}, got {len(chosen)}.",
            )
        if chosen:
            selection[category] = tuple(chosen)

    return selection


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def web_root():
    index_path = _WEB_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse(
        status_code=503,
        content={
            "status": "missing_web_bundle",
            "detail": "Frontend build was not found in web/dist. Run npm run build in web/.",
        },
    )


@app.post("/simulate")
def simulate(payload: SimulationRequest):
    config = _load_config(payload.config)
    lineup = _build_lineup(config, payload.towers)
    selection = _build_modifier_selection(config, payload.modifiers)
    result = evaluate_lineup(lineup, selection, config)
    return lineup_to_dict(result)


@app.get("/lineups")
def get_lineups(config: str, top: int = 10, max_cost: Optional[float] = None):
    if top <= 0:
        raise HTTPException(status_code=400, detail="Parameter 'top' must be > 0.")
    cfg = _load_config(config)
    results = search_best_lineups(cfg, top_n=top, max_cost=max_cost)
    return [lineup_to_dict(result) for result in results]


# ---------------------------------------------------------------------------
# Realtime API v1
# ---------------------------------------------------------------------------
catalog_repo = CatalogRepository(project_root=_PROJECT_ROOT)
replay_store = ReplayStore(project_root=catalog_repo.project_root)
live_bridge = LiveBridge(catalog=catalog_repo, replay_store=replay_store, project_root=catalog_repo.project_root)


class LiveConnectRequest(BaseModel):
    process_name: str = "NordHold.exe"
    poll_ms: int = Field(default=1000, ge=200, le=60000)
    require_admin: bool = True
    dataset_version: Optional[str] = None
    replay_session_id: str = ""
    signature_profile_id: str = ""
    calibration_candidates_path: str = ""
    calibration_candidate_id: str = ""


class LiveAutoconnectRequest(BaseModel):
    process_name: str = "NordHold.exe"
    poll_ms: int = Field(default=1000, ge=200, le=60000)
    require_admin: bool = True
    dataset_version: str = ""
    dataset_autorefresh: bool = True
    replay_session_id: str = ""
    signature_profile_id: str = ""
    calibration_candidates_path: str = ""
    calibration_candidate_id: str = ""


class ReplayImportRequest(BaseModel):
    format: Literal["json", "csv"]
    content: str


class TowerPlanInput(BaseModel):
    tower_id: str
    count: int = Field(default=1, ge=0)
    level: int = Field(default=0, ge=0)
    focus_priorities: List[str] = Field(default_factory=lambda: ["progress", "lowest_hp"])
    focus_until_death: bool = False


class BuildActionInput(BaseModel):
    wave: int = Field(..., ge=1)
    at_s: float = Field(default=0.0, ge=0.0)
    type: str
    target_id: str = ""
    value: float = 0.0
    payload: Dict[str, Any] = Field(default_factory=dict)


class BuildPlanInput(BaseModel):
    scenario_id: str
    towers: List[TowerPlanInput]
    active_global_modifiers: List[str] = Field(default_factory=list)
    actions: List[BuildActionInput] = Field(default_factory=list)


class TimelineEvaluateRequest(BaseModel):
    dataset_version: Optional[str] = None
    mode: Literal["expected", "combat", "monte_carlo"] = "expected"
    seed: int = 42
    monte_carlo_runs: int = Field(default=200, ge=1, le=10000)
    build_plan: BuildPlanInput


class CompareRequest(BaseModel):
    dataset_version: Optional[str] = None
    mode: Literal["expected", "combat", "monte_carlo"] = "expected"
    seed: int = 42
    monte_carlo_runs: int = Field(default=200, ge=1, le=10000)
    builds: List[BuildPlanInput]


class SensitivityRequest(BaseModel):
    dataset_version: Optional[str] = None
    mode: Literal["expected", "combat", "monte_carlo"] = "expected"
    seed: int = 42
    monte_carlo_runs: int = Field(default=200, ge=1, le=10000)
    parameter: Literal["tower_damage_scale", "tower_fire_rate_scale", "tower_accuracy_scale"] = "tower_damage_scale"
    values: List[float] = Field(default_factory=lambda: [0.8, 0.9, 1.0, 1.1, 1.2])
    build_plan: BuildPlanInput


class ForecastRequest(BaseModel):
    dataset_version: Optional[str] = None
    mode: Literal["expected", "combat", "monte_carlo"] = "expected"
    seed: int = 42
    monte_carlo_runs: int = Field(default=200, ge=1, le=10000)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    latest_build: Optional[BuildPlanInput] = None


def _to_build_plan(payload: BuildPlanInput) -> BuildPlan:
    try:
        return BuildPlan.from_dict(payload.model_dump())
    except ModelError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid build plan: {exc}") from exc


def _load_scenario_for_build(build: BuildPlan, dataset_version: Optional[str]):
    try:
        return catalog_repo.load_scenario(scenario_id=build.scenario_id, dataset_version=dataset_version)
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _dataset_meta_payload(dataset_version: Optional[str] = None) -> Dict[str, str]:
    try:
        meta = catalog_repo.get_dataset_meta(dataset_version) if dataset_version else catalog_repo.get_active_dataset_meta()
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "dataset_version": meta.dataset_version,
        "game_version": meta.game_version,
        "build_id": meta.build_id,
    }


def _load_catalog_payload(dataset_version: Optional[str] = None) -> tuple[Dict[str, str], Dict[str, Any]]:
    dataset = _dataset_meta_payload(dataset_version)
    try:
        meta = catalog_repo.get_dataset_meta(dataset["dataset_version"])
        payload = json.loads(meta.catalog_path.read_text(encoding="utf-8"))
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid catalog JSON: {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read catalog file: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Catalog file must contain a JSON object.")
    return dataset, payload


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _build_run_state_payload(status: Dict[str, Any], snapshot_payload: Dict[str, Any]) -> Dict[str, Any]:
    build = snapshot_payload.get("build")
    raw_fields = build.get("raw_memory_fields") if isinstance(build, dict) else {}
    raw_fields = raw_fields if isinstance(raw_fields, dict) else {}

    economy = {
        "gold": _safe_float(snapshot_payload.get("gold", 0.0), 0.0),
        "essence": _safe_float(snapshot_payload.get("essence", 0.0), 0.0),
        "wood": _safe_float(raw_fields.get("wood", 0.0), 0.0),
        "stone": _safe_float(raw_fields.get("stone", 0.0), 0.0),
        "wheat": _safe_float(raw_fields.get("wheat", 0.0), 0.0),
        "workers_total": _safe_float(raw_fields.get("workers_total", 0.0), 0.0),
        "workers_free": _safe_float(raw_fields.get("workers_free", 0.0), 0.0),
        "tower_inflation_index": _safe_float(raw_fields.get("tower_inflation_index", 1.0), 1.0),
    }

    return {
        "timestamp": _safe_float(snapshot_payload.get("timestamp", time.time()), time.time()),
        "wave": int(_safe_float(snapshot_payload.get("wave", 1), 1.0)),
        "source_mode": str(snapshot_payload.get("source_mode", "")),
        "status": str(status.get("status", "")),
        "mode": str(status.get("mode", "")),
        "reason": str(status.get("reason", "")),
        "dataset_version": str(status.get("dataset_version", "")),
        "game_build": str(status.get("game_build", "")),
        "source_provenance": {
            "mode": str(snapshot_payload.get("source_mode", "")),
            "memory_connected": bool(status.get("memory_connected", False)),
            "replay_session_id": str(status.get("replay_session_id", "")),
            "signature_profile": str(status.get("signature_profile", "")),
            "calibration_candidate": str(status.get("calibration_candidate", "")),
            "reason": str(status.get("reason", "")),
        },
        "economy": economy,
    }


def _format_sse_event(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True, separators=(',', ':'))}\n\n"


@app.post("/api/v1/live/connect")
def live_connect(payload: LiveConnectRequest):
    try:
        return live_bridge.connect(
            process_name=payload.process_name,
            poll_ms=payload.poll_ms,
            require_admin=payload.require_admin,
            dataset_version=payload.dataset_version,
            replay_session_id=payload.replay_session_id,
            signature_profile_id=payload.signature_profile_id,
            calibration_candidates_path=payload.calibration_candidates_path,
            calibration_candidate_id=payload.calibration_candidate_id,
        )
    except (CatalogError, ReplayError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/live/autoconnect")
def live_autoconnect(payload: Optional[LiveAutoconnectRequest] = None):
    request = payload or LiveAutoconnectRequest()
    try:
        return live_bridge.autoconnect(
            process_name=request.process_name,
            poll_ms=request.poll_ms,
            require_admin=request.require_admin,
            dataset_version=request.dataset_version,
            dataset_autorefresh=request.dataset_autorefresh,
            replay_session_id=request.replay_session_id,
            signature_profile_id=request.signature_profile_id,
            calibration_candidates_path=request.calibration_candidates_path,
            calibration_candidate_id=request.calibration_candidate_id,
        )
    except (CatalogError, ReplayError, MemoryProfileError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/live/status")
def live_status():
    return live_bridge.status()


@app.get("/api/v1/live/calibration/candidates")
def live_calibration_candidates(path: str = ""):
    try:
        return live_bridge.inspect_calibration_candidates(path)
    except MemoryProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/live/snapshot")
def live_snapshot():
    try:
        snap = live_bridge.snapshot()
    except (ReplayError,) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(snap)


@app.get("/api/v1/dataset/version")
def dataset_version(version: str = ""):
    version_value = version.strip()
    return _dataset_meta_payload(version_value or None)


@app.get("/api/v1/dataset/catalog")
def dataset_catalog(version: str = ""):
    version_value = version.strip()
    dataset, payload = _load_catalog_payload(version_value or None)
    return {"dataset": dataset, "catalog": payload}


@app.get("/api/v1/run/state")
def run_state():
    try:
        status = live_bridge.status()
        snapshot_payload = asdict(live_bridge.snapshot())
    except ReplayError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_run_state_payload(status, snapshot_payload)


@app.get("/api/v1/events")
def events(limit: int = 1, heartbeat_ms: int = 1000):
    max_events = max(1, min(int(limit), 1000))
    delay_s = max(0.05, min(float(heartbeat_ms) / 1000.0, 60.0))

    def _event_stream():
        sent = 0
        while sent < max_events:
            status = live_bridge.status()
            try:
                snapshot_payload = asdict(live_bridge.snapshot())
            except ReplayError as exc:
                yield _format_sse_event(
                    "error",
                    {"timestamp": time.time(), "detail": str(exc)},
                )
                break
            yield _format_sse_event("status", _build_run_state_payload(status, snapshot_payload))
            sent += 1
            if sent < max_events:
                yield _format_sse_event("heartbeat", {"timestamp": time.time(), "sequence": sent})
                time.sleep(delay_s)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/replay/import")
def replay_import(payload: ReplayImportRequest):
    try:
        session = replay_store.import_payload(payload.format, payload.content)
    except ReplayError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "session_id": session.session_id,
        "source": session.source,
        "snapshots": len(session.snapshots),
        "latest": asdict(session.snapshots[-1]),
    }


@app.post("/api/v1/timeline/evaluate")
def timeline_evaluate(payload: TimelineEvaluateRequest):
    build = _to_build_plan(payload.build_plan)
    meta, scenario = _load_scenario_for_build(build, payload.dataset_version)

    try:
        result = evaluate_timeline(
            scenario=scenario,
            build=build,
            dataset_version=meta.dataset_version,
            mode=payload.mode,
            seed=payload.seed,
            monte_carlo_runs=payload.monte_carlo_runs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "dataset": {
            "dataset_version": meta.dataset_version,
            "game_version": meta.game_version,
            "build_id": meta.build_id,
        },
        "result": result.to_dict(),
    }


@app.post("/api/v1/analytics/compare")
def analytics_compare(payload: CompareRequest):
    if not payload.builds:
        raise HTTPException(status_code=400, detail="'builds' cannot be empty.")

    build_plans = [_to_build_plan(build) for build in payload.builds]
    meta, scenario = _load_scenario_for_build(build_plans[0], payload.dataset_version)

    for build in build_plans[1:]:
        if build.scenario_id != build_plans[0].scenario_id:
            raise HTTPException(status_code=400, detail="All builds must use the same scenario_id.")

    result = compare_builds(
        scenario=scenario,
        dataset_version=meta.dataset_version,
        builds=build_plans,
        mode=payload.mode,
        seed=payload.seed,
        monte_carlo_runs=payload.monte_carlo_runs,
    )
    return {
        "dataset": {
            "dataset_version": meta.dataset_version,
            "game_version": meta.game_version,
            "build_id": meta.build_id,
        },
        "result": result,
    }


@app.post("/api/v1/analytics/sensitivity")
def analytics_sensitivity(payload: SensitivityRequest):
    build = _to_build_plan(payload.build_plan)
    meta, scenario = _load_scenario_for_build(build, payload.dataset_version)

    result = sensitivity_analysis(
        scenario=scenario,
        dataset_version=meta.dataset_version,
        build=build,
        parameter=payload.parameter,
        values=payload.values,
        mode=payload.mode,
        seed=payload.seed,
        monte_carlo_runs=payload.monte_carlo_runs,
    )

    return {
        "dataset": {
            "dataset_version": meta.dataset_version,
            "game_version": meta.game_version,
            "build_id": meta.build_id,
        },
        "result": result,
    }


@app.post("/api/v1/analytics/forecast")
def analytics_forecast(payload: ForecastRequest):
    latest_result = None
    if payload.latest_build is not None:
        build = _to_build_plan(payload.latest_build)
        meta, scenario = _load_scenario_for_build(build, payload.dataset_version)
        latest_result = evaluate_timeline(
            scenario=scenario,
            build=build,
            dataset_version=meta.dataset_version,
            mode=payload.mode,
            seed=payload.seed,
            monte_carlo_runs=payload.monte_carlo_runs,
        )

    result = forecast_from_history(payload.history, latest=latest_result)
    return {"result": result, "latest_included": latest_result is not None}
