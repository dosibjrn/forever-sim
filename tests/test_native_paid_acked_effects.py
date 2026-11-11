"""Only genuinely 2D-ACKed Rust damage effects enter the report event clock."""
from __future__ import annotations

import runpy
from pathlib import Path


def _collect():
    # This existing integration path has a hyphen; avoid registering a fake package.
    runner = (Path(__file__).resolve().parents[1] /
              "integrations" / "mythicsim-rust" / "live_two_world_pulls.py")
    return runpy.run_path(str(runner))["accumulate_acked_native_source_effects"]


def test_acked_effect_trace_excludes_unacked_and_preserves_caster_and_clock():
    accumulate = _collect()
    counts = {}
    events = []
    source = {"native_damage_events": [
        {"event_id": "e1", "source_action_id": "SourceShadow123",
         "native_caster_type": "player", "damage": 47.5,
         "periodic": True, "native_target_index": 0},
        {"event_id": "e2", "source_action_id": "SourcePetAttack",
         "native_caster_type": "pet", "damage": 99,
         "periodic": False, "native_target_index": 1},
    ]}
    accumulate(counts, source, {"applied_event_ids": ["e1"]},
               observations=events, clock_ns=2_500_000_000)
    assert counts == {"player": {"SourceShadow123": 1}}
    assert len(events) == 1
    assert events[0] == {
        "clock_ns": 2_500_000_000, "source_action_id": "SourceShadow123",
        "native_caster_type": "player", "source_damage": 47.5,
        "periodic": True, "native_target_index": 0, "event_id": "e1",
    }


def test_acked_effect_trace_keeps_legacy_counts_and_ignores_untyped_damage():
    accumulate = _collect()
    counts, events = {}, []
    source = {"native_damage_events": [
        {"event_id": "e1", "source_action_id": "a",
         "native_caster_type": "pet", "damage": "42"},
    ]}
    accumulate(counts, source, {"applied_event_ids": ["e1"]},
               observations=events, clock_ns=123)
    assert counts == {"pet": {"a": 1}}
    assert events == []
    # Old callers only supplying positional arguments keep the same behavior.
    accumulate(counts, source, {"applied_event_ids": ["e1"]})
    assert counts == {"pet": {"a": 2}}
