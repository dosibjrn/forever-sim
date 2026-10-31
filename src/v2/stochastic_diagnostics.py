from __future__ import annotations

"""Diagnostics for the frozen v1 stochastic scorer.

The v1 simulator is useful as an independent stochastic oracle, but a finite
sample is not ground truth.  This module measures the properties that matter
when an optimizer searches many candidates:

* reported standard error vs empirical seed-to-seed variation;
* rank/top-k stability under reseeding;
* winner's-curse / selection optimism after selecting on a short run;
* one-point talent deltas using paired-seed blocks vs independent blocks;
* analytic-v2 ranking against a much longer, independently seeded reference.

"Paired seed" is deliberately not called strict common-random-numbers (CRN):
two policies/builds can consume different numbers of random draws in v1, so a
shared PRNG seed does not guarantee event-wise alignment.  We measure whether
pairing actually reduces delta variance instead of assuming that it does.
"""

from dataclasses import dataclass, asdict
import math
import random
import statistics
from typing import Iterable, Sequence

from src.engine_registry import eng
from .analytic_scorer import optimize_policy_analytic, score_policy_analytic
from .mechanics_projection import sample_legal_builds, talent_key

EPS = 1e-12


@dataclass(frozen=True)
class Candidate:
    talents: eng.Talents
    policy: eng.Policy
    analytic_s_per_100: float

    @property
    def key(self) -> tuple:
        return talent_key(self.talents), eng.policy_desc(self.policy, 60)


@dataclass(frozen=True)
class Estimate:
    mobs: int
    seed: int
    mean_s_per_mob: float
    stderr_s_per_mob: float

    @property
    def s_per_100(self) -> float:
        return self.mean_s_per_mob * 100.0

    @property
    def se_s_per_100(self) -> float:
        return self.stderr_s_per_mob * 100.0


@dataclass(frozen=True)
class TruthEstimate:
    s_per_100: float
    se_s_per_100: float
    mobs_total: int
    blocks: int


@dataclass(frozen=True)
class PairCase:
    level: int
    tree: str
    talent_a: str
    talent_b: str
    talents_a: eng.Talents
    talents_b: eng.Talents
    policy: eng.Policy


def stochastic_estimate(level: int, talents: eng.Talents, policy: eng.Policy,
                        cfg: eng.SimConfig, *, mobs: int, seed: int) -> Estimate:
    r = eng.simulate_chain(level, talents, policy, cfg, n=int(mobs), seed=int(seed))
    return Estimate(
        mobs=int(mobs), seed=int(seed),
        mean_s_per_mob=float(r['mean_s_per_mob']),
        stderr_s_per_mob=float(r['stderr_s_per_mob']),
    )


def long_reference(level: int, candidate: Candidate, cfg: eng.SimConfig, *,
                   mobs_per_block: int, blocks: int, seed: int) -> TruthEstimate:
    rows = [
        stochastic_estimate(
            level, candidate.talents, candidate.policy, cfg,
            mobs=mobs_per_block, seed=seed + i * 1_000_003,
        )
        for i in range(int(blocks))
    ]
    # Equal-size blocks: mean of means.  Estimate the SE of the pooled mean in
    # two ways and conservatively keep the larger one.  The within-block value
    # uses the simulator's own sample variance; the between-block value catches
    # seed/block heterogeneity.
    mean = statistics.mean(r.mean_s_per_mob for r in rows)
    within = math.sqrt(sum(r.stderr_s_per_mob ** 2 for r in rows)) / max(1, blocks)
    between = (statistics.stdev(r.mean_s_per_mob for r in rows) / math.sqrt(blocks)) if blocks > 1 else 0.0
    se = max(within, between)
    return TruthEstimate(mean * 100.0, se * 100.0, int(mobs_per_block) * int(blocks), int(blocks))


def _rankdata(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        r = (i + j - 1) / 2.0 + 1.0
        for k in order[i:j]:
            ranks[k] = r
        i = j
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        return float('nan')
    ra, rb = _rankdata(a), _rankdata(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den > EPS else float('nan')


def build_candidate_pool(level: int, cfg: eng.SimConfig, *, n: int = 80,
                         seed: int = 1) -> list[Candidate]:
    """Create legal build candidates and freeze one analytic-best policy each.

    Policy choice is frozen before stochastic diagnostics.  This intentionally
    separates scorer noise from policy-search noise and prevents re-optimizing
    on every seed.  The resulting pool is suitable for selection-bias tests.
    """
    raw = sample_legal_builds(level, n=max(n * 2, n + 20), seed=seed)
    rows: list[Candidate] = []
    seen = set()
    for t in raw:
        try:
            p, r = optimize_policy_analytic(level, t, cfg)
        except Exception:
            continue
        key = (talent_key(t), eng.policy_desc(p, level))
        if key in seen:
            continue
        seen.add(key)
        rows.append(Candidate(t, p, float(r['total_s'])))
        if len(rows) >= n:
            break
    rows.sort(key=lambda c: c.analytic_s_per_100)
    return rows


def se_calibration(level: int, candidates: Sequence[Candidate], cfg: eng.SimConfig, *,
                   mobs: int = 100, reps: int = 20, sample_candidates: int = 8,
                   seed: int = 1) -> dict:
    if not candidates:
        return {}
    # Spread probes over the candidate ranking rather than taking only leaders.
    if sample_candidates >= len(candidates):
        idxs = list(range(len(candidates)))
    elif sample_candidates == 1:
        idxs = [0]
    else:
        idxs = sorted(set(round(i * (len(candidates) - 1) / (sample_candidates - 1)) for i in range(sample_candidates)))
    ratios = []
    rows = []
    for j, idx in enumerate(idxs):
        c = candidates[idx]
        est = [
            stochastic_estimate(level, c.talents, c.policy, cfg, mobs=mobs,
                                seed=seed + j * 100_003 + r * 10_007)
            for r in range(reps)
        ]
        empirical_sd = statistics.stdev(x.mean_s_per_mob for x in est) if len(est) > 1 else 0.0
        reported_rms = math.sqrt(statistics.mean(x.stderr_s_per_mob ** 2 for x in est))
        ratio = empirical_sd / reported_rms if reported_rms > EPS else float('nan')
        if math.isfinite(ratio):
            ratios.append(ratio)
        rows.append({
            'candidate_index': idx,
            'analytic_s_per_100': c.analytic_s_per_100,
            'empirical_sd_mean_s_per_mob': empirical_sd,
            'reported_rms_se_s_per_mob': reported_rms,
            'empirical_over_reported': ratio,
        })
    return {
        'mobs': mobs, 'reps': reps, 'candidates_probed': len(rows),
        'median_empirical_over_reported': statistics.median(ratios) if ratios else float('nan'),
        'mean_empirical_over_reported': statistics.mean(ratios) if ratios else float('nan'),
        'rows': rows,
    }


def selection_diagnostics(level: int, candidates: Sequence[Candidate], cfg: eng.SimConfig, *,
                          search_mobs: int = 100, search_reps: int = 12,
                          truth_mobs_per_block: int = 750, truth_blocks: int = 2,
                          top_k: int = 5, seed: int = 1) -> dict:
    if not candidates:
        return {}
    truths = [
        long_reference(level, c, cfg, mobs_per_block=truth_mobs_per_block,
                       blocks=truth_blocks, seed=seed + 10_000_019 + i * 97_003)
        for i, c in enumerate(candidates)
    ]
    truth_scores = [t.s_per_100 for t in truths]
    true_order = sorted(range(len(candidates)), key=lambda i: truth_scores[i])
    true_best = true_order[0]
    truth_rank = {idx: r + 1 for r, idx in enumerate(true_order)}
    true_top = set(true_order[:top_k])

    rep_rows = []
    winner_optimism = []
    winner_regret = []
    winner_z = []
    rho = []
    top_recall = []
    best_in_topk = []
    coverage = []

    for rep in range(search_reps):
        estimates = []
        for i, c in enumerate(candidates):
            # Distinct deterministic seed per candidate/rep: emulates the
            # optimizer seeing one noisy estimate per candidate.
            s = seed + 20_000_033 + rep * 1_000_003 + i * 10_007
            estimates.append(stochastic_estimate(level, c.talents, c.policy, cfg,
                                                mobs=search_mobs, seed=s))
        scores = [e.s_per_100 for e in estimates]
        order = sorted(range(len(candidates)), key=lambda i: scores[i])
        winner = order[0]
        opt = scores[winner] - truth_scores[winner]  # negative => lucky/optimistic
        reg = truth_scores[winner] - truth_scores[true_best]
        comb_se = math.sqrt(estimates[winner].se_s_per_100 ** 2 + truths[winner].se_s_per_100 ** 2)
        z = opt / comb_se if comb_se > EPS else float('nan')
        search_top = set(order[:top_k])
        rec = len(search_top & true_top) / max(1, len(true_top))
        cov = 0
        for i, e in enumerate(estimates):
            se = math.sqrt(e.se_s_per_100 ** 2 + truths[i].se_s_per_100 ** 2)
            if abs(e.s_per_100 - truth_scores[i]) <= 1.96 * se:
                cov += 1
        cov /= len(candidates)

        rr = spearman(scores, truth_scores)
        winner_optimism.append(opt); winner_regret.append(reg); winner_z.append(z)
        rho.append(rr); top_recall.append(rec); best_in_topk.append(true_best in search_top); coverage.append(cov)
        rep_rows.append({
            'rep': rep,
            'winner_index': winner,
            'winner_truth_rank': truth_rank[winner],
            'search_s_per_100': scores[winner],
            'truth_s_per_100': truth_scores[winner],
            'winner_optimism_s_per_100': opt,
            'winner_regret_s_per_100': reg,
            'winner_optimism_z': z,
            'spearman_vs_truth': rr,
            'topk_recall': rec,
            'truth_best_in_search_topk': true_best in search_top,
            'ci95_coverage': cov,
        })

    analytic = [c.analytic_s_per_100 for c in candidates]
    analytic_order = sorted(range(len(candidates)), key=lambda i: analytic[i])
    analytic_top = set(analytic_order[:top_k])
    rel = [abs(a - t) / max(EPS, t) for a, t in zip(analytic, truth_scores)]

    # Extreme-value scale if N independent Gaussian estimates all had the same
    # SE.  This is a diagnostic scale, not a claim that 15M candidates are
    # independent.  NormalDist gives the one-sided quantile directly.
    from statistics import NormalDist
    def extreme_z(n: int) -> float:
        p = max(1e-15, min(0.5, 1.0 / (n + 1.0)))
        return abs(NormalDist().inv_cdf(p))

    median_search_se = statistics.median(
        stochastic_estimate(level, candidates[i].talents, candidates[i].policy, cfg,
                            mobs=search_mobs, seed=seed + 30_000_037 + i * 101).se_s_per_100
        for i in range(min(len(candidates), 12))
    )

    return {
        'level': level,
        'candidate_count': len(candidates),
        'search_mobs': search_mobs,
        'search_reps': search_reps,
        'truth_mobs_per_candidate': truth_mobs_per_block * truth_blocks,
        'truth_blocks': truth_blocks,
        'median_truth_se_s_per_100': statistics.median(t.se_s_per_100 for t in truths),
        'median_short_run_se_s_per_100': median_search_se,
        'mean_winner_optimism_s_per_100': statistics.mean(winner_optimism),
        'median_winner_optimism_s_per_100': statistics.median(winner_optimism),
        'mean_abs_winner_optimism_s_per_100': statistics.mean(abs(x) for x in winner_optimism),
        'mean_winner_optimism_z': statistics.mean(x for x in winner_z if math.isfinite(x)),
        'mean_winner_truth_regret_s_per_100': statistics.mean(winner_regret),
        'median_winner_truth_rank': statistics.median(r['winner_truth_rank'] for r in rep_rows),
        'truth_best_selected_top1_rate': sum(r['winner_truth_rank'] == 1 for r in rep_rows) / len(rep_rows),
        'truth_best_in_search_topk_rate': statistics.mean(best_in_topk),
        'mean_search_truth_spearman': statistics.mean(rho),
        'mean_topk_recall': statistics.mean(top_recall),
        'mean_ci95_coverage': statistics.mean(coverage),
        'analytic_truth_spearman': spearman(analytic, truth_scores),
        'analytic_med_abs_rel_error': statistics.median(rel),
        'analytic_truth_best_rank': analytic_order.index(true_best) + 1,
        'analytic_truth_best_in_topk': true_best in analytic_top,
        'independent_gaussian_extreme_z_pool': extreme_z(len(candidates)),
        'independent_gaussian_extreme_z_15m': extreme_z(15_000_000),
        'independent_gaussian_15m_scale_s_per_100': extreme_z(15_000_000) * median_search_se,
        'truth_scores_s_per_100': truth_scores,
        'truth_se_s_per_100': [t.se_s_per_100 for t in truths],
        'analytic_scores_s_per_100': analytic,
        'rep_rows': rep_rows,
    }


def _random_parent(level: int, tree: str, rng: random.Random) -> eng.Talents | None:
    points = level - 10  # one point short of full allocation at this level
    t = eng.Talents()
    for _ in range(max(0, points)):
        legal = [n for n in eng.TALENT_RULES if eng.legal_add(t, n)]
        preferred = [n for n in legal if eng.TALENT_RULES[n][0] == tree]
        if preferred and rng.random() < 0.9:
            legal = preferred
        if not legal:
            return None
        t = eng.add_point(t, rng.choice(legal))
    return t


def make_one_point_pairs(level: int, *, pairs_per_tree: int = 4,
                         seed: int = 1) -> list[PairCase]:
    rng = random.Random(seed)
    out: list[PairCase] = []
    for tree, primary in [('frost', 'frostbolt'), ('fire', 'fireball'), ('arcane', 'arcane_missiles')]:
        made = attempts = 0
        while made < pairs_per_tree and attempts < 3000:
            attempts += 1
            parent = _random_parent(level, tree, rng)
            if parent is None:
                continue
            p = eng.Policy(f'pair-{primary}', primary, use_fireblast=False, use_nova=False, use_blink=False)
            adds = [
                n for n in eng.TALENT_RULES
                if eng.legal_add(parent, n)
                and eng.TALENT_RULES[n][0] == tree
                and eng.talent_directly_affects_policy(n, p, level)
            ]
            if len(adds) < 2:
                continue
            a_name, b_name = rng.sample(adds, 2)
            out.append(PairCase(level, tree, a_name, b_name,
                                eng.add_point(parent, a_name), eng.add_point(parent, b_name), p))
            made += 1
    return out


def pair_delta_diagnostics(level: int, pairs: Sequence[PairCase], cfg: eng.SimConfig, *,
                           block_mobs: int = 100, blocks: int = 12,
                           truth_mobs_per_block: int = 1000, truth_blocks: int = 2,
                           seed: int = 1) -> dict:
    rows = []
    for j, pair in enumerate(pairs):
        # Independent long reference for each side.
        ca = Candidate(pair.talents_a, pair.policy,
                       score_policy_analytic(level, pair.talents_a, pair.policy, cfg)['total_s'])
        cb = Candidate(pair.talents_b, pair.policy,
                       score_policy_analytic(level, pair.talents_b, pair.policy, cfg)['total_s'])
        ta = long_reference(level, ca, cfg, mobs_per_block=truth_mobs_per_block,
                            blocks=truth_blocks, seed=seed + 40_000_043 + j * 1_000_003)
        tb = long_reference(level, cb, cfg, mobs_per_block=truth_mobs_per_block,
                            blocks=truth_blocks, seed=seed + 50_000_047 + j * 1_000_003)
        truth_delta = ta.s_per_100 - tb.s_per_100
        analytic_delta = ca.analytic_s_per_100 - cb.analytic_s_per_100

        paired = []
        independent = []
        paired_reported_independent_se = []
        for r in range(blocks):
            shared_seed = seed + 60_000_053 + j * 1_000_003 + r * 10_007
            ea = stochastic_estimate(level, pair.talents_a, pair.policy, cfg,
                                     mobs=block_mobs, seed=shared_seed)
            eb = stochastic_estimate(level, pair.talents_b, pair.policy, cfg,
                                     mobs=block_mobs, seed=shared_seed)
            paired.append(ea.s_per_100 - eb.s_per_100)
            paired_reported_independent_se.append(math.sqrt(ea.se_s_per_100 ** 2 + eb.se_s_per_100 ** 2))

            ia = stochastic_estimate(level, pair.talents_a, pair.policy, cfg,
                                     mobs=block_mobs, seed=seed + 70_000_057 + j * 1_000_003 + r * 20_011)
            ib = stochastic_estimate(level, pair.talents_b, pair.policy, cfg,
                                     mobs=block_mobs, seed=seed + 80_000_069 + j * 1_000_003 + r * 20_011)
            independent.append(ia.s_per_100 - ib.s_per_100)

        psd = statistics.stdev(paired) if len(paired) > 1 else 0.0
        isd = statistics.stdev(independent) if len(independent) > 1 else 0.0
        rows.append({
            'tree': pair.tree,
            'talent_a': pair.talent_a,
            'talent_b': pair.talent_b,
            'analytic_delta_s_per_100': analytic_delta,
            'truth_delta_s_per_100': truth_delta,
            'truth_delta_se_s_per_100': math.sqrt(ta.se_s_per_100 ** 2 + tb.se_s_per_100 ** 2),
            'paired_seed_delta_sd_s_per_100': psd,
            'independent_delta_sd_s_per_100': isd,
            'paired_over_independent_sd': psd / isd if isd > EPS else float('nan'),
            'mean_naive_independent_se_s_per_100': statistics.mean(paired_reported_independent_se),
            'paired_seed_sign_accuracy': statistics.mean((x < 0) == (truth_delta < 0) for x in paired) if abs(truth_delta) > EPS else float('nan'),
            'independent_sign_accuracy': statistics.mean((x < 0) == (truth_delta < 0) for x in independent) if abs(truth_delta) > EPS else float('nan'),
        })

    finite_ratio = [r['paired_over_independent_sd'] for r in rows if math.isfinite(r['paired_over_independent_sd'])]
    nonzero = [r for r in rows if abs(r['truth_delta_s_per_100']) > EPS]
    analytic_sign = statistics.mean(
        (r['analytic_delta_s_per_100'] < 0) == (r['truth_delta_s_per_100'] < 0)
        for r in nonzero
    ) if nonzero else float('nan')
    paired_acc = [r['paired_seed_sign_accuracy'] for r in rows if math.isfinite(r['paired_seed_sign_accuracy'])]
    indep_acc = [r['independent_sign_accuracy'] for r in rows if math.isfinite(r['independent_sign_accuracy'])]
    return {
        'level': level,
        'pairs': len(rows),
        'block_mobs': block_mobs,
        'blocks': blocks,
        'truth_mobs_per_side': truth_mobs_per_block * truth_blocks,
        'analytic_truth_sign_accuracy': analytic_sign,
        'median_paired_over_independent_delta_sd': statistics.median(finite_ratio) if finite_ratio else float('nan'),
        'mean_paired_seed_sign_accuracy': statistics.mean(paired_acc) if paired_acc else float('nan'),
        'mean_independent_sign_accuracy': statistics.mean(indep_acc) if indep_acc else float('nan'),
        'rows': rows,
    }
