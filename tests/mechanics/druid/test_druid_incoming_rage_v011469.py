import math

from src.rulesets.forever.classes.druid import mechanics
from src.rulesets.forever.classes.druid.rage import (
    CMANGOS_COMMIT,
    incoming_damage_rage_per_second,
    rage_conversion,
    rage_from_damage_taken,
)
from src.rulesets.forever.classes.druid.talents import Talents
from src.rulesets.forever.fidelity import issues_for


def test_pinned_classic_reward_rage_formula_matches_reference_equation():
    level = 20
    expected_conversion = 0.0091107836 * level * level + 3.225598133 * level + 4.2652911
    assert math.isclose(rage_conversion(level), expected_conversion, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(rage_from_damage_taken(level, 100.0), 100.0 / expected_conversion * 2.5, rel_tol=0, abs_tol=1e-12)
    assert incoming_damage_rage_per_second(level, 37.5) > 0
    assert CMANGOS_COMMIT == "8ec338a1704e7dcb1c0213eb7ed58f9231ade40f"


def test_bear_pack_credits_incoming_rage_and_exposes_provenance():
    row = mechanics._bear_pack(40, Talents(), 3)
    assert row["incoming_damage_rage_rate_proxy"] > 0
    assert row["rage_rate_proxy"] > row["base_rage_rate_proxy"]
    assert row["incoming_damage_rage_provenance"]["status"] == "forever_source_backed_fixed_armor_rule"
    assert row["incoming_damage_rage_provenance"]["commit"] == CMANGOS_COMMIT


def test_incoming_rage_increases_or_preserves_bear_pack_throughput(monkeypatch):
    with_rage = mechanics._bear_pack(40, Talents(), 3)
    monkeypatch.setattr(mechanics, "incoming_damage_rage_per_second", lambda level, dps, **kwargs: 0.0)
    without_rage = mechanics._bear_pack(40, Talents(), 3)
    assert with_rage["mobs_per_hour"] >= without_rage["mobs_per_hour"]
    assert with_rage["rage_rate_proxy"] > without_rage["rage_rate_proxy"]


def test_incoming_rage_fidelity_is_explicit_profile_proxy_until_forever_verified():
    rows = {x.issue_id: x for x in issues_for("druid")}
    row = rows["druid.incoming_damage_rage"]
    assert row.status == "partial"
    assert row.severity == "low"
    assert "Blizzard states Forever" in row.summary
