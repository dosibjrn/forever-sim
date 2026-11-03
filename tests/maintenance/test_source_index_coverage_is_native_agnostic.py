"""The source-index inventory must not consume Forever acquisition proof data."""
from __future__ import annotations

import shutil
import sqlite3

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
from src.game.data.forever.sqlite_talents import DEFAULT_DB


def test_indexed_action_inventory_is_independent_of_acquisition_ledgers(tmp_path):
    staged = tmp_path / "without_acquisition_ledgers.sqlite"
    shutil.copy2(DEFAULT_DB, staged)
    with sqlite3.connect(staged) as db:
        db.execute("DROP TABLE IF EXISTS ability_acquisition_entities")
        db.execute("DROP TABLE IF EXISTS ability_acquisition_evidence")

    ir = build_game_ir_slice(
        class_key="druid", level=20, ability_db_path=staged,
    )
    report = indexed_ability_coverage(
        ir, class_key="druid", level=20, db_path=staged,
    )

    assert report["records"]
    retired_fields = {
        "acquisition_evidence_status",
        "acquisition_methods_observed",
        "world_acquisition_verified",
        "typed_index_acquisition",
    }
    assert all(not retired_fields.intersection(record)
               for record in report["records"])
    matched = next(
        record for record in report["records"]
        if record["matched_action_ids"] and not record.get("verified_source_quarantine")
    )
    assert matched["status"] == "SOURCE_ID_MATCHES_IR_ACTION"
    assert report["not_proof_of_legal_action_coverage"] is True
