from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


def _load_promote_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "nordhold_promote_deep_probe_candidates.py"
    )
    spec = importlib.util.spec_from_file_location("nordhold_promote_deep_probe_candidates_cli", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load script module spec: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PromoteDeepProbeCandidatesTests(unittest.TestCase):
    def test_build_promotion_inputs_merges_optional_meta_and_preserves_profile_and_active(self) -> None:
        module = _load_promote_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _write_meta(name: str) -> Path:
                path = root / f"{name}.meta.json"
                path.write_text("{}", encoding="utf-8")
                return path

            report_path = root / "combat_deep_probe_report.json"
            source_path = root / "source_candidates.json"

            source_payload = {
                "required_combat_fields": ["current_wave", "gold", "essence"],
                "optional_combat_fields": ["player_hp", "max_player_hp", "enemies_alive"],
                "source_snapshot_meta_paths": {
                    "current_wave": str(_write_meta("wave")),
                    "gold": str(_write_meta("gold")),
                    "essence": str(_write_meta("essence")),
                    "player_hp": str(_write_meta("player_hp")),
                    "max_player_hp": str(_write_meta("max_player_hp")),
                },
                "active_candidate_id": "artifact_combo_3",
                "recommended_candidate_id": "artifact_combo_2",
                "candidates": [
                    {"id": "artifact_combo_3", "profile_id": "default_20985960"},
                ],
            }
            report_payload = {
                "summary": {
                    "selected_meta": {
                        "enemies_alive": {
                            "meta_path": str(_write_meta("enemies_alive")),
                        }
                    }
                }
            }

            inputs = module._build_promotion_inputs(
                report_payload=report_payload,
                report_path=report_path,
                source_payload=source_payload,
                source_payload_path=source_path,
                project_root=root,
                active_candidate_id_override="",
            )

            self.assertEqual(inputs.required_fields, ("current_wave", "gold", "essence"))
            self.assertEqual(inputs.profile_id, "default_20985960")
            self.assertEqual(inputs.active_candidate_id, "artifact_combo_3")
            self.assertEqual(inputs.selected_optional_fields, ("enemies_alive",))
            self.assertEqual(
                tuple(inputs.optional_snapshot_meta_paths.keys()),
                ("player_hp", "max_player_hp", "enemies_alive"),
            )

            overridden = module._build_promotion_inputs(
                report_payload=report_payload,
                report_path=report_path,
                source_payload=source_payload,
                source_payload_path=source_path,
                project_root=root,
                active_candidate_id_override="override_candidate_1",
            )
            self.assertEqual(overridden.active_candidate_id, "override_candidate_1")

    def test_build_promotion_inputs_fails_for_missing_required_snapshot_meta_path(self) -> None:
        module = _load_promote_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            required_meta = root / "wave.meta.json"
            required_meta.write_text("{}", encoding="utf-8")

            source_payload = {
                "required_fields": ["current_wave", "gold", "essence"],
                "source_snapshot_meta_paths": {
                    "current_wave": str(required_meta),
                    "essence": str(required_meta),
                },
            }
            report_payload = {"summary": {"selected_meta": {}}}

            with self.assertRaisesRegex(ValueError, "Missing required snapshot meta path\\(s\\).*gold"):
                module._build_promotion_inputs(
                    report_payload=report_payload,
                    report_path=root / "report.json",
                    source_payload=source_payload,
                    source_payload_path=root / "source.json",
                    project_root=root,
                    active_candidate_id_override="",
                )


if __name__ == "__main__":
    unittest.main()
