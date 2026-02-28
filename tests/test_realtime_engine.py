from __future__ import annotations

import unittest

from nordhold.realtime.catalog import CatalogRepository
from nordhold.realtime.engine import evaluate_timeline
from nordhold.realtime.models import BuildPlan


class RealtimeEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = CatalogRepository()
        self.meta, self.scenario = self.repo.load_scenario("normal_baseline", "1.0.0")

    def test_expected_mode_produces_wave_results(self) -> None:
        build = BuildPlan.from_dict(
            {
                "scenario_id": "normal_baseline",
                "towers": [
                    {"tower_id": "arrow_tower", "count": 2, "level": 1},
                    {"tower_id": "frost_tower", "count": 1, "level": 0}
                ],
                "active_global_modifiers": ["village_arsenal_l3"],
                "actions": []
            }
        )

        result = evaluate_timeline(
            scenario=self.scenario,
            build=build,
            dataset_version=self.meta.dataset_version,
            mode="expected",
            seed=42,
            monte_carlo_runs=1,
        )

        self.assertGreater(len(result.wave_results), 0)
        self.assertGreater(result.totals["potential_damage"], 0.0)
        self.assertGreaterEqual(result.totals["combat_damage"], 0.0)
        self.assertIn("economy", result.totals)
        self.assertIn("build_spend_gold", result.totals["economy"])
        self.assertIn("workers", result.totals["economy"])
        self.assertGreaterEqual(result.totals["economy"]["workers"]["total"], 0)

    def test_economy_actions_apply_worker_policy_and_build_inflation(self) -> None:
        build = BuildPlan.from_dict(
            {
                "scenario_id": "normal_baseline",
                "towers": [{"tower_id": "arrow_tower", "count": 1, "level": 0}],
                "actions": [
                    {
                        "wave": 1,
                        "at_s": 0.0,
                        "type": "assign_workers",
                        "payload": {"gold_workers": 3, "essence_workers": 1},
                    },
                    {
                        "wave": 1,
                        "at_s": 0.1,
                        "type": "economy_policy",
                        "payload": {"policy_id": "rush"},
                    },
                    {
                        "wave": 1,
                        "at_s": 0.2,
                        "type": "build",
                        "payload": {"tower_id": "arrow_tower", "count": 1, "level": 0},
                    },
                    {
                        "wave": 2,
                        "at_s": 0.0,
                        "type": "build",
                        "payload": {"tower_id": "frost_tower", "count": 1, "level": 1},
                    },
                    {
                        "wave": 2,
                        "at_s": 0.1,
                        "type": "economy_policy",
                        "payload": {"policy_id": "harvest"},
                    },
                    {
                        "wave": 2,
                        "at_s": 0.2,
                        "type": "assign_workers",
                        "payload": {"gold_workers": 1, "essence_workers": 3},
                    },
                ],
            }
        )

        result = evaluate_timeline(
            scenario=self.scenario,
            build=build,
            dataset_version=self.meta.dataset_version,
            mode="expected",
            seed=2026,
            monte_carlo_runs=1,
        )

        economy = result.totals["economy"]
        self.assertEqual(economy["build_actions"], 2)
        self.assertGreater(economy["build_spend_gold"], 0.0)
        self.assertGreater(economy["build_inflation_gold"], 0.0)
        self.assertGreater(economy["gross_gold_income"], economy["build_spend_gold"])
        self.assertEqual(economy["policy_id"], "harvest")
        self.assertEqual(economy["workers"]["total"], 4)
        self.assertEqual(economy["workers"]["gold"], 1)
        self.assertEqual(economy["workers"]["essence"], 3)
        self.assertEqual(economy["workers"]["unassigned"], 0)

    def test_combat_mode_with_runtime_actions_is_deterministic_for_same_seed(self) -> None:
        build = BuildPlan.from_dict(
            {
                "scenario_id": "normal_baseline",
                "towers": [{"tower_id": "arrow_tower", "count": 1, "level": 0}],
                "actions": [
                    {
                        "wave": 1,
                        "at_s": 0.0,
                        "type": "build",
                        "payload": {
                            "tower_id": "frost_tower",
                            "count": 1,
                            "level": 1,
                            "focus_priorities": ["barrier", "highest_hp"],
                            "focus_until_death": True,
                        },
                    },
                    {
                        "wave": 1,
                        "at_s": 0.2,
                        "type": "upgrade",
                        "target_id": "arrow_tower",
                        "payload": {"levels": 2},
                    },
                    {
                        "wave": 1,
                        "at_s": 0.3,
                        "type": "modifier",
                        "target_id": "village_arsenal_l3",
                        "payload": {"enabled": True},
                    },
                    {
                        "wave": 2,
                        "at_s": 0.0,
                        "type": "targeting",
                        "target_id": "arrow_tower",
                        "payload": {
                            "focus_priorities": ["highest_hp", "progress"],
                            "focus_until_death": True,
                        },
                    },
                ],
            }
        )

        result_a = evaluate_timeline(
            scenario=self.scenario,
            build=build,
            dataset_version=self.meta.dataset_version,
            mode="combat",
            seed=1337,
            monte_carlo_runs=1,
        )
        result_b = evaluate_timeline(
            scenario=self.scenario,
            build=build,
            dataset_version=self.meta.dataset_version,
            mode="combat",
            seed=1337,
            monte_carlo_runs=1,
        )

        self.assertEqual(result_a.to_dict(), result_b.to_dict())
        self.assertGreater(result_a.totals["combat_damage"], 0.0)
        self.assertIn("economy", result_a.totals)

    def test_monte_carlo_aggregation_is_seed_deterministic(self) -> None:
        build = BuildPlan.from_dict(
            {
                "scenario_id": "normal_baseline",
                "towers": [{"tower_id": "arrow_tower", "count": 1, "level": 0}],
                "actions": [
                    {
                        "wave": 2,
                        "at_s": 0.0,
                        "type": "targeting",
                        "target_id": "arrow_tower",
                        "payload": {
                            "focus_priorities": ["highest_hp", "barrier"],
                            "focus_until_death": False,
                        },
                    }
                ],
            }
        )

        result_a = evaluate_timeline(
            scenario=self.scenario,
            build=build,
            dataset_version=self.meta.dataset_version,
            mode="monte_carlo",
            seed=111,
            monte_carlo_runs=32,
        )
        result_b = evaluate_timeline(
            scenario=self.scenario,
            build=build,
            dataset_version=self.meta.dataset_version,
            mode="monte_carlo",
            seed=111,
            monte_carlo_runs=32,
        )
        self.assertEqual(result_a.to_dict(), result_b.to_dict())

        distinct_combat_totals = {
            round(
                evaluate_timeline(
                    scenario=self.scenario,
                    build=build,
                    dataset_version=self.meta.dataset_version,
                    mode="monte_carlo",
                    seed=seed,
                    monte_carlo_runs=32,
                ).totals["combat_damage"],
                6,
            )
            for seed in (111, 222, 333)
        }
        self.assertGreater(len(distinct_combat_totals), 1)


if __name__ == "__main__":
    unittest.main()
