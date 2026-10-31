"""Read-only staged ability SQLite → generic IR → bounded real policy search.

This is a *verification gate*, NOT a parser, source-authority validator or a
promotion command. A synthetic SQL mutation can pass this executable probe,
but cannot become canonical data without a separately verified fetch/parse
transaction. Never interpret a bounded candidate winner as a global optimum.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from math import isfinite
from urllib.parse import urlsplit

from src.game.data.forever.registry import build_game_ir_slice
from src.game.multi_pull import evaluate_repeated_pulls
from src.v2.source_policy_search import synthesize_source_policies


def _integrity(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as connection:
        result = connection.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise ValueError(f'invalid SQLite stage {path}: {result}')


def _source_rows(path: Path, class_key: str, level: int) -> dict[int, tuple]:
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as conn:
        rows = conn.execute('''SELECT i.spell_id, i.raw_listview_json, i.source_url,
            s.semantic_type, s.required_mode_id, s.gcd_s, s.tick_interval_s,
            s.spell_power_coefficient, s.source_url, s.mechanics_source_url,
            s.caveats_json, m.tick_interval_s, m.crit_multiplier
            FROM spell_index i LEFT JOIN ability_semantic_source_facts s
              ON s.class_key=i.class_key AND s.spell_id=i.spell_id
            LEFT JOIN sourced_direct_periodic_melee_semantics m ON m.spell_id=i.spell_id
            WHERE i.class_key=? AND i.kind='abilities' AND i.level_hint<=?
            ORDER BY i.spell_id''', (class_key, level)).fetchall()
        return {int(row[0]):tuple(row[1:]) for row in rows}


def _verify_changed_identity(path: Path, class_key: str, spell_ids: list[int]) -> None:
    """Reject a wrong/renamed source page even if the executable grammar matches."""
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as conn:
        for sid in spell_ids:
            rows=conn.execute('''SELECT i.source_url,i.raw_listview_json,s.source_url
                    FROM spell_index i LEFT JOIN ability_semantic_source_facts s
                      ON s.class_key=i.class_key AND s.spell_id=i.spell_id
                    WHERE i.class_key=? AND i.kind='abilities' AND i.spell_id=?''',
                    (class_key,sid)).fetchall()
            if len(rows)!=1 or rows[0][2] is None:
                raise ValueError(f'{sid}: missing/ambiguous indexed typed source')
            index_url,raw,semantics_url=rows[0]
            parsed=urlsplit(str(index_url))
            if (parsed.scheme!='https' or parsed.hostname!='www.wowhead.com'
                    or parsed.path!=f'/forever/spell={sid}' or parsed.query or parsed.fragment
                    or index_url!=semantics_url):
                raise ValueError(f'{sid}: wrong page/source-identity mismatch')
            try:
                row=json.loads(raw)
            except (ValueError,TypeError) as exc:
                raise ValueError(f'{sid}: invalid source listview JSON') from exc
            if not isinstance(row,dict) or row.get('id')!=sid:
                raise ValueError(f'{sid}: wrong page/listview identity mismatch')


def compare(*, canonical_db: Path, staged_db: Path, class_key: str, level: int,
            mode_id: str, target_health: float, pulls: int,
            pre_combat_action_ids: tuple[str,...] = (),
            post_combat_action_ids: tuple[str,...] = (),
            prepared_first_pull_resources: dict[str,float] | None = None,
            travel_time_s: float = 0.0,
            max_policies: int = 28,
            include_auto_resource_fallback: bool = True,
            retain_mode_between_pulls: bool = True,
            apply_target_defense: bool = True) -> dict:
    """Demonstrate real search sensitivity to staged facts, without promotion.

    Both arms independently build from their respective source DB. The exact
    candidate frontier and any failed evaluations are reported, not hidden.
    Only the tested indexed-action subset is established, never class coverage.
    """
    canonical_db, staged_db = Path(canonical_db).resolve(), Path(staged_db).resolve()
    if canonical_db == staged_db:
        raise ValueError('staging and canonical SQLite must differ')
    if level < 1 or pulls < 1 or max_policies < 1 or not isfinite(target_health) or target_health <= 0:
        raise ValueError('invalid combat scenario')
    _integrity(canonical_db)
    _integrity(staged_db)
    key=class_key.strip().lower()
    old_rows = _source_rows(canonical_db,key,level)
    new_rows = _source_rows(staged_db,key,level)
    modified_ids = sorted(sid for sid in old_rows.keys() | new_rows.keys()
                          if old_rows.get(sid) != new_rows.get(sid))
    if not modified_ids:
        raise ValueError('no indexed ability-source delta in tested level window')
    _verify_changed_identity(staged_db,key,modified_ids)
    report = {'class_key':key,'level':int(level),'changed_spell_ids':modified_ids,
              'scope':'bounded_source_policy_search_real_combat_recovery',
              'provenance_status':'NOT_VERIFIED_BY_THIS_GATE',
              'promoted':False,'complete_action_coverage':False,
              'arms':{}}
    for label,db in (('canonical',canonical_db),('staging',staged_db)):
        ir=build_game_ir_slice(class_key=key,level=level,ability_db_path=db)
        if ir is None:
            raise ValueError('no registered class provider')
        envelope=synthesize_source_policies(ir,level=level,mode_id=mode_id,
                max_policies=max_policies,include_auto_resource_fallback=include_auto_resource_fallback,
                budget_mode='balanced_frontier')
        # A changed known action must stay executable & discoverable.
        source_ids = {int(src.get('source_spell_id')) for a in ir.actions
                      for src in a.provenance if isinstance(src,dict) and src.get('source_spell_id')}
        missing = sorted(set(modified_ids) - source_ids)
        if missing:
            raise ValueError(f'{label}: changed source spell IDs not compiled to executable actions: {missing}')
        scores=[]; errors=[]
        for policy in envelope['policies']:
            try:
                result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=level,
                    target_health=target_health,count=pulls,
                    pre_combat_action_ids=pre_combat_action_ids,
                    post_combat_action_ids=post_combat_action_ids,
                    prepared_first_pull_resources=prepared_first_pull_resources,
                    recovery_mode='threshold',retain_mode_between_pulls=retain_mode_between_pulls,
                    travel_time_s=travel_time_s,apply_target_defense=apply_target_defense)
                if not isfinite(result.seconds_per_mob) or result.seconds_per_mob<=0:
                    raise ValueError('non-finite/nonpositive score')
                scores.append({'policy_id':policy.id,'seconds_per_mob':result.seconds_per_mob,
                               'actions':[r.action_id for r in policy.rules]})
            except (ValueError,RuntimeError,TypeError,KeyError) as exc:
                errors.append({'policy_id':policy.id,'error':str(exc)})
        if errors or not scores:
            raise ValueError(f'{label}: incomplete real policy scoring: {errors}')
        scores.sort(key=lambda x:(x['seconds_per_mob'],x['policy_id']))
        report['arms'][label]={'candidate_count':len(envelope['policies']),
                              'evaluated_count':len(scores),
                              'winner':scores[0], 'runnerup':scores[1] if len(scores)>1 else None,
                              'policy_scores':scores}
    return report


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--canonical',type=Path,required=True)
    p.add_argument('--staging',type=Path,required=True)
    p.add_argument('--class-key',required=True)
    p.add_argument('--level',type=int,required=True)
    p.add_argument('--mode-id',required=True)
    p.add_argument('--target-health',type=float,required=True)
    p.add_argument('--pulls',type=int,default=3)
    p.add_argument('--pre-action',action='append',default=[])
    p.add_argument('--post-action',action='append',default=[])
    p.add_argument('--initial-resource',action='append',default=[],help='key=value')
    p.add_argument('--travel-time-s',type=float,default=0)
    a=p.parse_args()
    resources={}
    for item in a.initial_resource:
        key,sep,value=item.partition('=')
        if not sep: p.error('initial-resource must have key=value')
        resources[key]=float(value)
    result=compare(canonical_db=a.canonical,staged_db=a.staging,class_key=a.class_key,
          level=a.level,mode_id=a.mode_id,target_health=a.target_health,pulls=a.pulls,
          pre_combat_action_ids=tuple(a.pre_action),post_combat_action_ids=tuple(a.post_action),
          prepared_first_pull_resources=resources or None,travel_time_s=a.travel_time_s)
    # Includes all candidates for auditable scores, not just the top two.
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__=='__main__':
    main()
