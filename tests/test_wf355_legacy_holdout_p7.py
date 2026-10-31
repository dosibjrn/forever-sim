from copy import deepcopy
from src.game.data.forever.source_checkpoint_p7_legacy import fingerprint,validate_p7_replays

STAGE={'allocation':{'talent_x':5},'gear_policy_result':{'winner':{'gear':{'slots':{'weapon':{'item_id':123}}},'winner':{'prefix':['cat_form:768'],'fallback':'claw:rank@20','guarded_conditions':[]}}}}
PIN='a'*64
CTX='b'*64
CHECKPOINT='druid:L30:unrestricted'
RECOVERY={key:True for key in ('sourced_form_exit_executed','sourced_hot_cast_executed',
 'sourced_form_reentry_executed','form_entry_mana_paid','gcd_and_cast_time_paid',
 'hot_ticks_persisted_into_next_pull','no_forced_full_hp_mana_per_mob',
 'same_continuous_100mob_objective')}

def evidence(stage,score):
 return {'status':'COMPLETE','count':100,'mean_s_per_mob':score,'continuous_actor_state':True,
 'stage_fingerprint':fingerprint(stage),'source_context_sha256':CTX,
 'evaluator':'new_source_combat_runtime','equipment_legality_checked':True,
 'objective_id':'kill+recovery+survival_100_consecutive_mobs'}

def compare(old=20.,new=19.,old_stage=None,new_stage=None,recovery=True):
 a=deepcopy(old_stage or STAGE);b=deepcopy(new_stage or STAGE)
 return validate_p7_replays(legacy_stage=a,new_stage=b,legacy_publication_sha256=PIN,
     source_context_sha256=CTX,old_replay=evidence(a,old),new_replay=evidence(b,new),
     recovery_semantics_verification={'status':'PASS','source_context_sha256':CTX,**RECOVERY} if recovery else None,
     checkpoint=CHECKPOINT)

def test_legacy_missing_is_not_success():
 x=validate_p7_replays(legacy_stage=None,new_stage=STAGE,legacy_publication_sha256=PIN,
     source_context_sha256=CTX,old_replay=None,new_replay=None,
     recovery_semantics_verification=None,checkpoint=CHECKPOINT)
 assert x['status']=='BLOCKED' and x['reason']=='LEGACY_LEVEL_WINNER_UNPUBLISHED'

def test_new_cannot_lose_p7():
 x=compare(old=18.,new=19.)
 assert not x['pass'] and x['status']=='FAIL_LEGACY_BETTER'

def test_equal_or_faster_new_passes_only_p7():
 assert compare(old=20.,new=19.)['pass']
 assert compare(old=20.,new=20.)['pass']
 assert compare(old=20.,new=19.)['checkpoint_accepted'] is False

def test_recovery_semantics_missing_blocks_even_if_new_faster():
 x=compare(old=20.,new=15.,recovery=False)
 assert not x['pass'] and x['reason']=='BETWEEN_MOB_FORM_HEAL_CONTINUITY_UNPROVEN'

def test_identity_captures_gear_talents_and_policy():
 for location, key, value in [('allocation','talent_x',4)]:
  stage=deepcopy(STAGE);stage[location][key]=value
  assert fingerprint(stage)!=fingerprint(STAGE)
 stage=deepcopy(STAGE);stage['gear_policy_result']['winner']['gear']['slots']['weapon']['item_id']=22
 assert fingerprint(stage)!=fingerprint(STAGE)
 stage=deepcopy(STAGE);stage['gear_policy_result']['winner']['winner']['fallback']='wrath'
 assert fingerprint(stage)!=fingerprint(STAGE)

def test_replay_spoof_wrong_engine_is_blocked():
 stage=deepcopy(STAGE);old=evidence(stage,20);new=evidence(stage,19)
 old['evaluator']='legacy_scorer'
 x=validate_p7_replays(legacy_stage=stage,new_stage=stage,legacy_publication_sha256=PIN,
     source_context_sha256=CTX,old_replay=old,new_replay=new,
     recovery_semantics_verification={'status':'PASS','source_context_sha256':CTX,**RECOVERY},checkpoint=CHECKPOINT)
 assert x['reason']=='REPLAY_NOT_NEW_RUNTIME_LEGACY'

def test_mismatched_build_and_runtime_context_fail_closed():
 stage=deepcopy(STAGE);old=evidence(stage,20);new=evidence(stage,19)
 old['source_context_sha256']='different'
 x=validate_p7_replays(legacy_stage=stage,new_stage=stage,legacy_publication_sha256=PIN,
     source_context_sha256=CTX,old_replay=old,new_replay=new,
     recovery_semantics_verification={'status':'PASS','source_context_sha256':CTX,**RECOVERY},checkpoint=CHECKPOINT)
 assert x['status']=='BLOCKED' and x['reason']=='REPLAY_SOURCE_CONTEXT_MISMATCH_LEGACY'


def test_recovery_status_pass_without_actual_mode_hot_proof_is_blocked():
 stage=deepcopy(STAGE)
 out=validate_p7_replays(legacy_stage=stage,new_stage=stage,
  legacy_publication_sha256=PIN,source_context_sha256=CTX,
  old_replay=evidence(stage,20),new_replay=evidence(stage,19),
  recovery_semantics_verification={'status':'PASS','source_context_sha256':CTX},checkpoint=CHECKPOINT)
 assert out['status']=='BLOCKED' and out['reason']=='RECOVERY_PROOF_INCOMPLETE'
 assert 'hot_ticks_persisted_into_next_pull' in out['missing_recovery_evidence']
