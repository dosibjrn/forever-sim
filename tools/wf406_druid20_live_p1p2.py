"""Read-only, independent live L0 recheck for the first priority checkpoint.

This is a diagnostic bridge using the published Druid L20 source observations,
NOT the generic gate verifier for all 148 cases. Does not mutate source DBs,
claim L2 completeness, or create a seven-gate PASS.
"""
from __future__ import annotations
import json,time,hashlib
from pathlib import Path
from tools.wf335_spellbook_p1 import run as run_p1
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint,evaluate_p2
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.rulesets.forever.items.runtime_selection import _DEFAULT_DB as ITEM_DB

ROOT=Path(__file__).resolve().parents[1]

def run():
    started=time.monotonic()
    p1=run_p1()
    p2=evaluate_p2(build_game_ir_slice(class_key='druid',level=20),P2Checkpoint('druid',20),
        source_observations_path=ROOT/'evidence/wf336/druid_l20_talent_rank_observations_70338.json',
        spellbook_path=ROOT/'evidence/wf335/druid_spellbook_70338_level1_20.json')
    # These checks support coverage diagnostics, not P1/P2 full L2 gameplay.
    return {
        'checkpoint':'druid:L20:unrestricted','kind':'CURRENT_P1_P2_L0_RECHECK_NOT_GATE_ACCEPTANCE',
        'p1':{'l0_pass':p1['PASS1'], 'legal':p1['legal'], 'conditional':p1['conditional'],
              'ranked':p1['scored_legal_or_conditional'], 'unresolved':p1['unresolved'],
              'source_build':p1['source_build']},
        'p2':{'l0_pass':p2['p2_pass'], 'reachable':p2['known_reachable_rank_count'],
              'ranked':p2['l0_scored_reachable_rank_count'],
              'l2_unsupported':p2['l2_unsupported_scored_rank_count']},
        'item_db_sha256':hashlib.sha256(ITEM_DB.read_bytes()).hexdigest(),
        'ability_db_sha256':hashlib.sha256(DEFAULT_DB.read_bytes()).hexdigest(),
        'actual_wall_s':round(time.monotonic()-started,6),
        'full_checkpoint_accepted':False,
        'caveat':'P1/P2 are L0 scoped; P3 fast score smoke is not run; no P4-P7 search/replay',
    }

if __name__=='__main__':
    print(json.dumps(run(),sort_keys=True,indent=2))
