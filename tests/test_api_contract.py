from __future__ import annotations

import unittest


class ApiContractTests(unittest.TestCase):
    def test_v1_routes_exist(self) -> None:
        try:
            from nordhold.api import app
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI stack is not importable in this environment: {exc}")
            return

        paths = {route.path for route in app.routes}
        expected = {
            "/api/v1/live/connect",
            "/api/v1/live/autoconnect",
            "/api/v1/live/status",
            "/api/v1/live/calibration/candidates",
            "/api/v1/live/snapshot",
            "/api/v1/dataset/version",
            "/api/v1/dataset/catalog",
            "/api/v1/run/state",
            "/api/v1/events",
            "/api/v1/replay/import",
            "/api/v1/timeline/evaluate",
            "/api/v1/analytics/compare",
            "/api/v1/analytics/sensitivity",
            "/api/v1/analytics/forecast",
        }
        self.assertTrue(expected.issubset(paths))

    def test_live_status_and_snapshot_contract_shape(self) -> None:
        try:
            from nordhold import api as api_module
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI stack is not importable in this environment: {exc}")
            return

        status = api_module.live_status()
        required_status_keys = {
            "status",
            "mode",
            "process_name",
            "poll_ms",
            "require_admin",
            "dataset_version",
            "game_build",
            "signature_profile",
            "calibration_candidates_path",
            "calibration_candidate",
            "reason",
            "replay_session_id",
            "memory_connected",
            "required_field_resolution",
            "field_coverage",
            "calibration_quality",
            "active_required_fields",
            "calibration_candidate_ids",
            "last_memory_values",
            "last_error",
            "autoconnect_enabled",
            "autoconnect_last_attempt_at",
            "autoconnect_last_result",
            "dataset_autorefresh",
        }
        self.assertTrue(required_status_keys.issubset(status.keys()))
        self.assertEqual(
            set(status["field_coverage"].keys()),
            {"required_total", "required_resolved", "optional_total", "optional_resolved"},
        )
        coverage = status["field_coverage"]
        for key in ("required_total", "required_resolved", "optional_total", "optional_resolved"):
            self.assertIsInstance(coverage[key], int)
            self.assertGreaterEqual(coverage[key], 0)
        self.assertLessEqual(coverage["required_resolved"], coverage["required_total"])
        self.assertLessEqual(coverage["optional_resolved"], coverage["optional_total"])

        expected_quality = "minimal"
        if coverage["required_total"] > 0 and coverage["required_resolved"] == coverage["required_total"]:
            expected_quality = (
                "full"
                if coverage["optional_total"] == 0 or coverage["optional_resolved"] == coverage["optional_total"]
                else "partial"
            )
        elif coverage["required_resolved"] > 0 or coverage["optional_resolved"] > 0:
            expected_quality = "partial"

        self.assertIn(status["calibration_quality"], {"minimal", "partial", "full"})
        self.assertEqual(status["calibration_quality"], expected_quality)
        self.assertIsInstance(status["active_required_fields"], list)
        self.assertTrue(all(isinstance(field, str) for field in status["active_required_fields"]))
        self.assertEqual(len(status["active_required_fields"]), coverage["required_total"])
        resolution_keys = set(status.get("required_field_resolution", {}).keys())
        self.assertTrue(set(status["active_required_fields"]).issubset(resolution_keys))
        self.assertIsInstance(status["autoconnect_enabled"], bool)
        self.assertIsInstance(status["autoconnect_last_attempt_at"], str)
        self.assertIsInstance(status["autoconnect_last_result"], dict)
        self.assertIsInstance(status["dataset_autorefresh"], bool)

        snapshot = api_module.live_snapshot()
        required_snapshot_keys = {"timestamp", "wave", "gold", "essence", "build", "source_mode"}
        self.assertTrue(required_snapshot_keys.issubset(snapshot.keys()))
        self.assertIsInstance(snapshot["build"], dict)
        raw_memory_fields = snapshot["build"].get("raw_memory_fields")
        if isinstance(raw_memory_fields, dict):
            for key in ("current_wave", "gold", "essence"):
                self.assertIn(key, raw_memory_fields)

            expected_combat_first_fields = (
                "base_hp_current",
                "base_hp_max",
                "leaks_total",
                "enemies_alive",
                "boss_alive",
                "boss_hp_current",
                "boss_hp_max",
                "wave_elapsed_s",
                "wave_remaining_s",
                "barrier_hp_total",
                "enemy_regen_total_per_s",
                "is_combat_phase",
                "wood",
                "stone",
                "wheat",
                "workers_total",
                "workers_free",
                "tower_inflation_index",
            )
            for key in expected_combat_first_fields:
                self.assertIn(key, raw_memory_fields)

            for numeric_key in (
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
                "wood",
                "stone",
                "wheat",
                "workers_total",
                "workers_free",
                "tower_inflation_index",
            ):
                self.assertIsInstance(raw_memory_fields[numeric_key], (int, float))
            self.assertIsInstance(raw_memory_fields["boss_alive"], bool)
            self.assertIsInstance(raw_memory_fields["is_combat_phase"], bool)

    def test_dataset_and_run_state_contract_shape(self) -> None:
        try:
            from nordhold import api as api_module
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI stack is not importable in this environment: {exc}")
            return

        version = api_module.dataset_version()
        self.assertEqual(set(version.keys()), {"dataset_version", "game_version", "build_id"})
        self.assertTrue(version["dataset_version"])

        catalog_payload = api_module.dataset_catalog()
        self.assertIn("dataset", catalog_payload)
        self.assertIn("catalog", catalog_payload)
        self.assertEqual(catalog_payload["dataset"]["dataset_version"], version["dataset_version"])
        self.assertIsInstance(catalog_payload["catalog"], dict)

        run_state = api_module.run_state()
        required_run_state_keys = {
            "timestamp",
            "wave",
            "source_mode",
            "status",
            "mode",
            "reason",
            "dataset_version",
            "game_build",
            "source_provenance",
            "economy",
        }
        self.assertTrue(required_run_state_keys.issubset(run_state.keys()))
        self.assertIsInstance(run_state["source_provenance"], dict)
        self.assertIsInstance(run_state["economy"], dict)
        self.assertEqual(
            set(run_state["economy"].keys()),
            {
                "gold",
                "essence",
                "wood",
                "stone",
                "wheat",
                "workers_total",
                "workers_free",
                "tower_inflation_index",
            },
        )


if __name__ == "__main__":
    unittest.main()
