"""Regression guard: optimization uses balanced RNG; frozen acceptance stays stochastic.

This protects the owner-approved P7 contract without running expensive gates.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_live_p7_candidate_and_finalist_scoring_never_uses_stochastic_rng():
    for gate in ("p7_2", "p7_3", "p7_4", "p7_5"):
        source = _source(f"tools/wf_gate_{gate}_live.py")
        marker = ("    if full_search and search_wall_s >= 300.0:"
                  if gate == "p7_2" else "    complete_search =")
        search, separator, frozen = source.partition(marker)
        assert separator, gate
        assert 'rng_mode="stochastic"' not in search, gate
        assert '"search_rng_mode": "balanced"' in frozen, gate
        assert 'rng_mode="stochastic"' in frozen, gate  # frozen 1k only


def test_native_optimizer_entry_points_use_balanced_rng():
    rotation = _source("integrations/mythicsim-rust/rotation_search.py")
    assert 'rng_mode="balanced", deadline=None' in rotation
    assert '"frozen_stochastic_holdout",rng_mode="stochastic"' in rotation

    talents = _source("integrations/mythicsim-rust/p73_talent_search_v2.py")
    assert "choices=('balanced',),default='balanced'" in talents
    assert "run(a.binary,requested,24,rerank_seed,'balanced',rerank_end)" in talents
    assert "run(a.binary,winner,a.holdout_iterations,holdout_seed,'stochastic',deadline)" in talents

    gear = _source("integrations/mythicsim-rust/p74_gear_search.py")
    assert 'simulate(a.binary,req,"balanced",24,search_seed+555123,rerank_end)' in gear
    assert 'simulate(a.binary,req,"stochastic",a.holdout_iterations' in gear

    unrestricted = _source("integrations/mythicsim-rust/p75_unrestricted_search.py")
    search, separator, frozen = unrestricted.partition(
        '    holdout,output,_,_=run(')
    assert separator
    assert 'run(a.binary,q,a.screen_iterations,seed,"balanced",end_screen)' in search
    assert 'run(a.binary,q,24,seed+554433,"balanced",end_screen)' in search
    assert 'run(a.binary,q,24,seed+100005,"balanced",end_rerank)' in search
    assert 'run(a.binary,q,' not in search.replace(
        'run(a.binary,q,a.screen_iterations,seed,"balanced",end_screen)', '').replace(
        'run(a.binary,q,24,seed+554433,"balanced",end_screen)', '').replace(
        'run(a.binary,q,24,seed+100005,"balanced",end_rerank)', '')
    assert '"stochastic_fallback"' not in search
    assert '"stochastic",deadline)' in frozen
