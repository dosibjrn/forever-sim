"""Export independently run legacy Druid L30 winner, not a missing /decisions cached row.

Does not consult the new simulator's winning talents/gear/policy.  P7 must
subsequently convert this frozen challenge and replay it in the NEW engine.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def export_legacy_winner(snapshot: dict, *, snapshot_sha256: str) -> dict:
    if snapshot.get('phase') != 'complete' or snapshot.get('running') is not False:
        raise ValueError('LEGACY_SEARCH_NOT_COMPLETED')
    game = snapshot.get('game') or {}
    if (game.get('ruleset'), (game.get('class_name') or game.get('class'))) != ('forever', 'druid'):
        raise ValueError('WRONG_LEGACY_CLASS')
    if snapshot.get('engine') != 'v2-forever-experimental-class':
        raise ValueError('NOT_LEGACY_CLASS_SCORER')
    config = snapshot.get('config') or {}
    view = (snapshot.get('views') or {}).get('experimental') or {}
    levels = [x for x in view.get('level_summaries') or () if int(x.get('level', -1)) == 30]
    if len(levels) != 1:
        raise ValueError('NOT_ONE_LEGACY_L30_SEARCH_RESULT')
    row = levels[0]
    winner = row.get('best') or {}
    if (int(winner.get('level', -1)) != 30 or not winner.get('talent_ranks')
            or sum(int(n) for n in winner['talent_ranks'].values()) != 21):
        raise ValueError('LEGACY_TALENTS_INCOMPLETE')
    gear = (winner.get('gear_stats') or {}).get('slots') or {}
    if not gear or any(item.get('item_id') is None for item in gear.values()):
        raise ValueError('LEGACY_NAMED_GEAR_INCOMPLETE')
    if not (winner.get('rotation') and winner.get('combat_profile')):
        raise ValueError('LEGACY_POLICY_INCOMPLETE')
    if not winner.get('score_s_per_100') or float(winner['score_s_per_100']) <= 0:
        raise ValueError('LEGACY_SCORE_MISSING')
    # The standalone legacy class scorer is NOT the shared CombatRuntime.
    # Its score is a diagnostic only, and may not be used in P7 adjudication.
    return {
        'status':'LEGACY_L30_CHALLENGER_EXTRACTED_NOT_P7_PASS',
        'source':'independent_legacy_v2_runner_search',
        'publication_provenance':{'snapshot_sha256':snapshot_sha256,'engine':snapshot['engine'],
                                  'game':game,'search_config':config},
        'level':30,'talent_points':21,
        'talent_ranks':winner['talent_ranks'],'combat_profile':winner['combat_profile'],
        'rotation':winner['rotation'],'gear':winner['gear_stats'],
        'legacy_seconds_per_100':float(winner['score_s_per_100']),
        'source_row_identity':_digest(json.dumps(winner,sort_keys=True,default=str).encode()),
        'original_legacy_best_row':winner,
        'P7_comparable_replay':'NOT_RUN',
        'note':'Legacy metric is NOT comparable to new 100-mob CombatRuntime. Original candidate must be re-executed in new runtime, never copied from new winner.',
    }


def main():
    p=argparse.ArgumentParser();p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    data=args.snapshot.read_bytes()
    result=export_legacy_winner(json.loads(data),snapshot_sha256=_digest(data))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+'\n')
    print('LEGACY_L30',result['combat_profile'],result['talent_ranks'], 'legacy only',result['legacy_seconds_per_100']/100,flush=True)

if __name__=='__main__': main()
