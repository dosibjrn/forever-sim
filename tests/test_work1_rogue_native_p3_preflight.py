"""Work1 regression: native Rogue P3 scoring survives legacy bounded policy search."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.wf_gate_p3_live import (
    _native_p3_equipped_slot_proposals,
    run_live,
)


def test_native_option_proposals_use_rust_ids_and_request_slot_aliases():
    source = {"items": [
        {"slot": "one_hand", "item_id": 11, "item_level": 4},
        {"slot": "main_hand", "item_id": 12, "item_level": 8},
        {"slot": "off_hand", "item_id": 13, "item_level": 2},
        {"slot": "finger", "item_id": 14, "item_level": 3},
        {"slot": "finger", "item_id": 15, "item_level": 7},
        {"slot": "unsupported_request_slot", "item_id": 16, "item_level": 9},
    ]}
    selection = _native_p3_equipped_slot_proposals(source)["slots"]
    assert selection["weapon"]["selected_ids"] == [12, 11]
    assert selection["offhand"]["selected_ids"] == [13]
    assert selection["ring1"]["selected_ids"] == [15, 14]
    assert selection["ring2"]["selected_ids"] == [15, 14]
    assert "unsupported_request_slot" not in selection


def test_rogue_native_paid_probe_runs_even_when_legacy_policy_is_bounded(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/native")
    monkeypatch.setenv(
        "FOREVER_P3_NATIVE_ROGUE_REQUEST",
        "integrations/mythicsim-rust/fixtures/rogue-l20-p3-native.request.json",
    )
    ir = SimpleNamespace(
        actor=SimpleNamespace(metadata={}, base_stats={}),
        actions=(), auto_attacks=(),
    )
    bounded = {
        "status": "EVALUATED_BOUNDED", "attempted": 12, "evaluated": 7,
        "stages": [{
            "stage": "source_naked", "winner": None,
            "search_backend": "prefix", "search_status": "EVALUATED_BOUNDED",
            "attempted": 12, "evaluated": 7, "blocked": 5,
        }],
        "sensitivity_history": [],
    }
    native_options = {
        "items": [{"slot": "one_hand", "item_id": 24071, "item_level": 20}],
    }
    paid_calls = []

    def native_probe(_root, binary, selection, remaining):
        paid_calls.append((binary, selection, remaining))
        return {
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
            "actor_checkpoint_verified": True,
            "comparison": {"baseline_dps": 4.0, "equipped_dps": 33.0,
                           "delta_dps": 29.0},
        }

    with (
        patch("src.game.native_p3_item_options.query_native_p3_item_options",
              return_value=native_options),
        patch("src.game.data.forever.registry.build_game_ir_slice",
              return_value=ir),
        patch("tools.wf_gate_p3_live._source_profile_build_ir",
              return_value=(ir, {"profile": "unrestricted"})),
        patch("src.v2.source_budgeted_gear.run_source_budgeted_gear",
              return_value=bounded) as legacy_search,
        patch("tools.wf_gate_p3_live._paid_native_equipped_probe",
              side_effect=native_probe),
    ):
        result = run_live(Path("."), "rogue", 20, spec="unrestricted")

    assert len(paid_calls) == 1
    assert paid_calls[0] == (
        "/selected/native", {"slots": {
            "weapon": {"selected_ids": [24071]},
        }}, 18,
    )
    assert legacy_search.call_args.kwargs["max_evaluations"] == 26
    assert result["status"] == "BLOCKED"  # No unearned gate PASS.
    assert result["reasons"] == [
        "P3_PRODUCTION_SEARCH_OR_MEASURED_WEIGHT_CONTEXT_UNAVAILABLE:EVALUATED_BOUNDED"
    ]
    assert result["native_equipped_paid_receipt"]["comparison"]["delta_dps"] == 29.0
    assert result["native_equipped_paid_attempts"] == 2
    assert result["p3_shared_budget_attempts"] == 14
    assert result["p3_native_pair_reserved_attempts"] == 18
