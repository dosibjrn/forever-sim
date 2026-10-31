"""Conservative scalar summaries of actual fixed-build 100mob stat interventions.

The raw probes are the evidence. Return no scalar when discrete thresholds,
survival or unsupported effects make a derivative unjustifiable.
"""
from collections import defaultdict
from math import isfinite

def summarize_causal_probes(evidence):
    if evidence.get('method')!='one_axis_at_a_time_source_ir_100mob_intervention_conditional_recovery':
        raise ValueError('P3_CAUSAL_SOURCE_METHOD_MISMATCH')
    groups=defaultdict(list)
    for row in evidence['results']:
        groups[row['stat']].append(row)
    out={}
    for stat,rows in sorted(groups.items()):
        good=[r for r in rows if r['status']=='COMPLETE']
        slopes=[float(r['marginal_s_saved_per_mob_per_raw_unit']) for r in good]
        if len(good)!=len(rows) or len(rows)<2:
            status='UNRESOLVED_OR_SURVIVAL_DISCONTINUITY';weight=None
        elif not all(isfinite(x) for x in slopes):
            status='INVALID_NONFINITE_CAUSAL_PROBE';weight=None
        elif max(abs(x) for x in slopes)<1e-10:
            status='OBSERVED_ZERO_ONLY_IN_TESTED_RANGE';weight=0.
        elif (max(slopes)>0 and min(slopes)<0) or (
            max(slopes)-min(slopes)>0.25*max(abs(x) for x in slopes)):
            status='NONLINEAR_DISCRETE_RANGE_NO_SINGLE_WEIGHT';weight=None
        else:
            status='CONSISTENT_CONTROLLED_100MOB_LOCAL_WEIGHT'
            weight=sum(slopes)/len(slopes)
        out[stat]={'status':status,'weight_s_saved_per_mob_per_raw_unit':weight,
            'probes':rows,'interpretation':'fixed gear+talents+rotation+recovery, not a universal item coefficient'}
    return {'checkpoint':evidence['checkpoint'],'baseline_s_per_mob':evidence['baseline']['mean_s_per_mob'],
        'axes':out,'completed':evidence['completed'],'attempted':evidence['attempted'],
        'no_unknown_to_zero':True,'method':'controlled_100mob_stat_interventions_with_discrete_range_uncertainty'}
