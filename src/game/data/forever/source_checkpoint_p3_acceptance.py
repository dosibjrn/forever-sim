"""L0 user-contract gear acceptance: source coverage, contextual nontrivial weights,
explained Top 5.  An unknown component is *reported*, never assumed zero.
Do not confuse this P3 gate with complete executable L2 item effects.
"""
from collections import Counter
from math import isfinite


def l0_gear_top5_certificate(report, *, stat_curve_audit=None):
    weights=report['stat_weights']['weights']
    rows=[(slot,part,item) for slot,part in report['slots'].items()
          for item in part['weighted_top']]
    if not rows:raise ValueError('P3_EMPTY_TOP_FIVE_REPORT')
    failures=[]
    if not report.get('p3_pass'):failures.append('INCOMPLETE_LEGAL_L0_UNIVERSE')
    if any(part['available_legal']<1 or len(part['weighted_top'])!=min(5,part['available_legal'])
           for part in report['slots'].values()):failures.append('MISSING_TOP_FIVE_SLOT')
    if any(not item['item_url'] for _,_,item in rows):failures.append('TOP_FIVE_MISSING_SOURCE_URL')
    if any(abs(sum(float(c['contribution_s_saved_per_mob']) for c in item['contributions'])
               -float(item['known_score_s_saved_per_mob']))>1e-8 for _,_,item in rows):
        failures.append('TOP_FIVE_CONTRIBUTIONS_DO_NOT_SUM')
    if any(item['fully_rankable'] != (len(item['unknown_effects'])==0)
           for _,_,item in rows):failures.append('SILENT_UNKNOWN_EFFECT')
    measured={k:v for k,v in weights.items() if v.get('weight_s_saved_per_mob_per_unit') is not None
              and v.get('status')!='UNSUPPORTED_RUNTIME_AXIS'}
    nonzero={k:v for k,v in measured.items() if abs(v['weight_s_saved_per_mob_per_unit'])>1e-10}
    if len(nonzero)<3:failures.append('DEGENERATE_WEIGHT_MODEL')
    if not any(k in nonzero for k in ('weapon_dps','attack_power','spell_power')):
        failures.append('NO_SOURCED_OFFENSIVE_STAT_WEIGHT')
    if not any(k in nonzero for k in ('armor','stamina','health_regeneration_per_5s','mp5','spirit')):
        failures.append('NO_RECOVERY_OR_SURVIVAL_WEIGHT')
    # A finite difference in a kill-count objective is not a global item
    # coefficient. Require an independently evaluated 100-mob multi-scale
    # audit before passing the *user-facing* Top 5 guarantee.
    if stat_curve_audit is None:
        failures.append('MISSING_100MOB_MULTISCALE_VALIDATION')
    else:
        if (stat_curve_audit.get('build_identity_sha256') != report.get('build_identity_sha256')
            or stat_curve_audit.get('mobs') != 100
            or abs(float(stat_curve_audit.get('base_s_per_mob', float('nan')))
                   -float(report['stat_weights']['base_s_per_mob']))>1e-8):
            failures.append('INVALID_100MOB_MULTISCALE_CONTEXT')
        if not stat_curve_audit.get('pass'):
            failures.append('NONLINEAR_STAT_WEIGHTS_INVALIDATE_TOP5')
        # Mandatory axes must be physically tested; a missing weapon-DPS
        # sensitivity must never be called a zero or treated as established.
        required={k for k in ('agility','weapon_dps') if k in weights}
        if not required.issubset(stat_curve_audit.get('axes',{})):
            failures.append('MISSING_CRITICAL_ITEM_STAT_CURVES')
    # Unsupported negative source-stat values must not be used directly as
    # a generic *penalty* in additive Top 5 gear valuation.
    if any(v['weight_s_saved_per_mob_per_unit'] < -1e-10 for v in measured.values()):
        failures.append('UNVALIDATED_NEGATIVE_GEAR_WEIGHT')

    # All missing axes stay None, never promoted to zero just to pass P3.
    if any(v.get('weight_s_saved_per_mob_per_unit') == 0. and
           v.get('status') not in ('TESTED_ZERO_RANGE_ONLY','CONTEXTUAL_ZERO_FROM_SOURCE_FORM_FIXED',
                                   'MEASURED_ZERO_RANGE') for v in weights.values()):
        failures.append('UNJUSTIFIED_ZERO_AXIS')
    uncertain=report['unknown_item_count']
    return {'gate':'P3','status':'PASS_L0_WITH_EXPLICIT_UNCERTAINTY' if not failures else 'FAIL',
        'pass':not failures,'failures':failures,
        'legal_items':report['total_legal_items'],'slots':len(report['slots']),
        'top5_rows':len(rows),'nonzero_build_specific_axes':sorted(nonzero),
        'measured_or_context_zero_axes':sorted(measured),
        'unknown_weighted_ranking_items':uncertain,
        'unknown_item_components_remain_explicit':True,
        'limits':['NOT all item effects executable in L2',
                  'L0 local marginal weights not a global optimum guarantee',
                  'Unknown item effects, resistances and rank changes can reorder the Top5',
                  'Tested zero over a short finite-difference range does not prove universal zero'],
        'contract':'Source legal L0 + nondegenerate actual 100mob context weights + Top5 contributions, uncertainty disclosed'}
