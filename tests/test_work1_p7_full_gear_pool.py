"""Work1 #7: production P7 gear pool must not truncate source-admitted items.

Focused real candidate_pool() unit with a small SQLite catalogue. This does not
certify an exhaustive Forever source, item-effect parity or a full P7 gate.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import sqlite3
from types import SimpleNamespace


def test_full_source_gear_pool_keeps_admitted_items_below_top_80(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust"
    monkeypatch.syspath_prepend(str(source))
    gear = importlib.import_module("p74_gear_search")

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        con.execute(
            "CREATE TABLE items (item_id INTEGER, slot TEXT, spell_power REAL, "
            "intellect REAL, hit REAL, crit REAL, spirit REAL)"
        )
        source_slots = {
            name for slot in gear.SLOTS
            for name in gear.SOURCE_SLOTS.get(slot, (slot,))
        }
        for idx, slot in enumerate(sorted(source_slots), 1):
            con.execute(
                "INSERT INTO items VALUES (?, ?, 1, 0, 0, 0, 0)",
                (idx, slot),
            )
        # All 85 deliberately lower-ranked head items are admitted by the
        # same validator; the old full-search top-80 rule hid some forever.
        for idx in range(85):
            con.execute(
                "INSERT INTO items VALUES (?, 'head', ?, 0, 0, 0, 0)",
                (10000 + idx, float(idx + 2)),
            )
        admitted = []
        def accept(slot_index, item_id):
            admitted.append((slot_index, item_id))
        validator = SimpleNamespace(connection=con, item=accept)
        bounded, _ = gear.candidate_pool(validator, limit=80)
        complete, _ = gear.candidate_pool(validator, limit=None)
        assert len(bounded[0]) == 80
        assert len(complete[0]) == 86
        assert set(bounded[0]) < set(complete[0])
        assert len(set(complete[0]) - set(bounded[0])) == 6
        assert set(complete) == set(range(len(gear.SLOTS)))
        assert all(complete[slot] for slot in complete)
        assert len(admitted) >= 86
    finally:
        con.close()
