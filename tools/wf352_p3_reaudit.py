"""Revoke WF352 scalar-gear P3: genuine multiscale 100-mob evidence."""
from pathlib import Path
import json
from src.game.data.forever.source_checkpoint_p3_acceptance import l0_gear_top5_certificate
from src.game.data.forever.source_checkpoint_p3_consistency import audit_stat_weight_curves
ROOT=Path(__file__).resolve().parents[1]

def run():
    report=json.loads((ROOT/'evidence/wf352/WF352_L30_P3_TOP5.json').read_text())
    curves=json.loads((ROOT/'evidence/wf352/WF352_P3_ADVERSARIAL_CURVES.json').read_text())
    audit=audit_stat_weight_curves(report=report,curves=curves)
    cert=l0_gear_top5_certificate(report,stat_curve_audit=audit)
    if audit['pass'] or cert['pass']:raise RuntimeError('P3_ADVERSARIAL_REAUDIT_INVALID_EXPECTED_FAIL_CLOSED')
    context={'stale_report_seed_s_per_mob':report['stat_weights']['base_s_per_mob'],
             'newer_100mob_finder_score_s_per_mob':18.0712926573722,
             'newer_finder_context':'WF353 local independent P4/P5 WIP; not yet an accepted checkpoint',
             'finding':'19.0289 seed 16 talent points vs 18.0713 winner 21 talent points, nine different equipped item IDs',
             'requires':'redo gear Top5 in up-to-date best-build context before any new P3 acceptance'}
    result={'report':'WF352_P3_REVOCATION','supersedes_certificate':'WF352_P3_ACCEPTANCE.json',
            'checkpoint':'druid:L30:unrestricted','p3_status':'FAIL_REVOKED',
            'p1_status':'PASS_CARRIED','p2_status':'PASS_CARRIED',
            'p4_p5_p6_status':'NOT_CERTIFIED_BY_THIS_AUDIT',
            'accepted_checkpoints':'1/148','criticisms':['old weapon DPS unknown was fixed by WF352, but source was version-ambiguous',
                  'negative one-step agility slope mislabeled as reliable ranking penalty',
                  'weapon DPS marginal coefficient unusable across item delta thresholds',
                  'WF352 was derived for superseded 16-talent-point seed, not best known L30 build'],
            'multiscale_100mob':audit,'recomputed_certificate':cert,'current_best_context':context,
            'next':'Recompute candidate-context marginal curves and replay high-ranked item swaps at the actual 100mob objective; mark unresolved Top5 ranking uncertainty; reject until reranked and calibrated.'}
    out=ROOT/'evidence/wf352/WF352_P3_REVOCATION.json'
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return {'status':'FAIL_REVOKED','accepted_checkpoints':'1/148',
            'failures':cert['failures'],'curve_failures':audit['failures'],'output':str(out)}
if __name__=='__main__': print(json.dumps(run(),indent=2))
