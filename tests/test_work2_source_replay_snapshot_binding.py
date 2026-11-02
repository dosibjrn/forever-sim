"""Saved P4–P6 finalist replay must use the selected pinned source and profile.

These are small production preflight controls; they never claim 100 paid mobs
or native↔2D gate acceptance.
"""
from copy import deepcopy

import pytest

from src.v2.source_paid_cold_comparison import (
    source_gear_catalogue_snapshot, verify_saved_source_replay,
)


def _saved(snapshot, *, spec="balance"):
    tree = "balance" if spec == "balance" else None
    minimum = 31 if tree else None
    space = {"class_key": "druid", "level": 60}
    if tree:
        space.update({"checkpoint_spec": spec, "spec_tree": tree,
                      "min_spec_points": minimum})
    return {
        "class_key": "druid", "level": 60,
        "source_db_sha256": "canonical-ability-sqlite-hash",
        "source_gear_catalogue_snapshot": deepcopy(snapshot),
        "source_search_space": space,
        "spec_constraint": {"tree_key": tree, "minimum_points": minimum,
                            "required_combat_mode": None},
    }


def _verify(saved, snapshot, *, spec="balance"):
    return verify_saved_source_replay(
        saved, class_key="druid", level=60, spec=spec,
        source_hash="canonical-ability-sqlite-hash",
        gear_snapshot=snapshot,
        **({"spec_tree": "balance", "min_spec_points": 31}
           if spec == "balance" else {}),
    )


@pytest.mark.parametrize("spec", ["balance", "unrestricted"])
def test_unchanged_canonical_gear_and_source_checkpoint_allow_saved_replay(spec):
    snapshot = source_gear_catalogue_snapshot("druid", 60)
    assert _verify(_saved(snapshot, spec=spec), snapshot, spec=spec) is None


def test_unchanged_ability_sqlite_does_not_mask_changed_gear_source():
    snapshot = source_gear_catalogue_snapshot("druid", 60)
    saved = _saved(snapshot)
    changed = deepcopy(snapshot)
    changed["catalogue_sha256"] = "0" * 64
    # Ability/talent SQLite hash and class/level remain identical.
    with pytest.raises(ValueError, match="REPLAY_SOURCE_GEAR_SNAPSHOT_MISMATCH"):
        _verify(saved, changed)


@pytest.mark.parametrize("mutation,expected", [
    ("wrong_profile", "REPLAY_SOURCE_SPEC_MISMATCH"),
    ("wrong_tree", "REPLAY_SOURCE_SPEC_CONSTRAINT_MISMATCH"),
    ("too_few_points", "REPLAY_SOURCE_SPEC_CONSTRAINT_MISMATCH"),
    ("missing_space", "REPLAY_SOURCE_SPEC_MISMATCH"),
    ("wrong_class", "REPLAY_SOURCE_CHECKPOINT_MISMATCH"),
    ("wrong_sqlite", "REPLAY_SOURCE_CHECKPOINT_MISMATCH"),
])
def test_replay_rejects_wrong_saved_checkpoint_before_100_mobs(mutation, expected):
    snapshot = source_gear_catalogue_snapshot("druid", 60)
    saved = _saved(snapshot)
    if mutation == "wrong_profile":
        saved["source_search_space"]["checkpoint_spec"] = "feral"
    elif mutation == "wrong_tree":
        saved["spec_constraint"]["tree_key"] = "feral"
    elif mutation == "too_few_points":
        saved["spec_constraint"]["minimum_points"] = 21
    elif mutation == "missing_space":
        del saved["source_search_space"]
    elif mutation == "wrong_class":
        saved["class_key"] = "mage"
    elif mutation == "wrong_sqlite":
        saved["source_db_sha256"] = "different"
    with pytest.raises(ValueError, match=expected):
        _verify(saved, snapshot)
