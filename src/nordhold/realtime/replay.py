from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .models import LiveSnapshot, ReplaySession, ReplaySnapshot


class ReplayError(RuntimeError):
    """Raised when replay payload is malformed."""


class ReplayStore:
    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parents[3]
        self.project_root = project_root
        self.replays_dir = self.project_root / "runtime" / "replays"
        self.replays_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        return self.replays_dir / f"{session_id}.json"

    def import_payload(self, payload_format: str, content: str) -> ReplaySession:
        normalized = payload_format.strip().lower()
        if normalized not in {"json", "csv"}:
            raise ReplayError("Unsupported replay format. Use json or csv.")

        snapshots = self._parse_json(content) if normalized == "json" else self._parse_csv(content)
        session_id = f"replay-{int(time.time())}-{uuid4().hex[:8]}"
        session = ReplaySession(session_id=session_id, source=normalized, snapshots=tuple(snapshots))

        self._session_path(session_id).write_text(
            json.dumps(
                {
                    "session_id": session.session_id,
                    "source": session.source,
                    "snapshots": [asdict(item) for item in session.snapshots],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return session

    def load_session(self, session_id: str) -> ReplaySession:
        path = self._session_path(session_id)
        if not path.exists():
            raise ReplayError(f"Replay session not found: {session_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshots = tuple(
            ReplaySnapshot(
                timestamp=float(item.get("timestamp", 0.0)),
                wave=int(item.get("wave", 0)),
                gold=float(item.get("gold", 0.0)),
                essence=float(item.get("essence", 0.0)),
                build=dict(item.get("build", {})),
            )
            for item in payload.get("snapshots", [])
        )
        return ReplaySession(session_id=session_id, source=str(payload.get("source", "json")), snapshots=snapshots)

    def latest_snapshot(self, session_id: str) -> LiveSnapshot:
        session = self.load_session(session_id)
        if not session.snapshots:
            raise ReplayError(f"Replay session has no snapshots: {session_id}")
        snap = session.snapshots[-1]
        return LiveSnapshot(
            timestamp=snap.timestamp,
            wave=snap.wave,
            gold=snap.gold,
            essence=snap.essence,
            build=snap.build,
            source_mode="replay",
        )

    def _parse_json(self, content: str) -> List[ReplaySnapshot]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ReplayError(f"Invalid JSON replay payload: {exc}") from exc

        if isinstance(payload, list):
            raw = payload
        elif isinstance(payload, dict):
            raw = payload.get("snapshots", [])
        else:
            raise ReplayError("JSON replay payload must be list or object with snapshots.")

        snapshots: List[ReplaySnapshot] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            snapshots.append(
                ReplaySnapshot(
                    timestamp=float(item.get("timestamp", time.time())),
                    wave=int(item.get("wave", 0)),
                    gold=float(item.get("gold", 0.0)),
                    essence=float(item.get("essence", 0.0)),
                    build=dict(item.get("build", {})),
                )
            )
        if not snapshots:
            raise ReplayError("Replay payload contains no snapshots.")
        snapshots.sort(key=lambda item: item.timestamp)
        return snapshots

    def _parse_csv(self, content: str) -> List[ReplaySnapshot]:
        rows = list(csv.DictReader(content.splitlines()))
        snapshots: List[ReplaySnapshot] = []
        for row in rows:
            raw_build = row.get("build", "")
            build: Dict[str, Any]
            if raw_build.strip():
                try:
                    build = json.loads(raw_build)
                except json.JSONDecodeError:
                    build = {"raw": raw_build}
            else:
                build = {}

            snapshots.append(
                ReplaySnapshot(
                    timestamp=float(row.get("timestamp", time.time())),
                    wave=int(row.get("wave", 0)),
                    gold=float(row.get("gold", 0.0)),
                    essence=float(row.get("essence", 0.0)),
                    build=build,
                )
            )

        if not snapshots:
            raise ReplayError("CSV replay payload contains no rows.")
        snapshots.sort(key=lambda item: item.timestamp)
        return snapshots
