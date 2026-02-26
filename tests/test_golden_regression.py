from __future__ import annotations

import json
import unittest

from nordhold.realtime.catalog import CatalogRepository
from nordhold.realtime.engine import evaluate_timeline
from nordhold.realtime.models import BuildPlan


class GoldenRegressionTests(unittest.TestCase):
    @staticmethod
    def _normalize_actual_for_legacy_fixture(actual: dict, expected: dict) -> dict:
        expected_totals = expected.get("totals", {})
        if isinstance(expected_totals, dict) and "economy" not in expected_totals:
            totals = actual.get("totals", {})
            if isinstance(totals, dict):
                normalized_totals = dict(totals)
                normalized_totals.pop("economy", None)
                actual = dict(actual)
                actual["totals"] = normalized_totals
        return actual

    def test_outputs_match_golden_fixtures(self) -> None:
        repo = CatalogRepository()
        project_root = repo.project_root
        golden_dir = project_root / "runtime" / "golden"

        input_paths = sorted(golden_dir.glob("input_*.json"))
        self.assertGreater(len(input_paths), 0, "No golden input fixtures found")

        for input_path in input_paths:
            fixture_id = input_path.stem.removeprefix("input_")
            expected_path = golden_dir / f"expected_{fixture_id}.json"

            with self.subTest(fixture=fixture_id):
                self.assertTrue(expected_path.exists(), f"Missing golden expected fixture: {expected_path.name}")
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                meta, scenario = repo.load_scenario(
                    payload["build_plan"]["scenario_id"],
                    payload.get("dataset_version") or "1.0.0",
                )
                build = BuildPlan.from_dict(payload["build_plan"])

                actual = evaluate_timeline(
                    scenario=scenario,
                    build=build,
                    dataset_version=meta.dataset_version,
                    mode=payload["mode"],
                    seed=int(payload["seed"]),
                    monte_carlo_runs=int(payload["monte_carlo_runs"]),
                ).to_dict()

                expected = json.loads(expected_path.read_text(encoding="utf-8"))
                actual = self._normalize_actual_for_legacy_fixture(actual, expected)
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
