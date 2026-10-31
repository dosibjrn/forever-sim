from tools.wf341_rating_probe import ROOT
import json,os,sqlite3,tempfile
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.source_db_scope import ability_source_scope
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.rulesets.forever.items.runtime_selection import available_items
from src.v2.source_persistent_slot_search import _gear_replace
import copy
os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
with tempfile.TemporaryDirectory() as tmp:
    staged=Path(tmp)/'s.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db,sqlite3.connect(staged) as dst: db.backup(dst)
    ingest_observations(staged,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
    ingest_control(staged,ROOT/'evidence/wf321/druid_l20_control_observations.json')
    with ability_source_scope(staged):
        rating_item=next(x for x in available_items('druid',20,required_level_policy='observed') if int(x.item_id)==12985)
        stage=copy.deepcopy(stage)
        stage['gear_policy_result']['winner']['gear']=_gear_replace(
            stage['gear_policy_result']['winner']['gear'],'ring1',rating_item)
        unmod=prepare_candidate(class_key='druid',level=20,stage=stage)
        approx=prepare_candidate(class_key='druid',level=20,stage=stage,provisional_rating_model=True)
        b=evaluate_persistent_candidate(unmod,level=20,mobs=100,max_total_events=250000)
        a=evaluate_persistent_candidate(approx,level=20,mobs=100,max_total_events=250000)
        r=approx.ir.provenance['provisional_equipped_ratings']
        print(json.dumps({'rating_totals':r['totals'],'old':b['mean_s_per_mob'],
            'provisional_new':a['mean_s_per_mob'],'changed_actor_axes':{
            key:[unmod.ir.actor.base_stats.get(key),val] for key,val in approx.ir.actor.base_stats.items()
            if val!=unmod.ir.actor.base_stats.get(key)},
            'full_l2_valid':r['full_L2_valid']},indent=2))
