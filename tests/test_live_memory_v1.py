from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from nordhold.realtime.calibration_candidates import (
    build_calibration_candidates_from_snapshots,
    calibration_candidate_recommendation,
    choose_calibration_candidate_id,
    list_calibration_candidate_summaries,
    load_calibration_payload,
    resolve_calibration_payload_path,
)
from nordhold.realtime.memory_reader import (
    MemoryProfile,
    MemoryProfileError,
    MemoryReader,
    apply_calibration_candidate,
    load_memory_profile,
)


def _quality_count(quality: dict, *, primary: str, legacy: str) -> int:
    if primary in quality:
        primary_value = int(quality[primary])
        if legacy in quality:
            assert primary_value == int(quality[legacy])
        return primary_value
    if legacy in quality:
        return int(quality[legacy])
    raise AssertionError(f"candidate_quality missing count keys: {primary} / {legacy}")


class FakeMemoryBackend:
    def __init__(self, *, memory: dict[int, bytes], module_base: int = 0):
        self.memory = dict(memory)
        self.module_base = module_base
        self.last_process_name = ""
        self.last_module_name = ""
        self.open_calls: list[int] = []
        self.close_calls: list[int] = []
        self.read_calls: list[tuple[int, int, int]] = []

    def supports_memory_read(self) -> bool:
        return True

    def find_process_id(self, process_name: str) -> int | None:
        self.last_process_name = process_name
        return 4242

    def open_process(self, pid: int) -> int:
        self.open_calls.append(pid)
        return 9001

    def close_process(self, handle: int) -> None:
        self.close_calls.append(handle)

    def get_module_base(self, pid: int, module_name: str) -> int:
        self.last_module_name = module_name
        return self.module_base

    def read_memory(self, handle: int, address: int, size: int) -> bytes:
        self.read_calls.append((handle, address, size))
        payload = self.memory.get(address)
        if payload is None:
            raise AssertionError(f"Unexpected memory read at {hex(address)}")
        if len(payload) != size:
            raise AssertionError(
                f"Unexpected read size at {hex(address)}: expected {len(payload)}, got {size}"
            )
        return payload


class LiveMemoryV1ParserReaderTests(unittest.TestCase):
    def test_resolve_calibration_payload_path_falls_back_from_internal_to_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_root = Path(tmp) / "bundle"
            internal_root = bundle_root / "_internal"
            internal_root.mkdir(parents=True, exist_ok=True)
            worklogs_root = bundle_root / "worklogs"
            worklogs_root.mkdir(parents=True, exist_ok=True)
            target = worklogs_root / "memory_calibration_candidates_bundle.json"
            target.write_text("{}", encoding="utf-8")

            resolved = resolve_calibration_payload_path(
                "worklogs/memory_calibration_candidates_bundle.json",
                project_root=internal_root,
            )

            self.assertEqual(resolved, target.resolve())

    def test_load_calibration_payload_autodiscovery_finds_worklogs_in_ancestor_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bundle_internal_root = project_root / "runtime" / "dist" / "NordholdRealtimeLauncher" / "_internal"
            bundle_internal_root.mkdir(parents=True, exist_ok=True)
            worklogs = project_root / "worklogs" / "live"
            worklogs.mkdir(parents=True, exist_ok=True)

            calibration_file = worklogs / "memory_calibration_candidates_ancestor.json"
            calibration_file.write_text(json.dumps({"candidates": [{"id": "ancestor"}]}), encoding="utf-8")

            payload, resolved = load_calibration_payload("", project_root=bundle_internal_root)

            self.assertEqual(resolved, calibration_file.resolve())
            self.assertEqual(payload["candidates"][0]["id"], "ancestor")

    def test_load_calibration_payload_autodiscovers_latest_candidate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worklogs = root / "worklogs"
            old_dir = worklogs / "old"
            new_dir = worklogs / "new"
            old_dir.mkdir(parents=True, exist_ok=True)
            new_dir.mkdir(parents=True, exist_ok=True)

            old_file = old_dir / "memory_calibration_candidates_older.json"
            old_file.write_text(json.dumps({"candidates": [{"id": "older"}]}), encoding="utf-8")
            new_file = new_dir / "memory_calibration_candidates_latest.json"
            new_file.write_text(json.dumps({"candidates": [{"id": "latest"}]}), encoding="utf-8")

            os.utime(old_file, (10, 10))
            os.utime(new_file, (20, 20))

            payload, resolved = load_calibration_payload("", project_root=root)

            self.assertEqual(resolved, new_file.resolve())
            self.assertEqual(payload["candidates"][0]["id"], "latest")

    def test_build_calibration_candidates_from_snapshot_meta_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_meta_paths = {}

            def _write_snapshot(field: str, addresses: list[int], value: int) -> Path:
                records_path = root / f"{field}.records.tsv"
                records_path.write_text(
                    "".join(f"{hex(address)}\t{value}\n" for address in addresses),
                    encoding="utf-8",
                )
                meta_path = root / f"{field}.meta.json"
                meta_path.write_text(
                    json.dumps(
                        {
                            "schema": "nordhold_memory_scan_snapshot_v1",
                            "value_type": "int32",
                            "records_path": records_path.name,
                            "records_count": len(addresses),
                        }
                    ),
                    encoding="utf-8",
                )
                return meta_path

            snapshot_meta_paths["current_wave"] = _write_snapshot("wave", [0x1110, 0x1114], 7)
            snapshot_meta_paths["gold"] = _write_snapshot("gold", [0x2220], 100)
            snapshot_meta_paths["essence"] = _write_snapshot("essence", [0x3330, 0x3334], 20)

            output_path = root / "generated_candidates.json"
            payload = build_calibration_candidates_from_snapshots(
                project_root=root,
                field_snapshot_meta_paths=snapshot_meta_paths,
                output_path=output_path,
                profile_id="base_profile",
                max_records_per_field=2,
                max_candidates=3,
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(payload["active_candidate_id"], "artifact_combo_1")
            self.assertEqual(payload["combination_space"], 4)
            self.assertTrue(payload["combination_truncated"])
            self.assertEqual(len(payload["candidates"]), 3)
            first = payload["candidates"][0]
            self.assertEqual(first["id"], "artifact_combo_1")
            self.assertEqual(first["profile_id"], "base_profile")
            self.assertEqual(first["fields"]["current_wave"]["address"], "0x1110")
            self.assertEqual(first["fields"]["gold"]["address"], "0x2220")
            self.assertEqual(first["fields"]["essence"]["address"], "0x3330")

    def test_build_calibration_candidates_supports_extra_combat_meta_and_v2_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _write_snapshot(file_name: str, addresses: list[int]) -> Path:
                records_path = root / f"{file_name}.records.tsv"
                records_path.write_text(
                    "".join(f"{hex(address)}\t1\n" for address in addresses),
                    encoding="utf-8",
                )
                meta_path = root / f"{file_name}.meta.json"
                meta_path.write_text(
                    json.dumps(
                        {
                            "schema": "nordhold_memory_scan_snapshot_v1",
                            "value_type": "int32",
                            "records_path": records_path.name,
                            "records_count": len(addresses),
                        }
                    ),
                    encoding="utf-8",
                )
                return meta_path

            required_meta = {
                "current_wave": _write_snapshot("wave", [0x1010]),
                "gold": _write_snapshot("gold", [0x2020]),
                "essence": _write_snapshot("essence", [0x3030]),
            }
            lives_meta = _write_snapshot("lives", [0x4040, 0x4044])

            output_path = root / "candidates_v2.json"
            payload = build_calibration_candidates_from_snapshots(
                project_root=root,
                field_snapshot_meta_paths=required_meta,
                optional_field_snapshot_meta_paths={"lives": lives_meta},
                output_path=output_path,
                profile_id="base_profile",
                max_records_per_field=2,
                max_candidates=10,
            )

            self.assertEqual(payload["schema"], "nordhold_memory_calibration_candidates_v2")
            self.assertEqual(payload["memory_schema_compatibility"], ["live_memory_v1", "live_memory_v2"])
            self.assertEqual(payload["required_combat_fields"], ["current_wave", "gold", "essence"])
            self.assertIn("lives", payload["optional_combat_fields"])
            self.assertEqual(payload["combat_field_sets"]["optional_with_snapshot_meta"], ["lives"])
            self.assertEqual(payload["recommended_candidate_id"], "artifact_combo_1")
            self.assertEqual(payload["combination_space"], 2)
            self.assertEqual(len(payload["candidates"]), 2)
            self.assertIn("lives", payload["candidates"][0]["fields"])
            self.assertTrue(output_path.exists())

    def test_candidate_recommendation_prefers_valid_then_falls_back_to_best_required_coverage(self) -> None:
        payload = {
            "active_candidate_id": "candidate_c",
            "required_fields": ["current_wave", "gold", "essence"],
            "candidates": [
                {
                    "id": "candidate_a",
                    "fields": {
                        "current_wave": {"address": "0x1110"},
                        "gold": {"address": "0x0"},
                        "essence": {"address": "0x3330"},
                    },
                },
                {
                    "id": "candidate_b",
                    "fields": {
                        "current_wave": {"address": "0x2110"},
                        "gold": {"address": "0x2220"},
                        "essence": {"address": "0x2330"},
                    },
                },
                {
                    "id": "candidate_c",
                    "fields": {
                        "current_wave": {"address": "0x3110"},
                        "gold": {"address": "0x3220"},
                        "essence": {"address": "0x0"},
                    },
                },
            ],
        }

        selected_from_invalid_preferred = choose_calibration_candidate_id(
            payload,
            preferred_candidate_id="candidate_a",
        )
        selected_from_valid_preferred = choose_calibration_candidate_id(
            payload,
            preferred_candidate_id="candidate_b",
        )
        selected_without_preferred = choose_calibration_candidate_id(payload)

        self.assertEqual(selected_from_invalid_preferred, "candidate_b")
        self.assertEqual(selected_from_valid_preferred, "candidate_b")
        self.assertEqual(selected_without_preferred, "candidate_b")

        tie_payload = {
            "active_candidate_id": "candidate_b",
            "required_fields": ["current_wave", "gold", "essence"],
            "candidates": [
                {
                    "id": "candidate_a",
                    "fields": {
                        "current_wave": {"address": "0x1110"},
                        "gold": {"address": "0x1220"},
                        "essence": {"address": "0x0"},
                    },
                },
                {
                    "id": "candidate_b",
                    "fields": {
                        "current_wave": {"address": "0x2110"},
                        "gold": {"address": "0x2220"},
                        "essence": {"address": "0x0"},
                    },
                },
                {
                    "id": "candidate_c",
                    "fields": {
                        "current_wave": {"address": "0x3110"},
                        "gold": {"address": "0x0"},
                        "essence": {"address": "0x3330"},
                    },
                },
            ],
        }
        recommendation = calibration_candidate_recommendation(tie_payload)
        self.assertEqual(recommendation["recommended_candidate_id"], "candidate_b")
        self.assertEqual(recommendation["reason"], "max_required_resolved_active_candidate_tiebreak")
        self.assertEqual(
            [score["id"] for score in recommendation["candidate_scores"]],
            ["candidate_a", "candidate_b", "candidate_c"],
        )
        self.assertEqual(
            recommendation["candidate_scores"][1]["resolved_required_fields"],
            recommendation["candidate_scores"][0]["resolved_required_fields"],
        )
        self.assertTrue(recommendation["candidate_scores"][1]["is_active_candidate"])
        self.assertEqual(calibration_candidate_recommendation(tie_payload), recommendation)

    def test_calibration_candidate_recommendation_requires_stability_probe_when_metrics_present(self) -> None:
        payload = {
            "active_candidate_id": "candidate_full",
            "required_fields": ["current_wave", "gold", "essence"],
            "candidates": [
                {
                    "id": "candidate_full",
                    "stability": {
                        "snapshot_probe_count": 3,
                        "snapshot_total_count": 4,
                        "snapshot_ok_count": 1,
                        "transient_299_count": 0,
                        "connect_failures_total_last": 0,
                        "connect_transient_failure_count": 0,
                        "snapshot_failure_streak_max": 2,
                        "snapshot_failures_total_last": 2,
                    },
                    "fields": {
                        "current_wave": {"address": "0x1110"},
                        "gold": {"address": "0x1220"},
                        "essence": {"address": "0x1330"},
                    },
                },
                {
                    "id": "candidate_unstable",
                    "stability": {
                        "snapshot_probe_count": 3,
                        "snapshot_total_count": 10,
                        "snapshot_ok_count": 0,
                        "transient_299_count": 0,
                        "connect_failures_total_last": 0,
                        "connect_transient_failure_count": 0,
                        "snapshot_failure_streak_max": 0,
                        "snapshot_failures_total_last": 10,
                    },
                    "fields": {
                        "current_wave": {"address": "0x1111"},
                        "gold": {"address": "0x1221"},
                        "essence": {"address": "0x1331"},
                    },
                },
            ],
        }

        recommendation = calibration_candidate_recommendation(payload)
        self.assertTrue(recommendation["no_stable_candidate"])
        self.assertEqual(recommendation["recommended_candidate_id"], "")
        self.assertEqual(recommendation["reason"], "max_required_resolved_no_stable_probe")
        self.assertEqual(choose_calibration_candidate_id(payload), "candidate_full")

    def test_list_calibration_candidate_summaries_includes_candidate_quality(self) -> None:
        payload = {
            "required_fields": ["current_wave", "gold", "essence"],
            "optional_fields": ["lives"],
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
                        "current_wave": {"address": "0x2110"},
                        "gold": {"address": "0x2220"},
                        "essence": {"address": "0x2330"},
                        "lives": {"address": "0x2440"},
                    },
                },
            ],
        }

        summaries = list_calibration_candidate_summaries(payload)
        by_id = {item["id"]: item for item in summaries}

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
        self.assertIn("gold", partial_quality["unresolved_required_field_names"])
        self.assertEqual(
            _quality_count(
                partial_quality,
                primary="resolved_optional_count",
                legacy="resolved_optional_fields",
            ),
            0,
        )

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
            1,
        )

    def test_load_memory_profile_parses_live_memory_v1_fields(self) -> None:
        signatures = {
            "profiles": [
                {
                    "id": "fallback",
                    "process_name": "OtherProcess.exe",
                    "fields": {
                        "current_wave": {"source": "address", "address": "0x1", "type": "int32"},
                        "gold": {"source": "address", "address": "0x2", "type": "int32"},
                        "essence": {"source": "address", "address": "0x3", "type": "int32"},
                    },
                },
                {
                    "id": "live_memory_v1",
                    "process_name": "NordHold.exe",
                    "module_name": "NordHold.exe",
                    "pointer_size": 4,
                    "poll_ms": 250,
                    "required_admin": False,
                    "fields": {
                        "current_wave": {"source": "address", "address": "0x1200", "type": "int32"},
                        "gold": {
                            "source": "pointer_chain",
                            "address": "0x1300",
                            "offsets": ["0x10", 8],
                            "type": "float64",
                            "relative_to_module": True,
                        },
                        "essence": {"source": "address", "address": 0x1400, "type": "uint32"},
                    },
                },
            ]
        }

        profile = load_memory_profile(
            signatures_payload=signatures,
            process_name="NordHold.exe",
            profile_id="live_memory_v1",
        )

        self.assertEqual(profile.id, "live_memory_v1")
        self.assertEqual(profile.process_name, "NordHold.exe")
        self.assertEqual(profile.poll_ms, 250)
        self.assertEqual(profile.pointer_size, 4)
        self.assertFalse(profile.required_admin)
        self.assertEqual(profile.fields["current_wave"].address, 0x1200)
        self.assertEqual(profile.fields["gold"].source, "pointer_chain")
        self.assertEqual(profile.fields["gold"].offsets, (0x10, 0x08))
        self.assertTrue(profile.fields["gold"].relative_to_module)
        self.assertEqual(profile.fields["gold"].value_type, "float64")

    def test_load_memory_profile_supports_live_memory_v2_field_sets(self) -> None:
        signatures = {
            "schema_version": "live_memory_v2",
            "required_combat_fields": ["current_wave", "gold", "essence"],
            "optional_combat_fields": ["lives", "player_hp"],
            "profiles": [
                {
                    "id": "profile_v2",
                    "process_name": "NordHold.exe",
                    "module_name": "NordHold.exe",
                    "fields": {
                        "current_wave": {"source": "address", "address": "0x1000", "type": "int32"},
                        "gold": {"source": "address", "address": "0x1004", "type": "int32"},
                        "essence": {"source": "address", "address": "0x1008", "type": "int32"},
                        "lives": {"source": "address", "address": "0x1010", "type": "int32"},
                    },
                }
            ],
        }

        profile = load_memory_profile(signatures_payload=signatures, process_name="NordHold.exe")
        self.assertEqual(profile.required_combat_fields, ("current_wave", "gold", "essence"))
        self.assertEqual(profile.optional_combat_fields, ("lives", "player_hp"))
        profile.ensure_resolved()

    def test_load_memory_profile_rejects_unknown_schema_version(self) -> None:
        signatures = {
            "schema_version": "live_memory_v3",
            "profiles": [
                {
                    "id": "x",
                    "fields": {
                        "current_wave": {"source": "address", "address": "0x1", "type": "int32"},
                        "gold": {"source": "address", "address": "0x2", "type": "int32"},
                        "essence": {"source": "address", "address": "0x3", "type": "int32"},
                    },
                }
            ],
        }
        with self.assertRaises(MemoryProfileError) as ctx:
            load_memory_profile(signatures_payload=signatures, process_name="NordHold.exe")
        self.assertIn("Unsupported memory_signatures schema_version", str(ctx.exception))

    def test_memory_profile_ensure_resolved_requires_required_fields(self) -> None:
        missing_required = MemoryProfile.from_dict(
            {
                "id": "missing_required",
                "process_name": "NordHold.exe",
                "fields": {
                    "current_wave": {"source": "address", "address": "0x1000", "type": "int32"},
                    "gold": {"source": "address", "address": "0x1004", "type": "int32"},
                },
            },
            default_process_name="NordHold.exe",
        )
        with self.assertRaises(MemoryProfileError) as missing_ctx:
            missing_required.ensure_resolved()
        self.assertIn("missing required fields: essence", str(missing_ctx.exception))

        unresolved_required = MemoryProfile.from_dict(
            {
                "id": "unresolved_required",
                "process_name": "NordHold.exe",
                "fields": {
                    "current_wave": {"source": "address", "address": "0x1000", "type": "int32"},
                    "gold": {"source": "address", "address": "0x1004", "type": "int32"},
                    "essence": {"source": "address", "address": 0, "type": "int32"},
                },
            },
            default_process_name="NordHold.exe",
        )
        with self.assertRaises(MemoryProfileError) as unresolved_ctx:
            unresolved_required.ensure_resolved()
        self.assertIn("unresolved fields: essence", str(unresolved_ctx.exception))

    def test_apply_calibration_candidate_uses_active_candidate(self) -> None:
        base_profile = MemoryProfile.from_dict(
            {
                "id": "default_20985960",
                "process_name": "NordHold.exe",
                "module_name": "NordHold.exe",
                "required_admin": True,
                "fields": {
                    "current_wave": {
                        "source": "address",
                        "address": "0x0",
                        "type": "int32",
                        "relative_to_module": True,
                    },
                    "gold": {
                        "source": "pointer_chain",
                        "address": "0x0",
                        "offsets": ["0x0"],
                        "type": "int32",
                        "relative_to_module": True,
                    },
                    "essence": {
                        "source": "pointer_chain",
                        "address": "0x0",
                        "offsets": ["0x0"],
                        "type": "int32",
                        "relative_to_module": True,
                    },
                },
            },
            default_process_name="NordHold.exe",
        )
        calibration = {
            "active_candidate_id": "candidate_a",
            "candidates": [
                {
                    "id": "candidate_a",
                    "profile_id": "default_20985960",
                    "poll_ms": 250,
                    "required_admin": False,
                    "fields": {
                        "current_wave": {"address": "0x1110"},
                        "gold": {"address": "0x2220", "offsets": ["0x18", "0x8"]},
                        "essence": {"address": "0x3330", "offsets": ["0x20", "0x8"]},
                    },
                },
                {
                    "id": "candidate_b",
                    "profile_id": "default_20985960",
                    "fields": {
                        "current_wave": {"address": "0x4440"},
                        "gold": {"address": "0x5550", "offsets": ["0x10", "0x8"]},
                        "essence": {"address": "0x6660", "offsets": ["0x10", "0x10"]},
                    },
                },
            ],
        }

        calibrated_profile, selected_candidate = apply_calibration_candidate(base_profile, calibration)
        self.assertEqual(selected_candidate, "candidate_a")
        self.assertEqual(calibrated_profile.id, "default_20985960@candidate_a")
        self.assertEqual(calibrated_profile.poll_ms, 250)
        self.assertFalse(calibrated_profile.required_admin)
        self.assertEqual(calibrated_profile.fields["current_wave"].address, 0x1110)
        self.assertEqual(calibrated_profile.fields["gold"].source, "pointer_chain")
        self.assertEqual(calibrated_profile.fields["gold"].offsets, (0x18, 0x08))
        self.assertEqual(calibrated_profile.fields["essence"].offsets, (0x20, 0x08))

    def test_apply_calibration_candidate_switches_explicit_candidate(self) -> None:
        base_profile = MemoryProfile.from_dict(
            {
                "id": "default_20985960",
                "process_name": "NordHold.exe",
                "module_name": "NordHold.exe",
                "pointer_size": 8,
                "fields": {
                    "current_wave": {"source": "address", "address": "0x0", "type": "int32"},
                    "gold": {"source": "address", "address": "0x0", "type": "int32"},
                    "essence": {"source": "address", "address": "0x0", "type": "int32"},
                },
            },
            default_process_name="NordHold.exe",
        )
        calibration = {
            "active_candidate_id": "candidate_a",
            "candidates": [
                {
                    "id": "candidate_a",
                    "profile_id": "default_20985960",
                    "fields": {
                        "current_wave": {"address": "0x1110"},
                        "gold": {"address": "0x2220"},
                        "essence": {"address": "0x3330"},
                    },
                },
                {
                    "id": "candidate_b",
                    "profile_id": "default_20985960",
                    "pointer_size": 4,
                    "fields": {
                        "current_wave": {"address": "0x4440"},
                        "gold": {"address": "0x5550"},
                        "essence": {"address": "0x6660"},
                    },
                },
            ],
        }

        calibrated_profile, selected_candidate = apply_calibration_candidate(
            base_profile,
            calibration,
            candidate_id="candidate_b",
        )
        self.assertEqual(selected_candidate, "candidate_b")
        self.assertEqual(calibrated_profile.id, "default_20985960@candidate_b")
        self.assertEqual(calibrated_profile.pointer_size, 4)
        self.assertEqual(calibrated_profile.fields["current_wave"].address, 0x4440)
        self.assertEqual(calibrated_profile.fields["gold"].address, 0x5550)
        self.assertEqual(base_profile.fields["current_wave"].address, 0x0)

    def test_apply_calibration_candidate_falls_back_when_preferred_candidate_is_not_valid(self) -> None:
        base_profile = MemoryProfile.from_dict(
            {
                "id": "default_20985960",
                "process_name": "NordHold.exe",
                "module_name": "NordHold.exe",
                "pointer_size": 8,
                "fields": {
                    "current_wave": {"source": "address", "address": "0x0", "type": "int32"},
                    "gold": {"source": "address", "address": "0x0", "type": "int32"},
                    "essence": {"source": "address", "address": "0x0", "type": "int32"},
                },
            },
            default_process_name="NordHold.exe",
        )
        calibration = {
            "active_candidate_id": "candidate_partial",
            "candidates": [
                {
                    "id": "candidate_partial",
                    "profile_id": "default_20985960",
                    "fields": {
                        "current_wave": {"address": "0x1110"},
                        "gold": {"address": "0x2220"},
                        "essence": {"address": "0x0"},
                    },
                },
                {
                    "id": "candidate_full",
                    "profile_id": "default_20985960",
                    "fields": {
                        "current_wave": {"address": "0x4440"},
                        "gold": {"address": "0x5550"},
                        "essence": {"address": "0x6660"},
                    },
                },
            ],
        }

        calibrated_profile, selected_candidate = apply_calibration_candidate(
            base_profile,
            calibration,
            candidate_id="candidate_partial",
        )
        self.assertEqual(selected_candidate, "candidate_full")
        self.assertEqual(calibrated_profile.id, "default_20985960@candidate_full")
        self.assertEqual(calibrated_profile.fields["current_wave"].address, 0x4440)

    def test_memory_reader_decodes_typed_reads_from_addresses(self) -> None:
        module_base = 0x1000
        profile = MemoryProfile.from_dict(
            {
                "id": "typed_reads",
                "process_name": "NordHold.exe",
                "module_name": "NordHold.exe",
                "required_admin": False,
                "fields": {
                    "current_wave": {
                        "source": "address",
                        "address": "0x200",
                        "type": "int32",
                        "relative_to_module": True,
                    },
                    "gold": {
                        "source": "address",
                        "address": "0x204",
                        "type": "uint32",
                        "relative_to_module": True,
                    },
                    "essence": {
                        "source": "address",
                        "address": "0x208",
                        "type": "float32",
                        "relative_to_module": True,
                    },
                    "dps": {
                        "source": "address",
                        "address": "0x210",
                        "type": "float64",
                        "relative_to_module": True,
                    },
                },
            },
            default_process_name="NordHold.exe",
        )

        backend = FakeMemoryBackend(
            module_base=module_base,
            memory={
                module_base + 0x200: struct.pack("<i", -7),
                module_base + 0x204: struct.pack("<I", 4_000_000_000),
                module_base + 0x208: struct.pack("<f", 12.5),
                module_base + 0x210: struct.pack("<d", 128.125),
            },
        )
        reader = MemoryReader(backend=backend)
        reader.pointer_size = 8
        reader.open("NordHold.exe", profile)

        values = reader.read_fields(profile)
        self.assertEqual(values["current_wave"], -7)
        self.assertEqual(values["gold"], 4_000_000_000)
        self.assertAlmostEqual(float(values["essence"]), 12.5, places=5)
        self.assertAlmostEqual(float(values["dps"]), 128.125, places=6)
        self.assertTrue(reader.connected)
        self.assertEqual(backend.last_process_name, "NordHold.exe")
        self.assertEqual(backend.last_module_name, "NordHold.exe")

    def test_memory_reader_resolves_pointer_chain_relative_to_module(self) -> None:
        module_base = 0x1000
        profile = MemoryProfile.from_dict(
            {
                "id": "pointer_chain",
                "process_name": "NordHold.exe",
                "module_name": "NordHold.exe",
                "required_admin": False,
                "fields": {
                    "current_wave": {
                        "source": "address",
                        "address": "0x200",
                        "type": "int32",
                        "relative_to_module": True,
                    },
                    "gold": {
                        "source": "pointer_chain",
                        "address": "0x300",
                        "offsets": ["0x10", "0x08"],
                        "type": "float64",
                        "relative_to_module": True,
                    },
                    "essence": {
                        "source": "address",
                        "address": "0x400",
                        "type": "uint32",
                        "relative_to_module": True,
                    },
                },
            },
            default_process_name="NordHold.exe",
        )

        backend = FakeMemoryBackend(
            module_base=module_base,
            memory={
                module_base + 0x200: struct.pack("<i", 9),
                module_base + 0x300: struct.pack("<Q", 0x2000),
                0x2010: struct.pack("<Q", 0x3000),
                0x3008: struct.pack("<d", 123.5),
                module_base + 0x400: struct.pack("<I", 77),
            },
        )
        reader = MemoryReader(backend=backend)
        reader.pointer_size = 8
        reader.open("", profile)

        values = reader.read_fields(profile)
        self.assertEqual(values["current_wave"], 9)
        self.assertAlmostEqual(float(values["gold"]), 123.5, places=6)
        self.assertEqual(values["essence"], 77)

        read_addresses = [address for _, address, _ in backend.read_calls]
        self.assertIn(module_base + 0x300, read_addresses)
        self.assertIn(0x2010, read_addresses)
        self.assertIn(0x3008, read_addresses)
        self.assertLess(read_addresses.index(module_base + 0x300), read_addresses.index(0x2010))
        self.assertLess(read_addresses.index(0x2010), read_addresses.index(0x3008))


if __name__ == "__main__":
    unittest.main()
