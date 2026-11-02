"""Approved P5 twofold paid breadth and verified finite-universe saturation."""

from src.v2.source_paid_cold_comparison import p5_paid_breadth_evidence


def report(n, *, total=None, exhaustive=False):
    return {
        'unique_full_builds': n,
        'source_candidate_universe_exact_size': total,
        'source_candidate_universe_exhaustive': exhaustive,
    }


def test_exact_double_paid_builds_passes():
    got = p5_paid_breadth_evidence(report(25), report(50))
    assert got['p5_2x_or_exhaustion_breadth'] is True
    assert got['p5_breadth_required_unique'] == 50
    assert got['p5_verified_legal_universe_size'] is None


def test_below_double_fails_without_exhaustion():
    got = p5_paid_breadth_evidence(report(25), report(49))
    assert got['p5_2x_or_exhaustion_breadth'] is False


def test_small_verified_legal_universe_caps_breadth():
    got = p5_paid_breadth_evidence(
        report(25, total=42, exhaustive=True),
        report(42, total=42, exhaustive=True))
    assert got['p5_2x_or_exhaustion_breadth'] is True
    assert got['p5_breadth_required_unique'] == 42
    assert got['p5_verified_legal_universe_size'] == 42


def test_finite_universe_requires_all_candidates_not_most():
    got = p5_paid_breadth_evidence(
        report(25, total=42, exhaustive=True),
        report(41, total=42, exhaustive=True))
    assert got['p5_2x_or_exhaustion_breadth'] is False


def test_unproven_or_inconsistent_universe_cannot_lower_target():
    for a, b in (
        (report(25, total=42, exhaustive=False), report(42, total=42, exhaustive=True)),
        (report(25, total=42, exhaustive=True), report(42, total=43, exhaustive=True)),
        (report(25, total=42, exhaustive=True), report(42, total=42, exhaustive=False)),
        (report(25, total=True, exhaustive=True), report(42, total=True, exhaustive=True)),
        (report(25, total=24, exhaustive=True), report(42, total=24, exhaustive=True)),
    ):
        got = p5_paid_breadth_evidence(a, b)
        assert got['p5_2x_or_exhaustion_breadth'] is False
        assert got['p5_breadth_required_unique'] == 50
        assert got['p5_verified_legal_universe_size'] is None


def test_zero_baseline_never_passes_even_if_universe_is_capped():
    got = p5_paid_breadth_evidence(
        report(0, total=3, exhaustive=True), report(3, total=3, exhaustive=True))
    assert got['p5_2x_or_exhaustion_breadth'] is False
