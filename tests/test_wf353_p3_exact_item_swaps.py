import json
from pathlib import Path
import pytest
from src.game.data.forever.source_checkpoint_p3_swaps import (
 substituted_stage,source_context_fingerprint,isolated_100mob,
)
from src.rulesets.forever.items.runtime_selection import available_items

ROOT=Path(__file__).resolve().parents[1]
STAGE=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())

def test_exact_swap_rebuilds_stats_and_preserves_original():
 stage=STAGE
 slot='weapon';original=stage['gear_policy_result']['winner']['gear']['slots'][slot]['item_id']
 changed=substituted_stage(stage=stage,class_key='druid',level=30,slot=slot,item_id=original)
 assert changed['gear_policy_result']['winner']['gear']['aggregate_stats']==stage['gear_policy_result']['winner']['gear']['aggregate_stats']
 assert stage['score_s_per_mob'] is not None
 assert changed['score_s_per_mob'] is None
 assert changed is not stage

def test_slot_and_checkpoint_fail_closed():
 item=STAGE['gear_policy_result']['winner']['gear']['slots']['weapon']['item_id']
 with pytest.raises(ValueError,match='WRONG_CHECKPOINT'):
  substituted_stage(stage=STAGE,class_key='druid',level=20,slot='weapon',item_id=item)
 with pytest.raises(ValueError,match='SLOT_NOT_EQUIPPED'):
  substituted_stage(stage=STAGE,class_key='druid',level=30,slot='nonsense',item_id=item)
 with pytest.raises(ValueError,match='NOT_SOURCE_LEGAL'):
  substituted_stage(stage=STAGE,class_key='druid',level=30,slot='weapon',item_id=-1)

def test_source_context_identity_sensitive_to_gear_and_policy():
 a=source_context_fingerprint(stage=STAGE,class_key='druid',level=30,source_db_sha256='A')
 b=source_context_fingerprint(stage=STAGE,class_key='druid',level=30,source_db_sha256='B')
 assert a!=b
 import copy
 changed=copy.deepcopy(STAGE)
 changed['gear_policy_result']['winner']['winner']['fallback']='test:untrusted'
 assert source_context_fingerprint(stage=changed,class_key='druid',level=30,source_db_sha256='A')!=a

def test_hard_timeout_does_not_become_completed_score():
 import time
 def slow(q,candidate,level):time.sleep(2.)
 out=isolated_100mob(None,level=30,timeout_s=.05,worker=slow)
 assert out['status']=='OS_TIMEOUT' and out['outer_wall_s']<1.5

def test_stage_preparation_itself_is_hard_bounded():
 from src.game.data.forever.source_checkpoint_p3_swaps import isolated_stage_100mob
 import time
 def slow(q,stage,source_ir,class_key,level,slot,item_id):time.sleep(2.)
 out=isolated_stage_100mob(stage=STAGE,source_ir=None,class_key='druid',level=30,
                           timeout_s=.05,worker=slow)
 assert out['status']=='OS_TIMEOUT' and out['outer_wall_s']<1.5

def test_two_sourced_item_swaps_preserve_full_gear_audit():
 from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
 s=substituted_multi_stage(stage=STAGE,class_key='druid',level=30,
                           swaps={'chest':7374,'shoulder':2278})
 assert s['gear_policy_result']['winner']['gear']['slots']['chest']['item_id']==7374
 assert s['gear_policy_result']['winner']['gear']['slots']['shoulder']['item_id']==2278
 assert STAGE['gear_policy_result']['winner']['gear']['slots']['chest']['item_id']!=7374
