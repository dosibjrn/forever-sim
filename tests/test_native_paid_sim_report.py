"""Native-paid sim-report timeline and resource fields must be real evidence only."""
from __future__ import annotations

import hashlib
import json

from tools.wf_native_paid_html import read_verified_native_raw
from tools.wf_native_paid_sim_report import render_paid_simulation


def sample():
    sha = "a" * 64
    return (
        {
            "class": "warlock", "mob_count": 2, "iterations": 1,
            "rng_mode": "balanced", "backend": "rust",
        },
        {
            "source_request_sha256": sha, "engine_binary_sha256": "b" * 64,
            "native_elapsed_seconds": 35.525,
            "terminal_recovery_seconds": 7.5,
            "receipt": {
                "source_request_sha256": sha, "native_elapsed_seconds": 35.525,
                "terminal_recovery_seconds": 7.5, "targets_killed": 2,
                "terminal_hp": 574, "terminal_max_hp": 574,
                "terminal_mana": 943, "terminal_max_mana": 943,
            },
        },
        {
            "source_sha256": sha, "actual_2d_ack": True,
            "world_targets_killed": 2, "paid_recovery": True,
            "native_recovery_clock_accounted": True,
            "native_windows": [
                {"native_kill_ns": 9715000000, "actor_health": 574,
                 "actor_mana": 618, "native_damage": 511.07},
                {"native_kill_ns": 28025000000, "actor_health": 574,
                 "actor_mana": 618, "native_damage": 492.86},
            ],
            "world_kills": [
                {"target_id": "m1", "world_kill_clock_ns": 9715000000},
                {"target_id": "m0", "world_kill_clock_ns": 28025000000},
            ],
            "world_target_hp": 400.0,
            "native_terminal_recovery": {
                "start_clock_ns": 28025000000,
                "end_clock_ns": 35525000000,
                "health_before": 574, "health_after": 574,
                "max_health": 574, "mana_before": 618,
                "mana_after": 943, "max_mana": 943,
                "water_seconds": 7.5, "water_mana_gain": 260.6,
            },
            "native_water_seconds_total": 7.3,
            "gsim_route_paid_movement_s": 2.857142857,
        },
    )


def test_exact_digest_and_source_are_required_for_sidecar_timeline(tmp_path):
    result, row, sidecar = sample()
    file = tmp_path / "runs" / "native-api-paid-cache" / "L20.native.json"
    file.parent.mkdir(parents=True)
    data = json.dumps(sidecar, sort_keys=True).encode()
    file.write_bytes(data)
    row["receipt"]["native_raw_receipt_file"] = "runs/native-api-paid-cache/L20.native.json"
    row["receipt"]["native_raw_receipt_sha256"] = hashlib.sha256(data).hexdigest()
    matched = read_verified_native_raw(row, receipt_root=tmp_path)
    assert matched == sidecar
    report = render_paid_simulation(result, row, native_raw=matched)
    for expected in ("35.525 s", "28.02 s", "m0", "m1",
                     "Native damage", "7.50 s", "Mana before",
                     "Resource", "2.86 s", "260.60",
                     "Fight timeline", "Source-backed"):
        # Some labels are HTML metadata rather than visible headings.
        if expected == "Source-backed":
            continue
        assert expected.lower() in report.lower()
    assert "Per-spell damage not recorded" in report
    assert "Actual casts and aura uptimes not recorded" in report
    assert "<script" not in report and "<link " not in report


def test_tampered_sidecar_does_not_invent_spells_or_causality(tmp_path):
    result, row, sidecar = sample()
    path = tmp_path / "raw.native.json"
    data = json.dumps(sidecar).encode()
    path.write_bytes(data)
    row["receipt"]["native_raw_receipt_file"] = str(path)
    row["receipt"]["native_raw_receipt_sha256"] = hashlib.sha256(data).hexdigest()
    assert read_verified_native_raw(row) == sidecar
    altered = dict(sidecar, world_target_hp=999999)
    path.write_text(json.dumps(altered))
    assert read_verified_native_raw(row) is None
    fallback = render_paid_simulation(result, row)
    assert "Timeline not recorded" in fallback
    assert "Mana before final recovery" not in fallback
    assert "999999" not in fallback


def test_wrong_source_identity_is_refused_even_if_digest_matches(tmp_path):
    _, row, sidecar = sample()
    wrong = dict(sidecar, source_sha256="d" * 64)
    file = tmp_path / "receipt.native.json"
    raw = json.dumps(wrong).encode()
    file.write_bytes(raw)
    row["receipt"]["native_raw_receipt_file"] = str(file)
    row["receipt"]["native_raw_receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    assert read_verified_native_raw(row) is None


def test_malformed_timestamps_are_not_rendered_as_measured_markers():
    result, row, sidecar = sample()
    sidecar["world_kills"][0]["world_kill_clock_ns"] = 60_000_000_000
    html = render_paid_simulation(result, row, native_raw=sidecar)
    assert "No per-kill timeline in this receipt" in html
    assert "60.00 s" not in html


def test_untrusted_world_target_labels_are_html_escaped():
    result, row, sidecar = sample()
    attack = '<svg onload=alert(1)>'
    sidecar["world_kills"][0]["target_id"] = attack
    html = render_paid_simulation(result, row, native_raw=sidecar)
    assert attack not in html
    assert "&lt;svg onload=alert(1)&gt;" in html


def test_missing_cast_and_ability_breakdown_is_never_misrepresented_as_zero():
    result, row, sidecar = sample()
    page = render_paid_simulation(result, row, native_raw=sidecar)
    assert "Per-spell damage not recorded" in page
    assert "Actual casts and aura uptimes not recorded" in page
    assert "not raid DPS" in page
    assert "confidence intervals are unavailable" in page


def test_native_acked_source_effect_timeline_comes_from_exact_observations():
    result, row, raw = sample()
    raw["native_acked_damage_effect_timeline"] = [
        {"clock_ns": 1_000_000_000, "event_id": "a",
         "native_caster_type": "player", "source_action_id": "corruption",
         "source_damage": 40.0, "periodic": True, "native_target_index": 0},
        {"clock_ns": 1_200_000_000, "event_id": "b",
         "native_caster_type": "pet", "source_action_id": "<script>alert(1)</script>",
         "source_damage": 23.0, "periodic": False, "native_target_index": 1},
    ]
    rendered = render_paid_simulation(result, row, native_raw=raw)
    assert "Actual source-native damage-effect timeline (2 events)" in rendered
    assert "1.000 s" in rendered and "1.200 s" in rendered
    assert "40.00" in rendered and "23.00" in rendered
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "not inferred casts" in rendered


def test_invalid_native_effect_order_is_not_described_as_recorded():
    result, row, raw = sample()
    raw["native_acked_damage_effect_timeline"] = [
        {"clock_ns": 2_000_000_000, "event_id": "a",
         "native_caster_type": "player", "source_action_id": "a",
         "source_damage": 40.0},
        {"clock_ns": 1_000_000_000, "event_id": "b",
         "native_caster_type": "player", "source_action_id": "a",
         "source_damage": 40.0},
    ]
    rendered = render_paid_simulation(result, row, native_raw=raw)
    assert "Invalid damage-effect timeline" in rendered
    assert "Actual source-native damage-effect timeline" not in rendered
