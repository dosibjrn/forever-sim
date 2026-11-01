"""WF412: genuine PROCESS v2 P3 semantic evidence, not a JSON green alone."""
import hashlib
import json
from pathlib import Path
from src.game.checkpoint_p3_smoke import (
    fast_p3_smoke_for_policy,policy_uses_equipped_weapon_damage,
    policy_uses_equipped_weapon_mean_hit,
)
from tools.wf412_recertify_druid20_p3 import recovered_wf347_winner

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'evidence/wf412/WF412_DRUID_L20_P3_REOPTIMIZED_SOURCE_WINNER.json'


def test_new_p3_evidence_is_replayable_on_original_sourced_build_and_gear():
    r=json.loads(EVIDENCE.read_text())
    assert r['p3_status']=='PASS' and not r['accepted_checkpoint']
    candidate, stage, published=recovered_wf347_winner()
    assert {k:int(v['item_id']) for k,v in stage['gear_policy_result']['winner']['gear']['slots'].items()}==published['winner']['gear']
    assert stage['allocation']==published['winner']['talents']
    assert r['replayed_wf347_talents']==published['winner']['talents']
    assert abs(r['replayed_wf347_fixed_full_recovery_100mob_s_per_mob']-
               published['winner']['actual_100mob_s_per_mob']) < 1e-9
    assert policy_uses_equipped_weapon_damage(candidate.ir,candidate.policy)
    assert not policy_uses_equipped_weapon_mean_hit(candidate.ir,candidate.policy)
    report=fast_p3_smoke_for_policy(source_ir=candidate.ir,policy=candidate.policy,
         class_key='druid',level=20,weights=r['weight_certificate'],
         weight_evidence_kind='MEASURED_SOURCE_CONTEXT')
    assert report['p3_pass'] and not report['blockers']
    assert report['tested_item_count']==92 and report['slot_count']==19
    assert report['source_policy']['equipped_weapon_damage_relevant']
    assert not report['source_policy']['equipped_weapon_mean_hit_relevant']


def test_four_missing_weights_are_real_100mob_improvements_same_build():
    r=json.loads(EVIDENCE.read_text())
    from src.rulesets.forever.items.runtime_selection import catalogue_path
    assert r['source_catalogue_sha256']==hashlib.sha256(catalogue_path().read_bytes()).hexdigest()
    for axis in ('stamina','spirit','mp5','spell_power'):
        row=r['reoptimized_evidence'][axis]
        assert row['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
        assert row['positive'] and row['mobs']==100
        assert row['best']['before']['status']==row['best']['after']['status']=='COMPLETE'
        assert row['weight_s_saved_per_mob_per_unit']>0
        assert r['weight_certificate'][axis]['weight_s_saved_per_mob_per_unit']==row['weight_s_saved_per_mob_per_unit']
        assert all(s['status']=='COMPLETE' for s in row['rows'])


def test_protected_process_and_overall_bytes_unchanged():
    fixed={
      'PROCESS_WOW_FOREVER_v2_2026-10-15.md':'f605840ba8321cf0494a2fe813a596fd873a800e1c4f9a05b65bf69281345a5d',
      'OVERALL_PLAN_WOW_FOREVER_v5_APPROVED_2026-10-15.md':'841162fa6817c8c8b20e2804c5e77f9589d167765ad537bdad6daa508e1e5e5a',
    }
    for name,digest in fixed.items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
