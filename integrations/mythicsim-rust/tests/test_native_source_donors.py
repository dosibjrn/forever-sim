"""Pinned source-donor inventory and JOINT adapter provenance contracts."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_joint_two_class import source_bounded_adapter
from native_source_donors import (
    DONOR_DIRECTORIES, load_source_donor_fixtures, source_profile_hint,
)


def request(class_name="ClassDruid", item_ids=(1001, 1002), talents="99999-6"):
    return {
        "raid": {"parties": [{"players": [{
            "class": class_name,
            "equipment": {"items": [{"id": item_id} for item_id in item_ids]},
            "talentsString": talents,
            "rotation": {"priorityList": [{"action": {"wait": {}}}]},
        }]}]},
        "encounter": {"duration": 180, "targets": 1},
        "simOptions": {"iterations": 3, "randomSeed": "47"},
    }


def donor(source_path, source_request):
    raw = json.dumps(source_request, sort_keys=True).encode("utf-8")
    return {
        "source_path": source_path,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "class_name": source_request["raid"]["parties"][0]["players"][0]["class"],
        "profile_id_hint": source_profile_hint(
            source_path, source_request["raid"]["parties"][0]["players"][0]["class"]
        ),
        "item_count": len(source_request["raid"]["parties"][0]["players"][0]["equipment"]["items"]),
        "request": source_request,
    }


class SourceDonorInventoryTests(unittest.TestCase):
    def make_dirs(self, root):
        for relative in DONOR_DIRECTORIES:
            (root / relative).mkdir(parents=True, exist_ok=True)

    def test_scans_only_curated_dirs_and_records_exact_source_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_dirs(root)
            expected = []
            for index, relative in enumerate(DONOR_DIRECTORIES):
                path = root / relative / f"donor-{index}.request.json"
                raw = json.dumps(request(item_ids=(1001 + index, 1002))).encode("utf-8")
                path.write_bytes(raw)
                expected.append((path.relative_to(root).as_posix(),
                                 hashlib.sha256(raw).hexdigest()))
            ignored = root / "fixtures/not-in-donor-manifest/ignored.request.json"
            ignored.parent.mkdir(parents=True)
            ignored.write_text(json.dumps(request()))

            inventory = load_source_donor_fixtures(root)
            self.assertEqual(list(DONOR_DIRECTORIES), inventory["directories"])
            self.assertEqual([], inventory["skipped"])
            self.assertEqual(
                [None] * len(inventory["fixtures"]),
                [item["profile_id_hint"] for item in inventory["fixtures"]],
            )
            self.assertEqual(
                expected,
                [(item["source_path"], item["source_sha256"])
                 for item in inventory["fixtures"]],
            )
            self.assertEqual(4, len(inventory["fixtures"]))

    def test_unsupported_class_or_empty_gear_is_skipped_with_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_dirs(root)
            unknown = request(class_name="ClassUnknown")
            empty = request()
            empty["raid"]["parties"][0]["players"][0]["equipment"]["items"] = []
            (root / DONOR_DIRECTORIES[0] / "unknown.request.json").write_text(
                json.dumps(unknown)
            )
            (root / DONOR_DIRECTORIES[0] / "empty.request.json").write_text(
                json.dumps(empty)
            )

            inventory = load_source_donor_fixtures(root)
            self.assertEqual([], inventory["fixtures"])
            self.assertEqual(
                [
                    {"source_path": f"{DONOR_DIRECTORIES[0]}/empty.request.json",
                     "reason": "MISSING_OR_EMPTY_EQUIPMENT_ITEMS"},
                    {"source_path": f"{DONOR_DIRECTORIES[0]}/unknown.request.json",
                     "reason": "UNSUPPORTED_OR_MISSING_CLASS"},
                ],
                inventory["skipped"],
            )

    def test_profile_hint_requires_one_explicit_class_spec_path_token(self):
        self.assertEqual(
            "warlock/demonology",
            source_profile_hint(
                "fixtures/forever-gaps/demonology-warlock-black-book.request.json",
                "ClassWarlock",
            ),
        )
        self.assertEqual(
            "warlock/destruction",
            source_profile_hint(
                "fixtures/mage/prepared-v2/destruction-warlock-broad.request.json",
                "ClassWarlock",
            ),
        )
        self.assertEqual(
            "druid/feral_bear",
            source_profile_hint(
                "fixtures/mage/prepared-v2/feral-bear-druid-swipe.request.json",
                "ClassDruid",
            ),
        )
        self.assertIsNone(
            source_profile_hint(
                "fixtures/mage/prepared-v2/feral-druid-swap.request.json",
                "ClassDruid",
            )
        )
        self.assertIsNone(
            source_profile_hint(
                "fixtures/forever-gaps/demonology-warlock-black-book.request.json",
                "ClassMage",
            )
        )

    def test_malformed_pinned_source_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_dirs(root)
            path = root / DONOR_DIRECTORIES[0] / "broken.request.json"
            path.write_text("{")
            with self.assertRaisesRegex(ValueError, "SOURCE_DONOR_JSON_INVALID"):
                load_source_donor_fixtures(root)


class SourceDonorAdapterTests(unittest.TestCase):
    def test_same_class_donors_expand_gear_and_51_point_builds_with_provenance(self):
        reference = request()
        valid_donor_request = request(
            item_ids=(1003, 1002),
            talents="7777777-2",
        )
        invalid_talent_donor_request = request(
            item_ids=(1004, 1002),
            talents="not-a-talent-build",
        )
        other_class_request = request(
            class_name="ClassMage",
            item_ids=(1005, 1002),
            talents="88888-7",
        )
        donors = [
            donor("fixtures/forever-gaps/balance-druid-gear-and-talent.request.json",
                  valid_donor_request),
            donor("fixtures/mage/prepared-v2/druid-gear-only.request.json",
                  invalid_talent_donor_request),
            donor("fixtures/mage/prepared-v2/mage-must-not-cross.request.json",
                  other_class_request),
        ]
        items = {
            1001: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            1002: {"type": "ItemTypeChest", "armor_type": "ArmorTypeCloth"},
            1003: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            1004: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            1005: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
        }

        adapter, scope = source_bounded_adapter(
            "druid", reference, [reference], items,
            profile_id="druid/balance", same_profile=[reference],
            donor_fixtures=donors,
        )

        self.assertEqual([0], scope["gear_mutable_slots"])
        self.assertEqual(
            sorted(["99999-6", "7777777-2"]),
            scope["talent_builds"],
        )
        self.assertEqual(2, scope["source_donor_fixture_count"])
        self.assertEqual(1, scope["talent_donor_fixture_count"])
        self.assertEqual("druid/balance", scope["talent_profile_id"])
        self.assertEqual(
            [
                "fixtures/forever-gaps/balance-druid-gear-and-talent.request.json",
                "fixtures/mage/prepared-v2/druid-gear-only.request.json",
            ],
            [item["source_path"] for item in scope["gear_donor_fixtures_scanned"]],
        )
        self.assertEqual(
            ["fixtures/forever-gaps/balance-druid-gear-and-talent.request.json"],
            [item["source_path"] for item in scope["talent_donor_fixtures"]],
        )
        self.assertTrue(adapter.legal(copy.deepcopy(reference)))


    def test_source_observed_non_51_reference_can_anchor_two_full_51_point_donors(self):
        reference = request(item_ids=(1001, 1002), talents="99999-4")
        donor_one_request = request(
            item_ids=(1003, 1002), talents="7777777-2"
        )
        donor_two_request = request(
            item_ids=(1004, 1002), talents="6666666-9"
        )
        donors = [
            donor("fixtures/production/balance-druid-arcane.request.json", donor_one_request),
            donor("fixtures/production/balance-druid-fire.request.json", donor_two_request),
        ]
        items = {
            1001: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            1002: {"type": "ItemTypeChest", "armor_type": "ArmorTypeCloth"},
            1003: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            1004: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
        }

        adapter, scope = source_bounded_adapter(
            "druid", reference, [reference], items,
            profile_id="druid/balance", same_profile=[reference],
            donor_fixtures=donors,
        )

        self.assertEqual(
            sorted(["7777777-2", "6666666-9"]), scope["talent_builds"]
        )
        self.assertEqual(
            "SAME_PROFILE_SOURCE_OBSERVED_BASELINE_PLUS_51_POINT_WHOLE_BUILDS_NOT_RANKWISE",
            scope["talent_validation"],
        )
        self.assertTrue(adapter.legal(copy.deepcopy(reference)))
        for build in scope["talent_builds"]:
            candidate = copy.deepcopy(reference)
            candidate["raid"]["parties"][0]["players"][0]["talentsString"] = build
            self.assertTrue(adapter.legal(candidate))

    def test_other_spec_donors_supply_gear_but_not_profile_talents(self):
        reference = request(
            class_name="ClassWarlock", item_ids=(1001, 1002), talents="99999-6"
        )
        demonology_request = request(
            class_name="ClassWarlock", item_ids=(1003, 1002), talents="5555555-88"
        )
        destruction_request = request(
            class_name="ClassWarlock", item_ids=(1004, 1002), talents="7777777-2"
        )
        donors = [
            donor(
                "fixtures/forever-gaps/demonology-warlock-black-book.request.json",
                demonology_request,
            ),
            donor(
                "fixtures/mage/prepared-v2/destruction-warlock-broad.request.json",
                destruction_request,
            ),
        ]
        items = {
            1001: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            1002: {"type": "ItemTypeChest", "armor_type": "ArmorTypeCloth"},
            1003: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            1004: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
        }

        adapter, scope = source_bounded_adapter(
            "warlock", reference, [reference, demonology_request], items,
            profile_id="warlock/destruction", same_profile=[reference],
            donor_fixtures=donors,
        )

        self.assertEqual(
            sorted(["99999-6", "7777777-2"]), scope["talent_builds"]
        )
        self.assertEqual(2, scope["source_donor_fixture_count"])
        self.assertEqual(1, scope["talent_donor_fixture_count"])
        self.assertEqual(
            ["fixtures/mage/prepared-v2/destruction-warlock-broad.request.json"],
            [item["source_path"] for item in scope["talent_donor_fixtures"]],
        )

        candidate = copy.deepcopy(reference)
        candidate["raid"]["parties"][0]["players"][0]["talentsString"] = "5555555-88"
        self.assertFalse(adapter.legal(candidate))
        candidate["raid"]["parties"][0]["players"][0]["talentsString"] = "7777777-2"
        self.assertTrue(adapter.legal(candidate))



if __name__ == "__main__":
    unittest.main()
