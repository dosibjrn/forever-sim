"""Source-bound spec-profile P2 adapter: no false acceptance by name only."""
from types import SimpleNamespace as N
from unittest.mock import patch

import pytest

from tools import wf_gate_p2_live as p2


def _ir(rule=None):
    # Synthetic source tree: a deep source tier and enough legal-point
    # candidates to inspect adapter bookkeeping without a game fixture.
    # Real talent-selection validation needs sourced rank rows, caps, tree
    # positions and prerequisites; a name/row-only fake hides illegal builds.
    def talent(tid, tree, row, cap=5, prerequisite=None):
        return N(id=tid, tree_key=tree, metadata={"row":row},
                 max_rank=cap, prerequisite=prerequisite,
                 ranks=tuple(N(rank=r, modifiers=(N(kind="stat_pct"),))
                             for r in range(1, cap + 1)))
    talents=[talent(f"source_t{i}", "balance", i % 6) for i in range(10)]
    talents.append(talent("source_capstone", "balance", 6, cap=1,
                          prerequisite={"talent_id":"source_t0",
                                        "required_rank":5}))
    talents.append(talent("source_capstone_peer", "balance", 6))
    talents.append(talent("other_t", "restoration", 0))
    talents.extend(talent(f"other_t{i}", "restoration", 0) for i in range(1, 5))
    return N(talents=tuple(talents),actor=N(metadata={"class_key":"druid"}),
             provenance={"talent_tree_rules":{"points_per_row":5},
                         "source_spec_profile_rules":{} if rule is None
                         else {"balance":rule}})


def _allocation():
    return {**{f"source_t{i}":5 for i in range(10)},
            "source_capstone":1}


def _build_with(builder, spec="balance", rule=None):
    with patch.object(p2,"available_talent_points",return_value=51):
        return p2._source_spec_profile(_ir(rule),spec,level=60,bonus=0,
                                       step=5,source_sha256="a"*64,
                                       frontier_builder=builder)


def test_reject_unknown_or_cross_class_source_tree_without_guessing_aliases():
    def unexpected(*a,**k):
        raise AssertionError("No frontier expected for invalid profile")
    for bad in ("feral-cat","mage","",None,"moonkin"):
        with pytest.raises(ValueError,match="SPEC_PROFILE_NOT_A_SOURCE_TREE"):
            _build_with(unexpected,spec=bad)


def test_existing_source_tree_does_not_self_certify_spec_semantics():
    calls=[]
    def builder(ir,candidates,**kwargs):
        calls.append(kwargs)
        return [_allocation()],{"source":"synthetic_fullpoint_test"}
    population,meta=_build_with(builder)
    assert calls[0]["tree_key"]=="balance"
    assert calls[0]["minimum_points"]==31   # deepest sourced row 6 * 5 + 1
    assert len(population)==1
    assert meta["source_spec_profile_verified"] is False
    assert meta["source_spec_profile_authority"]=="UNVERIFIED_SOURCE_TREE_ONLY"
    assert meta["source_spec_candidate_frontier_exhaustive"] is False
    assert p2._source_spec_rank_witness(population,"source_t0",5)==_allocation()
    assert p2._source_spec_rank_witness(population,"source_t0",4) is None


def test_only_same_class_level_tree_and_sourced_rule_could_verify_profile():
    def builder(ir,candidates,**kwargs):
        return [_allocation()],{}
    rule={"tree_key":"balance","class_key":"druid","level":60,
          "minimum_points":31,"source_url":"https://example.invalid/provenance",
          "source_db_sha256":"a"*64,
          "evidence_status":"VERIFIED_SOURCE_PROFILE"}
    _,confirmed=_build_with(builder,rule=rule)
    assert confirmed["source_spec_profile_verified"] is True
    assert confirmed["source_spec_required_points"]==31
    for mutated in (
        {**rule,"class_key":"mage"},
        {**rule,"level":30},
        {**rule,"tree_key":"restoration"},
        {**rule,"minimum_points":1},
        {**rule,"source_url":"unverified"},
        {**rule,"source_db_sha256":"b"*64},
        {**rule,"evidence_status":"HINT_ONLY"},
    ):
        _,not_proven=_build_with(builder,rule=mutated)
        assert not_proven["source_spec_profile_verified"] is False


def test_bounded_frontier_must_not_forge_full_point_or_tree_membership():
    with pytest.raises(ValueError,match="SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION"):
        _build_with(lambda ir,src,**kw:([{"source_capstone":1}],{}))
    with pytest.raises(ValueError,match="SOURCE_SPEC_FRONTIER_EMPTY"):
        _build_with(lambda ir,src,**kw:([],{}))


def test_unrestricted_profile_is_unchanged_without_invoking_frontier():
    with patch.object(p2,"available_talent_points",side_effect=AssertionError):
        population,meta=p2._source_spec_profile(_ir(),"unrestricted",
                                                level=60,bonus=0,step=5)
    assert population is None
    assert meta["source_spec_profile_verified"] is True
    assert meta["source_spec_tree"] is None


def test_full_budget_frontier_rejects_overrank_even_if_sum_and_tree_match():
    invalid={**_allocation(), "source_t0":6, "source_t1":4}
    assert sum(invalid.values())==51
    with pytest.raises(ValueError,match="SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION"):
        _build_with(lambda ir,src,**kw:([invalid],{}))


def test_full_budget_frontier_rejects_missing_source_prerequisite():
    invalid={**_allocation(), "source_t0":4, "other_t":1}
    assert sum(invalid.values())==51
    with pytest.raises(ValueError,match="SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION"):
        _build_with(lambda ir,src,**kw:([invalid],{}))


def test_full_budget_frontier_rejects_noninteger_rank_even_when_sum_matches():
    invalid={**_allocation(), "source_t0":True, "other_t":4}
    assert sum(invalid.values())==51
    with pytest.raises(ValueError,match="SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION"):
        _build_with(lambda ir,src,**kw:([invalid],{}))


def test_full_budget_frontier_rejects_tier_gate_violation():
    # The named tree still has 31 points, but only 25 are in rows before
    # row six. Five points in another row-six talent cannot unlock that tier.
    invalid={**{f"source_t{i}":5 for i in range(5)},
             "source_capstone":1, "source_capstone_peer":5,
             **{f"other_t{i}":5 for i in range(1, 5)}}
    assert sum(invalid.values())==51
    with pytest.raises(ValueError,match="SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION"):
        _build_with(lambda ir,src,**kw:([invalid],{}))


def test_p2_reuses_exact_legal_full_point_spec_witness_for_unlock():
    """RED on old P2: the unrestricted greedy builder was always called.

    A full-point source/profile candidate has already been validated in the
    P2 spec frontier. Rebuilding it can spuriously fail or lose the profile.
    """
    witness = _allocation()
    target = N(id="source_capstone")
    with patch.object(p2, "available_talent_points", return_value=51), patch(
        "src.v2.source_bounded_joint_frontier._source_unlock_full_point_allocation",
        side_effect=AssertionError("do not rebuild an already validated full spec"),
    ):
        full = p2._full_point_unlock_witness(
            _ir(), target, 1, witness, level=60, bonus=0)
    assert full == witness
    assert full is not witness
    assert sum(full.values()) == 51
    assert sum(v for k, v in full.items() if k.startswith("source_")) >= 31


def test_p2_partial_witness_still_uses_generic_full_point_builder():
    target = N(id="source_capstone")
    partial = {"source_capstone": 1}
    rebuilt = _allocation()
    compiled = _ir()
    with patch.object(p2, "available_talent_points", return_value=51), patch(
        "src.v2.source_bounded_joint_frontier._source_unlock_full_point_allocation",
        return_value=rebuilt,
    ) as builder:
        full = p2._full_point_unlock_witness(
            compiled, target, 1, partial, level=60, bonus=0)
    assert full == rebuilt
    builder.assert_called_once_with(
        compiled, target, level=60, bonus_talent_points=0, target_rank=1)


def test_spec_rank_probe_uses_legal_partial_effect_control_but_full_search_candidate():
    """A 51-point profile may have no legal 50-point predecessor in that profile.

    Behavioral comparison can use an independently legal smaller allocation;
    actual search reachability is the validated full-point optimizer candidate.
    Never call unrestricted neighbors on an out-of-profile predecessor.
    """
    full = _allocation()
    isolated = {"source_t0": 5, "source_capstone": 1}
    modifier = N(kind="stat_pct", target_type="actor", target_id="intellect",
                 value=0.1, provenance={})
    talent = N(id="source_capstone",
               ranks=(N(rank=1, modifiers=(modifier,)),))
    compiled = _ir()
    receipt = N(applied_modifiers=[{"talent_id": "source_capstone", "rank": 1}])
    with patch.object(p2, "available_talent_points", return_value=51), patch.object(
        p2, "_witness", return_value=isolated
    ), patch.object(p2, "validate_talent_selection"), patch.object(
        p2, "apply_talent_selection", return_value=(compiled, receipt)
    ), patch.object(p2, "_effect_change", return_value=True), patch.object(
        p2, "_behavior_fixtures", return_value=([{"actually_executed": True, "passed": True}], [])
    ), patch.object(p2, "replace", side_effect=lambda mod, **kw: mod), patch.object(
        p2, "source_legal_talent_neighbors",
        side_effect=AssertionError("must not use out-of-profile predecessor"),
    ):
        result = p2._rank_probe(compiled, talent, 1, full, level=60,
                                bonus=0, profile_tree="balance")
    assert result["status"] == "PASS"
    assert result["witness"] == isolated
    assert result["search_witness"] == full
    assert result["search_reachable"] is True


def test_unrestricted_rank_probe_still_checks_real_neighbor_reachability():
    """A legal applied rank alone must not mark an unrestricted search PASS."""
    modifier = N(kind="stat_pct", target_type="actor", target_id="intellect",
                 value=0.1, provenance={})
    talent = N(id="source_capstone",
               ranks=(N(rank=1, modifiers=(modifier,)),))
    compiled = _ir()
    receipt = N(applied_modifiers=[{"talent_id": "source_capstone", "rank": 1}])
    with patch.object(p2, "available_talent_points", return_value=51), patch.object(
        p2, "_executable_filler_witness", return_value=None
    ), patch.object(p2, "apply_talent_selection", return_value=(compiled, receipt)
    ), patch.object(p2, "_effect_change", return_value=True), patch.object(
        p2, "_behavior_fixtures", return_value=([], [])
    ), patch.object(p2, "replace", side_effect=lambda mod, **kw: mod), patch.object(
        p2, "source_legal_talent_neighbors", return_value={"neighbors": ()}
    ) as neighbors:
        result = p2._rank_probe(compiled, talent, 1, {"source_capstone": 1},
                                level=60, bonus=0)
    neighbors.assert_called_once()
    assert result["status"] == "FAIL"
    assert result["search_reachable"] is False
    assert "SEARCH_RANK_NOT_GENERATED" in result["reasons"]
