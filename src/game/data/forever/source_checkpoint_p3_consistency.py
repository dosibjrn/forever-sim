"""Independent, build-bound adversarial validation of scalar stat weights.

A one-point finite difference is evidence for that exact perturbation only.
It is NOT a safe additive gear-ranking coefficient in a discontinuous combat
runtime unless nearby, item-relevant perturbations behave consistently.

No game-specific stat-to-effect coefficients or hard-coded item IDs live here.
"""
from __future__ import annotations
from math import isfinite
from .source_checkpoint_p3_weights import PROBE_STEPS

CRITICAL_COARSE_AXES = frozenset({'agility', 'weapon_dps'})


def audit_stat_weight_curves(*, report, curves, slope_ratio_limit=4.0,
                             impact_floor_s_per_mob=0.005):
    """Reject unsupported extrapolation and preserve every observed point.

    `curves` has a source-build key and 100-mob deltas with absolute scores.
    A negative improvement is *not* removed or replaced with a zero.
    All quantified scores come from full 100-mob CombatRuntime evaluations.
    """
    weight_context=report['stat_weights']
    base=float(weight_context['base_s_per_mob'])
    failures=[];rows={}
    if curves.get('build_identity_sha256') != report.get('build_identity_sha256'):
        failures.append('AUDIT_WRONG_BUILD_IDENTITY')
    if curves.get('catalogue_sha256') != report.get('catalogue_sha256'):
        failures.append('AUDIT_WRONG_CATALOGUE')
    if curves.get('mobs') != 100 or abs(float(curves.get('base_s_per_mob', float('nan')))-base)>1e-8:
        failures.append('AUDIT_NOT_SAME_100MOB_OBJECTIVE')
    for stat,data in curves.get('axes',{}).items():
        points=data.get('probes',[])
        valid=[]
        for x in points:
            delta=float(x['delta']); score=float(x['s_per_mob'])
            if delta==0 or not isfinite(delta) or not isfinite(score) or x.get('status')!='COMPLETE':
                failures.append('INVALID_MULTISCALE_SAMPLE:'+stat);continue
            valid.append({'delta':delta,'s_per_mob':score,'improvement_s_per_mob':base-score,
                          'slope_s_saved_per_mob_per_unit':(base-score)/delta})
        positive=sorted((x for x in valid if x['delta']>0),key=lambda x:x['delta'])
        negative=[x for x in valid if x['delta']<0]
        issues=[]
        if len(positive)<2:issues.append('INSUFFICIENT_POSITIVE_STEPS')
        if stat in CRITICAL_COARSE_AXES:
            required=float(PROBE_STEPS[stat])
            adequate=[x for x in positive if x['delta']>=required]
            if len(adequate)<2 or max((x['delta'] for x in adequate),default=0.)<2*required:
                issues.append('NO_TWO_ITEM_RELEVANT_COARSE_STEPS')
            # Tiny deltas are retained as evidence, but cannot qualify a
            # ranking coefficient for these threshold-sensitive axes.
        if any(x['improvement_s_per_mob'] < -impact_floor_s_per_mob for x in positive):
            issues.append('ADVERSE_POSITIVE_STAT_PERTURBATION')
        significant=[x for x in positive if x['improvement_s_per_mob']>impact_floor_s_per_mob]
        if len(significant)>1:
            slopes=[x['slope_s_saved_per_mob_per_unit'] for x in significant]
            ratio=max(slopes)/min(slopes)
            if ratio>slope_ratio_limit:issues.append('NONLINEAR_SLOPE_EXTRAPOLATION_UNSAFE')
        # A larger positive stat bonus that makes results worse than a smaller
        # one also defeats a monotone marginal weight, even if both are positive.
        for a,b in zip(positive,positive[1:]):
            if b['improvement_s_per_mob']+impact_floor_s_per_mob < a['improvement_s_per_mob']:
                issues.append('NONMONOTONE_POSITIVE_SAMPLES');break
        if negative and significant:
            closest_negative=min(negative,key=lambda x:abs(x['delta']))
            closest_positive=min(significant,key=lambda x:x['delta'])
            if abs(closest_negative['delta']) == closest_positive['delta']:
                down=(closest_negative['s_per_mob']-base)/abs(closest_negative['delta'])
                up=closest_positive['slope_s_saved_per_mob_per_unit']
                if down>0 and max(down,up)/min(down,up)>slope_ratio_limit:
                    issues.append('ASYMMETRIC_ITEM_STAT_THRESHOLD')
        rows[stat]={'issues':sorted(set(issues)),'points':valid,'safe_scalar_weight':not issues,
                    'source_weight_s_saved_per_mob_per_unit':weight_context['weights'].get(stat,{}).get('weight_s_saved_per_mob_per_unit')}
        for issue in sorted(set(issues)):
            failures.append(stat+':'+issue)
    return {'status':'PASS' if not failures else 'FAIL','pass':not failures,'failures':sorted(failures),
            'build_identity_sha256':report.get('build_identity_sha256'),
            'base_s_per_mob':base,'mobs':100,'axes':rows,
            'slope_ratio_limit':slope_ratio_limit,'impact_floor_s_per_mob':impact_floor_s_per_mob,
            'interpretation':'NO_CLAIM_OF_LINEAR_WEIGHT_OUTSIDE_ACTUAL_PROBED_REGION'}
