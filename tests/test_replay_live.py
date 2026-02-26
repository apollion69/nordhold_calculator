from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nordhold.realtime.catalog import CatalogRepository
from nordhold.realtime.live_bridge import LiveBridge
from nordhold.realtime.memory_reader import MemoryReaderError
from nordhold.realtime.replay import ReplayStore


def _valid_memory_signatures() -> dict:
    return {
        "profiles": [
            {
                "id": "live_memory_v1_test",
                "process_name": "NordHold.exe",
                "module_name": "NordHold.exe",
                "poll_ms": 250,
                "required_admin": False,
                "fields": {
                    "current_wave": {
                        "source": "address",
                        "address": "0x1000",
                        "type": "int32",
                    },
                    "gold": {
                        "source": "address",
                        "address": "0x1004",
                        "type": "int32",
                    },
                    "essence": {
                        "source": "address",
                        "address": "0x1008",
                        "type": "int32",
                    },
                },
            }
        ]
    }


def _unresolved_memory_signatures() -> dict:
    return {
        "profiles": [
            {
                "id": "base_profile",
                "process_name": "NordHold.exe",
                "module_name": "NordHold.exe",
                "poll_ms": 250,
                "required_admin": False,
                "fields": {
                    "current_wave": {
                        "source": "address",
                        "address": "0x0",
                        "type": "int32",
                    },
                    "gold": {
                        "source": "address",
                        "address": "0x0",
                        "type": "int32",
                    },
                    "essence": {
                        "source": "address",
                        "address": "0x0",
                        "type": "int32",
                    },
                },
            }
        ]
    }


def _quality_count(quality: dict, *, primary: str, legacy: str) -> int:
    if primary in quality:
        primary_value = int(quality[primary])
        if legacy in quality:
            assert primary_value == int(quality[legacy])
        return primary_value
    if legacy in quality:
        return int(quality[legacy])
    raise AssertionError(f"candidate_quality missing count keys: {primary} / {legacy}")


class ReplayLiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = CatalogRepository()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.store = ReplayStore(project_root=Path(self._tmpdir.name))

    def test_replay_json_import_and_latest(self) -> None:
        payload = {
            "snapshots": [
                {"timestamp": 1.0, "wave": 1, "gold": 50, "essence": 5, "build": {}},
                {"timestamp": 2.0, "wave": 2, "gold": 75, "essence": 8, "build": {"towers": []}}
            ]
        }
        session = self.store.import_payload("json", json.dumps(payload))
        latest = self.store.latest_snapshot(session.session_id)
        self.assertEqual(latest.wave, 2)
        self.assertEqual(latest.source_mode, "replay")

    def test_live_bridge_uses_replay_fallback(self) -> None:
        payload = {
            "snapshots": [{"timestamp": 3.0, "wave": 3, "gold": 99, "essence": 9, "build": {}}]
        }
        session = self.store.import_payload("json", json.dumps(payload))

        bridge = LiveBridge(catalog=self.repo, replay_store=self.store, project_root=self.repo.project_root)
        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_valid_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=False),
        ):
            status = bridge.connect(
                process_name="DefinitelyNoSuchProcess.exe",
                poll_ms=1000,
                require_admin=False,
                dataset_version="1.0.0",
                replay_session_id=session.session_id,
            )

        self.assertEqual(status["mode"], "replay")
        self.assertEqual(
            status["field_coverage"],
            {
                "required_total": 3,
                "required_resolved": 3,
                "optional_total": 0,
                "optional_resolved": 0,
            },
        )
        self.assertEqual(status["calibration_quality"], "full")
        self.assertEqual(status["active_required_fields"], ["current_wave", "gold", "essence"])
        snap = bridge.snapshot()
        self.assertEqual(snap.wave, 3)

    def test_live_bridge_reports_admin_required_without_overwriting_reason(self) -> None:
        bridge = LiveBridge(catalog=self.repo, replay_store=self.store, project_root=self.repo.project_root)

        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_valid_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=True),
            patch.object(bridge, "_is_admin_context", return_value=False),
        ):
            status = bridge.connect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=True,
                dataset_version="1.0.0",
            )

        self.assertEqual(status["mode"], "degraded")
        self.assertEqual(status["reason"], "process_found_but_admin_required")
        self.assertFalse(status["memory_connected"])
        self.assertEqual(status["replay_session_id"], "")

    def test_live_bridge_memory_snapshot_failure_falls_back_to_synthetic(self) -> None:
        class FlakyMemoryReader:
            def __init__(self):
                self.connected = False
                self.open_calls = 0
                self.read_calls = 0
                self.close_calls = 0

            def close(self) -> None:
                self.close_calls += 1
                self.connected = False

            def open(self, process_name: str, profile) -> None:
                self.open_calls += 1
                self.connected = True

            def read_fields(self, profile):
                self.read_calls += 1
                if self.read_calls == 1:
                    return {"current_wave": 7, "gold": 321, "essence": 45}
                raise MemoryReaderError("forced snapshot failure")

        memory_reader = FlakyMemoryReader()
        bridge = LiveBridge(
            catalog=self.repo,
            replay_store=self.store,
            project_root=self.repo.project_root,
            memory_reader=memory_reader,  # type: ignore[arg-type]
        )

        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_valid_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=True),
            patch.object(bridge, "_is_admin_context", return_value=True),
        ):
            status = bridge.connect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=False,
                dataset_version="1.0.0",
            )

        self.assertEqual(status["mode"], "memory")
        snap = bridge.snapshot()
        self.assertEqual(snap.source_mode, "synthetic")
        self.assertEqual(snap.wave, 1)

        after = bridge.status()
        self.assertEqual(after["mode"], "degraded")
        self.assertTrue(after["reason"].startswith("memory_snapshot_failed:"))
        self.assertFalse(after["memory_connected"])
        self.assertEqual(after["last_memory_values"]["current_wave"], 7)
        self.assertEqual(after["last_memory_values"]["gold"], 321)
        self.assertEqual(after["last_error"]["stage"], "snapshot_memory_read")
        self.assertEqual(after["last_error"]["type"], "MemoryReaderError")
        self.assertGreaterEqual(memory_reader.close_calls, 2)
        self.assertEqual(memory_reader.read_calls, 2)

    def test_live_bridge_accepts_composite_signature_profile_without_calibration_path(self) -> None:
        class CompositeProfileMemoryReader:
            def __init__(self):
                self.connected = False

            def close(self) -> None:
                self.connected = False

            def open(self, process_name: str, profile) -> None:
                self.connected = True

            def read_fields(self, profile):
                return {"current_wave": 6, "gold": 123, "essence": 45}

        bridge = LiveBridge(
            catalog=self.repo,
            replay_store=self.store,
            project_root=self.repo.project_root,
            memory_reader=CompositeProfileMemoryReader(),  # type: ignore[arg-type]
        )

        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_valid_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=True),
            patch.object(bridge, "_is_admin_context", return_value=True),
        ):
            status = bridge.connect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=False,
                dataset_version="1.0.0",
                signature_profile_id="live_memory_v1_test@artifact_combo_1",
            )
            snapshot = bridge.snapshot()

        self.assertEqual(status["mode"], "memory")
        self.assertEqual(status["signature_profile"], "live_memory_v1_test")
        self.assertTrue(status["memory_connected"])
        self.assertEqual(status["reason"], "ok")
        self.assertEqual(snapshot.wave, 6)
        self.assertEqual(snapshot.source_mode, "memory")

    def test_live_bridge_calibration_candidates_support_fast_switch(self) -> None:
        class CandidateMemoryReader:
            def __init__(self):
                self.connected = False

            def close(self) -> None:
                self.connected = False

            def open(self, process_name: str, profile) -> None:
                self.connected = True

            def read_fields(self, profile):
                wave_address = profile.fields["current_wave"].address
                if wave_address == 0x1110:
                    return {"current_wave": 11, "gold": 101, "essence": 21}
                if wave_address == 0x4440:
                    return {"current_wave": 22, "gold": 202, "essence": 42}
                raise MemoryReaderError(f"unknown_candidate_wave_address:{hex(wave_address)}")

        calibration_path = Path(self._tmpdir.name) / "memory_calibration_candidates.json"
        calibration_path.write_text(
            json.dumps(
                {
                    "active_candidate_id": "candidate_a",
                    "candidates": [
                        {
                            "id": "candidate_a",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x1110"},
                                "gold": {"address": "0x2220"},
                                "essence": {"address": "0x3330"},
                            },
                        },
                        {
                            "id": "candidate_b",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x4440"},
                                "gold": {"address": "0x5550"},
                                "essence": {"address": "0x6660"},
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        bridge = LiveBridge(
            catalog=self.repo,
            replay_store=self.store,
            project_root=self.repo.project_root,
            memory_reader=CandidateMemoryReader(),  # type: ignore[arg-type]
        )

        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_unresolved_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=True),
            patch.object(bridge, "_is_admin_context", return_value=True),
        ):
            status_a = bridge.connect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=False,
                dataset_version="1.0.0",
                signature_profile_id="base_profile@candidate_a",
                calibration_candidates_path=str(calibration_path),
            )
            snapshot_a = bridge.snapshot()

            status_b = bridge.connect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=False,
                dataset_version="1.0.0",
                calibration_candidates_path=str(calibration_path),
                calibration_candidate_id="candidate_b",
            )
            snapshot_b = bridge.snapshot()

        self.assertEqual(status_a["mode"], "memory")
        self.assertEqual(status_a["signature_profile"], "base_profile@candidate_a")
        self.assertEqual(status_a["calibration_candidate"], "candidate_a")
        self.assertEqual(status_a["calibration_candidate_ids"], ["candidate_a", "candidate_b"])
        self.assertEqual(status_a["required_field_resolution"]["current_wave"]["address"], "0x1110")
        self.assertTrue(status_a["required_field_resolution"]["current_wave"]["resolved"])
        self.assertEqual(
            status_a["field_coverage"],
            {
                "required_total": 3,
                "required_resolved": 3,
                "optional_total": 0,
                "optional_resolved": 0,
            },
        )
        self.assertEqual(status_a["calibration_quality"], "full")
        self.assertEqual(status_a["active_required_fields"], ["current_wave", "gold", "essence"])
        self.assertEqual(status_a["last_memory_values"]["current_wave"], 11)
        self.assertEqual(Path(status_a["calibration_candidates_path"]), calibration_path)
        self.assertEqual(snapshot_a.wave, 11)

        self.assertEqual(status_b["mode"], "memory")
        self.assertEqual(status_b["signature_profile"], "base_profile@candidate_b")
        self.assertEqual(status_b["calibration_candidate"], "candidate_b")
        self.assertEqual(status_b["required_field_resolution"]["current_wave"]["address"], "0x4440")
        self.assertEqual(status_b["last_memory_values"]["current_wave"], 22)
        self.assertEqual(snapshot_b.wave, 22)

    def test_live_bridge_uses_calibration_layer_candidate_selection_rule(self) -> None:
        class CandidateRuleMemoryReader:
            def __init__(self):
                self.connected = False

            def close(self) -> None:
                self.connected = False

            def open(self, process_name: str, profile) -> None:
                self.connected = True

            def read_fields(self, profile):
                wave_address = profile.fields["current_wave"].address
                if wave_address == 0x4440:
                    return {"current_wave": 44, "gold": 404, "essence": 84}
                raise MemoryReaderError(f"unexpected_wave_address:{hex(wave_address)}")

        calibration_path = Path(self._tmpdir.name) / "candidate_selection_rule.json"
        calibration_path.write_text(
            json.dumps(
                {
                    "active_candidate_id": "candidate_incomplete",
                    "candidates": [
                        {
                            "id": "candidate_incomplete",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x1110"},
                            },
                        },
                        {
                            "id": "candidate_complete",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x4440"},
                                "gold": {"address": "0x5550"},
                                "essence": {"address": "0x6660"},
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        bridge = LiveBridge(
            catalog=self.repo,
            replay_store=self.store,
            project_root=self.repo.project_root,
            memory_reader=CandidateRuleMemoryReader(),  # type: ignore[arg-type]
        )

        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_unresolved_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=True),
            patch.object(bridge, "_is_admin_context", return_value=True),
        ):
            status = bridge.connect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=False,
                dataset_version="1.0.0",
                calibration_candidates_path=str(calibration_path),
            )
            snapshot = bridge.snapshot()

        self.assertEqual(status["mode"], "memory")
        self.assertEqual(status["calibration_candidate"], "candidate_complete")
        self.assertEqual(status["signature_profile"], "base_profile@candidate_complete")
        self.assertEqual(status["required_field_resolution"]["current_wave"]["address"], "0x4440")
        self.assertEqual(snapshot.wave, 44)

    def test_live_bridge_inspect_candidates_exposes_recommendation_and_candidate_quality(self) -> None:
        calibration_path = Path(self._tmpdir.name) / "inspect_candidates.json"
        calibration_path.write_text(
            json.dumps(
                {
                    "active_candidate_id": "candidate_partial",
                    "candidates": [
                        {
                            "id": "candidate_partial",
                            "fields": {
                                "current_wave": {"address": "0x1110"},
                                "gold": {"address": "0x0"},
                                "essence": {"address": "0x3330"},
                            },
                        },
                        {
                            "id": "candidate_full",
                            "fields": {
                                "current_wave": {"address": "0x4440"},
                                "gold": {"address": "0x5550"},
                                "essence": {"address": "0x6660"},
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        bridge = LiveBridge(catalog=self.repo, replay_store=self.store, project_root=self.repo.project_root)
        payload = bridge.inspect_calibration_candidates(str(calibration_path))

        self.assertEqual(Path(payload["path"]), calibration_path)
        self.assertEqual(payload["active_candidate_id"], "candidate_partial")
        self.assertEqual(payload["recommended_candidate_id"], "candidate_full")
        self.assertEqual(payload["candidate_ids"], ["candidate_partial", "candidate_full"])

        by_id = {item["id"]: item for item in payload["candidates"]}
        partial_quality = by_id["candidate_partial"]["candidate_quality"]
        full_quality = by_id["candidate_full"]["candidate_quality"]

        self.assertFalse(partial_quality["valid"])
        self.assertEqual(
            _quality_count(
                partial_quality,
                primary="resolved_required_count",
                legacy="resolved_required_fields",
            ),
            2,
        )
        self.assertEqual(
            _quality_count(
                partial_quality,
                primary="resolved_optional_count",
                legacy="resolved_optional_fields",
            ),
            0,
        )
        self.assertIn("gold", partial_quality["unresolved_required_field_names"])
        self.assertTrue(full_quality["valid"])
        self.assertEqual(
            _quality_count(
                full_quality,
                primary="resolved_required_count",
                legacy="resolved_required_fields",
            ),
            3,
        )
        self.assertEqual(
            _quality_count(
                full_quality,
                primary="resolved_optional_count",
                legacy="resolved_optional_fields",
            ),
            0,
        )

        support = payload["recommended_candidate_support"]
        self.assertEqual(support["recommended_candidate_id"], "candidate_full")
        self.assertEqual(len(support["candidate_scores"]), 2)
        self.assertEqual(support["reason"], "max_required_resolved_original_order_tiebreak")
        # Recommendation payload should be deterministic for the same input file.
        payload_repeat = bridge.inspect_calibration_candidates(str(calibration_path))
        self.assertEqual(payload_repeat["recommended_candidate_support"], support)

    def test_live_snapshot_memory_adds_combat_block_defaults(self) -> None:
        class CombatFieldMemoryReader:
            def __init__(self):
                self.connected = False

            def close(self) -> None:
                self.connected = False

            def open(self, process_name: str, profile) -> None:
                self.connected = True

            def read_fields(self, profile):
                return {
                    "current_wave": 8,
                    "gold": 180,
                    "essence": 21,
                }

        bridge = LiveBridge(
            catalog=self.repo,
            replay_store=self.store,
            project_root=self.repo.project_root,
            memory_reader=CombatFieldMemoryReader(),  # type: ignore[arg-type]
        )

        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_valid_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=True),
            patch.object(bridge, "_is_admin_context", return_value=True),
        ):
            status = bridge.connect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=False,
                dataset_version="1.0.0",
            )
            snapshot = bridge.snapshot()
            snapshot_repeat = bridge.snapshot()

        self.assertEqual(status["mode"], "memory")
        self.assertEqual(snapshot.source_mode, "memory")
        raw_fields = snapshot.build["raw_memory_fields"]
        self.assertEqual(raw_fields["current_wave"], 8)
        self.assertEqual(raw_fields["gold"], 180)
        self.assertEqual(raw_fields["essence"], 21)
        self.assertEqual(raw_fields["combat_block_value"], 0.0)
        self.assertEqual(raw_fields["combat_block_percent"], 0.0)
        self.assertEqual(raw_fields["combat_block_flat"], 0.0)
        expected_zero_numeric = (
            "wood",
            "stone",
            "wheat",
            "workers_total",
            "workers_free",
            "base_hp_current",
            "base_hp_max",
            "leaks_total",
            "enemies_alive",
            "boss_hp_current",
            "boss_hp_max",
            "wave_elapsed_s",
            "wave_remaining_s",
            "barrier_hp_total",
            "enemy_regen_total_per_s",
        )
        for key in expected_zero_numeric:
            self.assertIn(key, raw_fields)
            self.assertEqual(float(raw_fields[key]), 0.0)
        self.assertIn("boss_alive", raw_fields)
        self.assertIn("is_combat_phase", raw_fields)
        self.assertFalse(bool(raw_fields["boss_alive"]))
        self.assertFalse(bool(raw_fields["is_combat_phase"]))
        combat_block = snapshot.build["combat"]["block"]
        self.assertEqual(combat_block["value"], 0.0)
        self.assertEqual(combat_block["percent"], 0.0)
        self.assertEqual(combat_block["flat"], 0.0)
        raw_fields_repeat = snapshot_repeat.build["raw_memory_fields"]
        self.assertEqual(raw_fields_repeat["combat_block_value"], 0.0)
        self.assertEqual(raw_fields_repeat["combat_block_percent"], 0.0)
        self.assertEqual(raw_fields_repeat["combat_block_flat"], 0.0)
        for key in expected_zero_numeric:
            self.assertEqual(float(raw_fields_repeat[key]), 0.0)
        self.assertEqual(float(raw_fields["tower_inflation_index"]), 1.0)
        self.assertEqual(float(raw_fields_repeat["tower_inflation_index"]), 1.0)
        self.assertFalse(bool(raw_fields_repeat["boss_alive"]))
        self.assertFalse(bool(raw_fields_repeat["is_combat_phase"]))

    def test_live_snapshot_infers_leaks_and_combat_phase_from_partial_combat_fields(self) -> None:
        bridge = LiveBridge(catalog=self.repo, replay_store=self.store, project_root=self.repo.project_root)
        snapshot = bridge._snapshot_from_memory_values(
            now=123.0,
            values={
                "current_wave": 4,
                "gold": 120,
                "essence": 15,
                "player_hp": 17,
                "max_player_hp": 20,
                "enemies_alive": 6,
            },
        )
        raw_fields = snapshot.build["raw_memory_fields"]

        self.assertEqual(raw_fields["base_hp_current"], 17)
        self.assertEqual(raw_fields["base_hp_max"], 20)
        self.assertEqual(raw_fields["leaks_total"], 3)
        self.assertEqual(raw_fields["enemies_alive"], 6)
        self.assertTrue(bool(raw_fields["is_combat_phase"]))

    def test_live_bridge_autodiscovers_calibration_candidates_without_path(self) -> None:
        class AutoDiscoveryMemoryReader:
            def __init__(self):
                self.connected = False

            def close(self) -> None:
                self.connected = False

            def open(self, process_name: str, profile) -> None:
                self.connected = True

            def read_fields(self, profile):
                wave_address = profile.fields["current_wave"].address
                if wave_address != 0x7770:
                    raise MemoryReaderError(f"unexpected_wave_address:{hex(wave_address)}")
                return {"current_wave": 33, "gold": 303, "essence": 63}

        bundle_root = Path(self._tmpdir.name) / "bundle"
        internal_root = bundle_root / "_internal"
        internal_root.mkdir(parents=True, exist_ok=True)
        worklogs_root = bundle_root / "worklogs"
        worklogs_root.mkdir(parents=True, exist_ok=True)
        calibration_path = worklogs_root / "memory_calibration_candidates_autodiscovery.json"
        calibration_path.write_text(
            json.dumps(
                {
                    "active_candidate_id": "candidate_auto",
                    "candidates": [
                        {
                            "id": "candidate_auto",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x7770"},
                                "gold": {"address": "0x8880"},
                                "essence": {"address": "0x9990"},
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        bridge = LiveBridge(
            catalog=self.repo,
            replay_store=self.store,
            project_root=internal_root,
            memory_reader=AutoDiscoveryMemoryReader(),  # type: ignore[arg-type]
        )

        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_unresolved_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=True),
            patch.object(bridge, "_is_admin_context", return_value=True),
        ):
            status = bridge.connect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=False,
                dataset_version="1.0.0",
            )
            snapshot = bridge.snapshot()

        self.assertEqual(status["mode"], "memory")
        self.assertEqual(status["calibration_candidate"], "candidate_auto")
        self.assertEqual(status["signature_profile"], "base_profile@candidate_auto")
        self.assertEqual(Path(status["calibration_candidates_path"]), calibration_path.resolve())
        self.assertEqual(snapshot.wave, 33)

    def test_live_calibration_candidates_route_returns_ids_and_addresses(self) -> None:
        try:
            from nordhold import api as api_module
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI stack is not importable in this environment: {exc}")
            return

        calibration_path = Path(self._tmpdir.name) / "route_candidates.json"
        calibration_path.write_text(
            json.dumps(
                {
                    "active_candidate_id": "candidate_a",
                    "candidates": [
                        {
                            "id": "candidate_a",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x1110"},
                                "gold": {"address": "0x2220"},
                                "essence": {"address": "0x3330"},
                            },
                        },
                        {
                            "id": "candidate_b",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x4440"},
                                "gold": {"address": "0x5550"},
                                "essence": {"address": "0x6660"},
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        original_project_root = api_module.live_bridge.project_root
        try:
            api_module.live_bridge.project_root = Path(self._tmpdir.name)
            payload = api_module.live_calibration_candidates(path=calibration_path.name)
        finally:
            api_module.live_bridge.project_root = original_project_root

        self.assertEqual(payload["active_candidate_id"], "candidate_a")
        self.assertEqual(payload["recommended_candidate_id"], "candidate_a")
        self.assertEqual(payload["candidate_ids"], ["candidate_a", "candidate_b"])
        self.assertEqual(payload["candidates"][0]["fields"]["current_wave"], "0x1110")
        self.assertEqual(payload["candidates"][1]["fields"]["essence"], "0x6660")
        route_quality = payload["candidates"][0]["candidate_quality"]
        self.assertTrue(route_quality["valid"])
        self.assertEqual(
            _quality_count(
                route_quality,
                primary="resolved_required_count",
                legacy="resolved_required_fields",
            ),
            3,
        )
        self.assertEqual(
            _quality_count(
                route_quality,
                primary="resolved_optional_count",
                legacy="resolved_optional_fields",
            ),
            0,
        )
        self.assertEqual(
            payload["recommended_candidate_support"]["reason"],
            "max_required_resolved_active_candidate_tiebreak",
        )

    def test_live_calibration_candidates_route_autodiscovers_when_path_is_omitted(self) -> None:
        try:
            from nordhold import api as api_module
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI stack is not importable in this environment: {exc}")
            return

        worklogs_dir = Path(self._tmpdir.name) / "worklogs" / "route"
        worklogs_dir.mkdir(parents=True, exist_ok=True)
        calibration_path = worklogs_dir / "memory_calibration_candidates_route.json"
        calibration_path.write_text(
            json.dumps(
                {
                    "active_candidate_id": "route_auto",
                    "candidates": [
                        {
                            "id": "route_auto",
                            "fields": {
                                "current_wave": {"address": "0x1010"},
                                "gold": {"address": "0x2020"},
                                "essence": {"address": "0x3030"},
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        original_project_root = api_module.live_bridge.project_root
        try:
            api_module.live_bridge.project_root = Path(self._tmpdir.name)
            payload = api_module.live_calibration_candidates()
        finally:
            api_module.live_bridge.project_root = original_project_root

        self.assertEqual(payload["active_candidate_id"], "route_auto")
        self.assertEqual(payload["candidate_ids"], ["route_auto"])
        self.assertEqual(Path(payload["path"]), calibration_path.resolve())

    def test_live_bridge_autoconnect_selects_recommended_candidate_deterministically(self) -> None:
        class AutoconnectMemoryReader:
            def __init__(self):
                self.connected = False

            def close(self) -> None:
                self.connected = False

            def open(self, process_name: str, profile) -> None:
                self.connected = True

            def read_fields(self, profile):
                wave_address = profile.fields["current_wave"].address
                if wave_address != 0x4440:
                    raise MemoryReaderError(f"unexpected_wave_address:{hex(wave_address)}")
                return {"current_wave": 12, "gold": 240, "essence": 30}

        worklogs_dir = Path(self._tmpdir.name) / "worklogs" / "autoconnect"
        worklogs_dir.mkdir(parents=True, exist_ok=True)
        calibration_path = worklogs_dir / "memory_calibration_candidates_autoconnect.json"
        calibration_path.write_text(
            json.dumps(
                {
                    "active_candidate_id": "candidate_partial",
                    "candidates": [
                        {
                            "id": "candidate_partial",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x1110"},
                                "gold": {"address": "0x0"},
                                "essence": {"address": "0x3330"},
                            },
                        },
                        {
                            "id": "candidate_full",
                            "profile_id": "base_profile",
                            "fields": {
                                "current_wave": {"address": "0x4440"},
                                "gold": {"address": "0x5550"},
                                "essence": {"address": "0x6660"},
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        bridge = LiveBridge(
            catalog=self.repo,
            replay_store=self.store,
            project_root=Path(self._tmpdir.name),
            memory_reader=AutoconnectMemoryReader(),  # type: ignore[arg-type]
        )

        with (
            patch.object(self.repo, "load_memory_signatures", return_value=_unresolved_memory_signatures()),
            patch.object(bridge, "_process_exists", return_value=True),
            patch.object(bridge, "_is_admin_context", return_value=True),
        ):
            status = bridge.autoconnect(
                process_name="NordHold.exe",
                poll_ms=1000,
                require_admin=False,
            )

        self.assertEqual(status["mode"], "memory")
        self.assertEqual(status["calibration_candidate"], "candidate_full")
        self.assertEqual(status["signature_profile"], "base_profile@candidate_full")
        self.assertEqual(Path(status["calibration_candidates_path"]), calibration_path.resolve())
        self.assertTrue(status["autoconnect_enabled"])
        self.assertTrue(status["dataset_autorefresh"])
        self.assertTrue(status["autoconnect_last_attempt_at"])
        self.assertEqual(
            status["autoconnect_last_result"]["candidate_selection"]["selected_candidate_id"],
            "candidate_full",
        )

    def test_live_autoconnect_route_uses_default_payload(self) -> None:
        try:
            from nordhold import api as api_module
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI stack is not importable in this environment: {exc}")
            return

        fake_status = {"status": "connected", "mode": "memory", "reason": "ok"}
        with patch.object(api_module.live_bridge, "autoconnect", return_value=fake_status) as mocked:
            payload = api_module.live_autoconnect()

        self.assertEqual(payload, fake_status)
        called = mocked.call_args.kwargs
        self.assertEqual(called["process_name"], "NordHold.exe")
        self.assertEqual(called["poll_ms"], 1000)
        self.assertTrue(called["require_admin"])
        self.assertEqual(called["dataset_version"], "")
        self.assertTrue(called["dataset_autorefresh"])
        self.assertEqual(called["calibration_candidates_path"], "")
        self.assertEqual(called["calibration_candidate_id"], "")

    def test_events_endpoint_returns_sse_status_event(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from nordhold import api as api_module
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI stack is not importable in this environment: {exc}")
            return

        client = TestClient(api_module.app)
        response = client.get("/api/v1/events?limit=1&heartbeat_ms=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-type", "").split(";")[0], "text/event-stream")
        self.assertIn("event: status", response.text)
        self.assertIn('"source_provenance"', response.text)
        self.assertIn('"economy"', response.text)


if __name__ == "__main__":
    unittest.main()
