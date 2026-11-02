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
        # All 85 additional head items are admitted by the
        # same validator; the old full-search top-80 rule hid six forever.
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


def test_explicit_unenchanted_candidate_does_not_inherit_saved_enchant(monkeypatch):
    """Actual P7.4/P7.5 GearValidator.validate must check what Rust will run.

    A candidate with no enchant serializes without an enchant field; the
    saved reference's enchant must not be silently substituted by the
    source/native legality validator. Omitted `enchants` still intentionally
    retains the historical reference-default validation contract.
    """
    import pytest

    source = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust"
    monkeypatch.syspath_prepend(str(source))
    gear = importlib.import_module("p74_gear_validation")
    validator = object.__new__(gear.GearValidator)
    validator.ref_items = [{"enchant": 7777}] + [{} for _ in range(15)]
    paid = []

    def item(index, item_id, enchant_id=None):
        paid.append((index, item_id, enchant_id))
        if index == 0 and enchant_id != 0:
            raise gear.RejectedGear(
                "engine_enchant_missing",
                "Saved reference enchant is unavailable for this cold item")
        return {"limit_category": 0}

    validator.item = item
    ids = list(range(101, 117))
    # P7.4/P7.5 pass explicit None for an unenchanted cold slot.
    validator.validate(ids, [None] * 16)
    assert paid == [(i, ids[i], 0) for i in range(16)]

    # Legacy callers omitting the entire enchant vector still use the saved
    # reference enchant; this intentionally remains a distinct API mode.
    with pytest.raises(gear.RejectedGear, match="Saved reference enchant"):
        validator.validate(ids)


def test_source_enchant_pool_checks_no_enchant_as_zero(monkeypatch):
    """The native source-enchant discovery must not interpret None as saved."""
    source = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust"
    monkeypatch.syspath_prepend(str(source))
    gear = importlib.import_module("p74_gear_search")
    seen = []

    def item(slot, item_id, enchant_id=None):
        seen.append((slot, item_id, enchant_id))
        if enchant_id is None:
            raise gear.RejectedGear(
                "engine_enchant_missing", "No enchant is not saved enchant")

    validator = SimpleNamespace(enchants={401: {}}, item=item)
    options = gear.source_enchant_pools(validator, {0: [101]})
    assert options == {0: [None, 401]}
    assert seen == [(0, 101, 0), (0, 101, 401)]
