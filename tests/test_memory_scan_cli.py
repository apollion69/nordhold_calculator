from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


def _load_memory_scan_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "nordhold_memory_scan.py"
    spec = importlib.util.spec_from_file_location("nordhold_memory_scan_cli", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load script module spec: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MemoryScanCliTests(unittest.TestCase):
    def test_build_calibration_candidates_accepts_extra_combat_meta_paths(self) -> None:
        module = _load_memory_scan_module()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _write_snapshot(stem: str, addresses: list[int]) -> Path:
                records_path = root / f"{stem}.records.tsv"
                records_path.write_text(
                    "".join(f"{hex(address)}\t1\n" for address in addresses),
                    encoding="utf-8",
                )
                meta_path = root / f"{stem}.meta.json"
                meta_path.write_text(
                    json.dumps(
                        {
                            "schema": "nordhold_memory_scan_snapshot_v1",
                            "value_type": "int32",
                            "records_path": str(records_path),
                            "records_count": len(addresses),
                        }
                    ),
                    encoding="utf-8",
                )
                return meta_path

            wave_meta = _write_snapshot("wave", [0x1000])
            gold_meta = _write_snapshot("gold", [0x2000])
            essence_meta = _write_snapshot("essence", [0x3000])
            lives_meta = _write_snapshot("lives", [0x4000, 0x4004])

            out_path = root / "generated_candidates.json"
            parser = module.build_parser()
            args = parser.parse_args(
                [
                    "build-calibration-candidates",
                    "--current-wave-meta",
                    str(wave_meta),
                    "--gold-meta",
                    str(gold_meta),
                    "--essence-meta",
                    str(essence_meta),
                    "--combat-meta",
                    f"lives={lives_meta}",
                    "--out",
                    str(out_path),
                ]
            )

            exit_code = module.cmd_build_calibration_candidates(args)
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "nordhold_memory_calibration_candidates_v2")
            self.assertEqual(payload["recommended_candidate_id"], payload["active_candidate_id"])
            self.assertIn("lives", payload["combat_field_sets"]["optional_with_snapshot_meta"])
            self.assertEqual(payload["combination_space"], 2)


if __name__ == "__main__":
    unittest.main()
