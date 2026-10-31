from copy import deepcopy

import src.rulesets.forever.release_gate as gate


def test_release_gate_covers_all_3x3_production_rows():
    report = gate.build_release_gate()
    assert report["ok"] is True
    assert {(r["class"], r["level"]) for r in report["checks"]} == {
        (cls, level) for cls in ("mage", "paladin", "druid") for level in (20, 40, 60)
    }


def test_release_gate_falsifies_broken_player_facing_rotation(monkeypatch):
    real = gate.fixed_fixture_rows

    def broken(cls):
        rows = deepcopy(real(cls))
        if cls == "mage":
            target = next(r for r in rows if int(r["level"]) == 20)
            target["rotation"] = ""
        return rows

    monkeypatch.setattr(gate, "fixed_fixture_rows", broken)
    report = gate.build_release_gate()
    assert report["ok"] is False
    assert "mage:L20:production_row_contract_failed" in report["failures"]


def test_release_gate_restores_active_game_context():
    from src import game_context
    from src.engine_registry import get_engine, reset_engine_cache

    game_context.configure("classic", "mage")
    reset_engine_cache()
    before = game_context.current()
    gate.build_release_gate()
    after = game_context.current()
    assert after == before
    assert "classic_mage" in get_engine().__name__
