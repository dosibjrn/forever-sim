"""Source-catalogue per-slot gear coordinate search with actual persistent L2.

Unlike weight-vector selectors, this can test an item that is not the top
choice under ANY previously generated weight vector. The legacy oracle is
never an input. This is a bounded coordinate search, not a global proof.
"""
from __future__ import annotations
from collections import defaultdict
import json
from math import isfinite
from time import process_time, monotonic
from src.rulesets.forever.items.runtime_selection import (
    available_items,item_vector,item_payload,effective_level,item_score,item_scoring_vector,
)
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate


def _physical_slot(slot,item):
    if slot in ('ring1','ring2'):return item.slot=='finger'
    if slot in ('trinket1','trinket2'):return item.slot=='trinket'
    if slot=='weapon':return item.slot in ('one_hand','main_hand','two_hand')
    if slot=='offhand':return item.slot=='off_hand' and item.weapon_hands!=2
    return item.slot==slot


def _gear_replace(base,slot,item):
    slots={k:dict(v) for k,v in base['slots'].items()}
    slots[slot]=item_payload(item,display_slot=slot,effective_level=effective_level(item))
    from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids
    validate_equipped_item_ids(int(x['item_id']) for x in slots.values())
    stats={}
    for record in slots.values():
        for key in ('strength','agility','stamina','intellect','spirit','attack_power','spell_power',
                    'healing','mp5','armor','weapon_dps','wand_dps'):
            stats[key]=stats.get(key,0.)+float(record.get(key,0.))
    return {**base,'slots':slots,'aggregate_stats':stats,'item_count':len(slots)}


def _source_slot_proposals(*,class_key,level,base,per_slot=2,max_proposals=48,
                           p3_certificate=None,weighted_p3_report=None,seed_stage=None,
                           allow_unattested_diagnostic=False):
    if max_proposals < 0:
        raise ValueError('invalid source slot proposal budget')
    if max_proposals == 0:
        if p3_certificate is not None:
            from src.game.data.forever.source_checkpoint_p3 import verify_checkpoint_item_l0
            verify_checkpoint_item_l0(p3_certificate,class_key=class_key,level=level,
                allow_unattested_diagnostic=allow_unattested_diagnostic)
        return [],{}
    items=available_items(class_key,level,required_level_policy='observed')
    from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids
    def group_legal(slot,item):
        ids=[int(x['item_id']) for k,x in base['slots'].items() if k!=slot]
        try:
            validate_equipped_item_ids(ids+[int(item.item_id)])
            return True
        except ValueError as exc:
            if ('BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP' in str(exc)
                or 'DUPLICATE_EQUIPPED_ITEM' in str(exc)):
                return False
            raise
    if weighted_p3_report is not None:
        from src.game.data.forever.source_checkpoint_p3_weights import verify_weighted_ranking
        # Source-backed weighted Top N is the only ranking when supplied.
        # Do not pretend unknown item effects have been fully resolved.
        verify_weighted_ranking(weighted_p3_report,class_key=class_key,level=level,
            stage=seed_stage if seed_stage is not None else {})
        by_id={int(x.item_id):x for x in items}
        groups={};rankings={}
        for slot,frontier in weighted_p3_report['slots'].items():
            if slot=='offhand' and (not base['slots'].get('weapon') or
                                    base['slots']['weapon']['weapon_hands']==2):continue
            used={int(x['item_id']) for other,x in base['slots'].items() if other!=slot}
            current=base['slots'].get(slot)
            legal=[by_id[int(i)] for i in frontier['all_ranked_item_ids']
                if int(i) not in used and (current is None or int(i)!=int(current['item_id']))
                and _physical_slot(slot,by_id[int(i)]) and group_legal(slot,by_id[int(i)])]
            groups[slot]=legal
            rankings[slot]=legal[:per_slot]
        proposals=[]
        for depth in range(per_slot):
            for slot in sorted(rankings):
                if depth<len(rankings[slot]):
                    proposals.append((slot,rankings[slot][depth]))
                    if len(proposals)>=max_proposals:return proposals,{k:len(v) for k,v in groups.items()}
        return proposals,{k:len(v) for k,v in groups.items()}
    if p3_certificate is not None:
        # Reuse the complete L0 certificate to drive *real* paid proposals.
        # Every item remains in the certificate, even if the paid budget can
        # afford only a small sample of the highest-priority alternatives.
        from src.game.data.forever.source_checkpoint_p3 import verify_checkpoint_item_l0
        verify_checkpoint_item_l0(p3_certificate,class_key=class_key,level=level,
            allow_unattested_diagnostic=allow_unattested_diagnostic)
        by_id={int(x.item_id):x for x in items}
        groups={};rankings={}
        for slot,frontier in p3_certificate['slot_frontiers'].items():
            # An offhand requires a one-handed weapon; changing the weapon
            # package is a distinct search move, not an illegal free addition.
            if slot=='offhand' and (not base['slots'].get('weapon') or
                base['slots']['weapon']['weapon_hands']==2):
                continue
            used={int(x['item_id']) for other,x in base['slots'].items() if other!=slot}
            current=base['slots'].get(slot)
            ids=[int(i) for i in frontier['priority_item_ids']]
            legal=[by_id[i] for i in ids if i not in used
                   and (current is None or i!=int(current['item_id']))
                   and _physical_slot(slot,by_id[i]) and group_legal(slot,by_id[i])]
            groups[slot]=legal
            rankings[slot]=legal[:per_slot]
        # Slot round-robin: an overall 48-proposal budget must not drop
        # weapon/relic/trinket just because their names sort late.
        proposals=[]
        for depth in range(per_slot):
            for slot in sorted(rankings):
                if depth<len(rankings[slot]):
                    proposals.append((slot,rankings[slot][depth]))
                    if len(proposals)>=max_proposals:
                        return proposals,{k:len(v) for k,v in groups.items()}
        return proposals,{k:len(v) for k,v in groups.items()}
    groups=defaultdict(list)
    for slot in base['slots']:
        used={int(x['item_id']) for other,x in base['slots'].items() if other!=slot}
        original=base['slots'][slot]
        for item in items:
            if item.item_id in used or item.item_id==int(original['item_id']):continue
            if not _physical_slot(slot,item) or not group_legal(slot,item):continue
            if slot=='weapon' and 'offhand' in base['slots'] and item.weapon_hands==2:continue
            if slot=='offhand' and base['slots']['weapon']['weapon_hands']==2:continue
            groups[slot].append(item)
    weights=dict(base['selection_weights'])
    # Diverse, source-only stat axes. Candidate ranking is only a pruning
    # heuristic; all final comparisons use the exact CombatRuntime clock.
    axes=[weights,{'strength':1.},{'agility':1.},{'stamina':1.},
          {'intellect':1.},{'spirit':1.},{'weapon_dps':1.},
          {'armor':1.},{'spell_power':1.}]
    per=[]
    for slot,rows in sorted(groups.items()):
        if not rows:continue
        ranked=[];seen=set()
        axis_rankings=[sorted(rows,key=lambda x:(item_score(x,axis),int(x.item_level or 0),-int(x.item_id)),reverse=True)
                       for axis in axes]
        # Include source-typed numeric extra axes in the actual paid shortlist.
        # A physical build's primary-stat heuristic alone can miss equipment
        # that shortens recovery (HP5) without increasing immediate damage.
        # No item ID, class-specific action or guessed effect is introduced.
        from src.rulesets.forever.items.source_numeric_extras import modeled_source_numeric_extras
        extra_axes=sorted({k for row in rows for k,v in modeled_source_numeric_extras(row).items() if v})
        for axis in extra_axes:
            ranking=sorted(rows,key=lambda x:(
                modeled_source_numeric_extras(x).get(axis,0.),int(x.item_level or 0),-int(x.item_id)),reverse=True)
            # HP5 is relevant to every physical/magic survival+recovery clock,
            # whereas penetration/resistance requires a matching encounter.
            # Surface its best candidate even in a short, slot-round-robin P4.
            axis_rankings.insert(0 if axis=='health_regeneration_per_5s' else 1, ranking)
        # Round-robin *axes* before depth. Otherwise top-3 is just the
        # first weight vector's top-2 plus one strength item, excluding all
        # other independently source-derived objectives from the actual L2.
        for depth in range(len(rows)):
            for ranking in axis_rankings:
                if depth<len(ranking):
                    item=ranking[depth]
                    if item.item_id not in seen:
                        ranked.append(item);seen.add(item.item_id)
            if len(ranked)>=per_slot:break
        for item in ranked[:per_slot]:
            per.append((slot,item))
    return per[:max_proposals],{slot:len(rows) for slot,rows in groups.items()}



def _source_chance_axis_gain(*, axis, selected, base):
    """Raw source-stat gain for a complete, legal candidate package.

    ItemRecord and published stage payload use different field names; this
    helper compares the same source units without any rating conversion.
    """
    selected_raw=sum(float(item_scoring_vector(item).get(axis,0.) or 0.)
                     for item in selected.values())
    equipped_raw=sum(float(item.get(axis+'_rating',0.) or 0.)
                     for item in base['slots'].values())
    return selected_raw-equipped_raw


def _source_cross_axis_gear_packages(*, base, pure, axes, by_id,
                                     already_seen, is_legal):
    """Cross source item winners, requiring two independently improved axes.

    A candidate's contribution is computed from actual selected item records;
    no synthetic weights, historical winners, or class-dependent exceptions.
    """
    vectors={item_id:item_scoring_vector(item) for item_id,item in by_id.items()}
    original={slot:int(item['item_id']) for slot,item in base['slots'].items()}
    def total(swaps,axis):
        values=[]
        for slot,item in base['slots'].items():
            record=vectors.get(int(swaps.get(slot,item['item_id'])))
            if record is None:
                return None
            values.append(float(record.get(axis,0.) or 0.))
        return sum(values)
    base_totals={axis:total({},axis) for axis in axes}
    mixed=[]
    mixed_seen=set(already_seen)
    for left_i,(left,left_swaps) in enumerate(pure[:6]):
        for right,right_swaps in pure[left_i+1:6]:
            if total(left_swaps,left) is None or total(right_swaps,right) is None:
                continue
            if (total(left_swaps,left)<=base_totals[left]+1e-9 or
                    total(right_swaps,right)<=base_totals[right]+1e-9):
                continue
            conflicting=[]
            for slot,item in base['slots'].items():
                first=int(left_swaps.get(slot,item['item_id']))
                second=int(right_swaps.get(slot,item['item_id']))
                if first==second or first not in vectors or second not in vectors:
                    continue
                increase=(float(vectors[second].get(right,0.) or 0.)
                          -float(vectors[first].get(right,0.) or 0.))
                if increase>1e-9:
                    conflicting.append((-increase,slot,second))
            for _,slot,second in sorted(conflicting):
                swaps=dict(left_swaps)
                if second==original[slot]:
                    swaps.pop(slot,None)
                else:
                    swaps[slot]=second
                signature=tuple(sorted(swaps.items()))
                if signature in mixed_seen or not is_legal(swaps):
                    continue
                if (total(swaps,left) is None or total(swaps,right) is None or
                        total(swaps,left)<=base_totals[left]+1e-9 or
                        total(swaps,right)<=base_totals[right]+1e-9):
                    continue
                mixed_seen.add(signature)
                mixed.append((left+'+'+right,swaps))
    return mixed


def _source_bounded_pure_mixed_order(pure, mixed, max_packages):
    """Retain prior pure-axis coverage while adding one mixed source package."""
    pure_reserved=min(len(pure),max_packages if max_packages<=2 else max_packages-1)
    proposals=list(pure[:pure_reserved])
    proposals.extend(mixed[:min(1,max_packages-len(proposals))])
    for candidate in pure[pure_reserved:]:
        if len(proposals)>=max_packages:
            break
        proposals.append(candidate)
    return proposals


def _source_stat_package_proposals(*, class_key, level, base, max_packages=4):
    """Source-legal pure and mixed-stat full gear proposals within one quota.

    A mixed candidate crosses actual canonical item selections, not synthetic
    marginal stat weights. It is emitted only if *both* source-stat totals beat
    the same incumbent, and the entire resulting equipment set is legal.
    All candidates still require the ordinary paid CombatRuntime objective.
    """
    if type(max_packages) is not int or max_packages < 0:
        raise ValueError('INVALID_STAT_PACKAGE_PROPOSAL_BUDGET')
    if not max_packages:
        return [], {'authority':'CANONICAL_SOURCE_SQLITE',
                    'historical_winner_as_seed':False,'axes_tried':[],
                    'mixed_stat_candidates':0}
    from src.rulesets.forever.items.runtime_selection import select_gear
    from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
    axes=('spell_power','crit','hit','strength','agility','weapon_dps',
          'intellect','stamina','spirit','armor','attack_power','mp5')
    role=str(base.get('role') or '')
    original={slot:int(item['item_id']) for slot,item in base['slots'].items()}
    stage={'allocation':{},'gear_policy_result':{'winner':{
        'gear':base,'winner':{'prefix':[],'fallback':'unused'}}}}
    pure=[]
    seen=set()
    tried=[]
    def legal(swaps):
        if not swaps:
            return False
        try:
            substituted_multi_stage(stage=stage,class_key=class_key,
                                    level=level,swaps=swaps)
        except (ValueError,KeyError):
            return False
        return True
    for axis in axes:
        selected=select_gear(class_key,level,role,weights={axis:1.},
            required_level_policy='observed',exclude_unknown_item_effects=True)
        tried.append(axis)
        if axis in ('crit','hit') and _source_chance_axis_gain(
                axis=axis,selected=selected,base=base)<=0:
            continue
        swaps={slot:int(item.item_id) for slot,item in selected.items()
               if original.get(slot)!=int(item.item_id)}
        signature=tuple(sorted(swaps.items()))
        if signature in seen or not legal(swaps):
            continue
        seen.add(signature)
        pure.append((axis,swaps))

    from src.rulesets.forever.items.runtime_selection import available_items
    by_id={int(item.item_id):item for item in available_items(
        class_key,level,required_level_policy='observed')}
    mixed=_source_cross_axis_gear_packages(base=base,pure=pure,axes=axes,
        by_id=by_id,already_seen=seen,is_legal=legal)

    # Preserve both pure-axis anchors before admitting cross-axis candidates.
    # The shared package budget is unchanged: no free evaluations are added.
    proposals=_source_bounded_pure_mixed_order(pure,mixed,max_packages)
    return proposals, {'authority':'CANONICAL_SOURCE_SQLITE',
                       'historical_winner_as_seed':False,
                       'axes_tried':tried,
                       'mixed_stat_candidates':sum('+' in label for label,_ in proposals),
                       'mixed_stat_legal_candidates':len(mixed),
                       'multi_slot_candidates':sum(len(swaps)>1 for _,swaps in proposals)}


def _source_weapon_package_proposals(*, class_key, level, base, max_packages=8):
    """Explore source-legal weapon *packages*, not invalid intermediate slots.

    A 2H incumbent hides the entire offhand frontier from single-slot search.
    Conversely a 1H+offhand incumbent hides 2H replacements. These moves are
    assembled from the same canonical item catalogue, then verified atomically
    by ``substituted_multi_stage`` before any paid CombatRuntime evaluation.
    The bounded ranking is only a search proposal heuristic, never P3 proof.
    """
    if type(max_packages) is not int or max_packages < 0:
        raise ValueError('invalid source weapon package budget')
    weapon = base['slots'].get('weapon')
    if not weapon or not max_packages:
        return [], {'one_hand_candidates':0,'offhand_candidates':0,'two_hand_candidates':0}
    items=available_items(class_key,level,required_level_policy='observed')
    onehand=[x for x in items if x.slot in ('one_hand','main_hand') and x.weapon_hands==1]
    offhand=[x for x in items if x.slot=='off_hand' and x.weapon_hands!=2]
    twohand=[x for x in items if x.slot=='two_hand' or x.weapon_hands==2 and x.slot in ('main_hand','one_hand')]
    counts={'one_hand_candidates':len(onehand),'offhand_candidates':len(offhand),
            'two_hand_candidates':len(twohand)}
    from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids
    other_ids=[int(v['item_id']) for k,v in base['slots'].items() if k not in ('weapon','offhand')]
    weights=dict(base.get('selection_weights') or {})
    axes=[weights,{'spell_power':1.},{'intellect':1.},{'spirit':1.},
          {'strength':1.},{'agility':1.},{'stamina':1.},{'weapon_dps':1.}]
    def shortlist(rows,limit):
        # Axis-round-robin avoids selecting only the top item under one proxy.
        ranks=[sorted(rows,key=lambda x:(item_score(x,w),int(x.item_level or 0),
                         -int(x.item_id)),reverse=True) for w in axes]
        out=[];seen=set()
        for depth in range(len(rows)):
            for ranking in ranks:
                if depth<len(ranking) and ranking[depth].item_id not in seen:
                    out.append(ranking[depth]);seen.add(ranking[depth].item_id)
                    if len(out)>=limit:return out
        return out
    proposals=[]
    seen=set()
    def consider(swaps):
        key=tuple(sorted(swaps.items()))
        if key in seen:return
        try:
            validate_equipped_item_ids(other_ids+[int(i) for i in swaps.values()])
        except ValueError:
            return
        seen.add(key);proposals.append(swaps)
    if int(weapon.get('weapon_hands') or 0)==2:
        # A real 1H + held-in-offhand is an atomic package, not two legal
        # individual moves from a 2H seed.
        main=shortlist(onehand,max(4,max_packages))
        off=shortlist(offhand,max(4,max_packages))
        for depth in range(len(main)+len(off)-1):
            for i in range(len(main)):
                j=depth-i
                if 0<=j<len(off):
                    consider({'weapon':int(main[i].item_id),'offhand':int(off[j].item_id)})
                    if len(proposals)>=max_packages:return proposals,counts
    else:
        # A 2H move removes the incumbent offhand atomically. The existing
        # single-slot scorer must not reject it as an intermediate illegal set.
        for item in shortlist(twohand,max_packages):
            consider({'weapon':int(item.item_id)})
            if len(proposals)>=max_packages:break
    return proposals,counts



def _source_gear_move_stage(*,stage,class_key,level,slot,item,swaps):
    """Construct a legal source stage before the same paid evaluator runs."""
    if swaps is not None:
        from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
        return substituted_multi_stage(stage=stage,class_key=class_key,
                                       level=level,swaps=swaps)
    new_gear=_gear_replace(stage['gear_policy_result']['winner']['gear'],slot,item)
    return {**stage,'score_s_per_mob':None,
            'paid_candidate_origin':'source_catalogue_slot_coordinate',
            'source_policy_and_gear_reused':True,
            'gear_policy_result':{'winner':{**stage['gear_policy_result']['winner'],
                                            'gear':new_gear}}}



def _source_full_build_key(stage):
    """Full build identity independent of proposal path, scores or timing."""
    winner=stage['gear_policy_result']['winner']
    policy=winner['winner']
    return json.dumps({'allocation':stage['allocation'],
        'gear':sorted((str(slot),int(item['item_id']))
                      for slot,item in winner['gear']['slots'].items()),
        'policy':{key:policy.get(key) for key in
                  ('prefix','fallback','guarded_action','guarded_conditions')}},
        sort_keys=True,separators=(',',':'))



def _unique_source_builds(seed_stage, rows, *, require_full_100mob):
    eligible=[seed_stage]
    for row in rows:
        if row['stage'] is None:
            continue
        status=(row.get('persistent',{}).get('status') if require_full_100mob
                else row['screen'].get('status'))
        if status=='COMPLETE':
            eligible.append(row['stage'])
    return len({_source_full_build_key(stage) for stage in eligible})


def search_persistent_gear_slots(*,class_key,level,seed_stage,rounds=2,
                                 per_slot=2,max_proposals_per_round=40,
                                 screen_mobs=8,finalist_mobs=100,max_finalists=8,
                                 max_cpu_s=50.,max_events=200000,p3_certificate=None,weighted_p3_report=None,
                                 strict_l2_item_effects=False,
                                 allow_unattested_diagnostic=False,
                                 allow_partial_gear_stats=False,
                                 max_weapon_packages_per_round=4):
    if not 1<=rounds<=5 or not 1<=per_slot<=10 or max_cpu_s<=0 or max_events<1 or not 0<=max_weapon_packages_per_round<=max_proposals_per_round:
        raise ValueError('invalid source slot-search budget')
    t0=monotonic();c0=process_time();total_events=0;rows=[];history=[]
    stage=seed_stage
    seed=prepare_candidate(class_key=class_key,level=level,stage=stage,
        strict_l2_item_effects=strict_l2_item_effects,
        allow_partial_gear_stats=allow_partial_gear_stats)
    initial=evaluate_persistent_candidate(seed,level=level,mobs=finalist_mobs,
        max_cpu_s=max_cpu_s,max_total_events=max_events)
    total_events+=int(initial.get('events') or 0)
    if initial['status']!='COMPLETE':
        return {'status':'BLOCKED_SEED','initial':initial,'events':total_events,'cpu_s':process_time()-c0}
    best=initial
    best_screen=None
    for round_id in range(rounds):
        if process_time()-c0>=max_cpu_s or total_events>=max_events:break
        base=stage['gear_policy_result']['winner']['gear']
        package_budget=min(max_weapon_packages_per_round,max_proposals_per_round)
        proposals,legal_counts=_source_slot_proposals(class_key=class_key,level=level,
            base=base,per_slot=per_slot,max_proposals=max_proposals_per_round-package_budget,
            p3_certificate=p3_certificate,weighted_p3_report=weighted_p3_report,seed_stage=stage,
            allow_unattested_diagnostic=allow_unattested_diagnostic)
        packages,package_counts=_source_weapon_package_proposals(
            class_key=class_key,level=level,base=base,max_packages=package_budget)
        # The package moves get a reserved share of the *same* bounded budget;
        # they do not add free attempts or displace all regular slots.
        moves=[{'slot':slot,'item_id':int(item.item_id),'name':item.name,
                'swaps':None,'item':item} for slot,item in proposals]
        moves.extend({'slot':'weapon+offhand','item_id':int(swaps['weapon']),
                      'name':'atomic_weapon_package','swaps':swaps,'item':None}
                     for swaps in packages)
        screened=[]
        for move in moves:
            if process_time()-c0>=max_cpu_s or total_events>=max_events:break
            slot=move['slot'];item=move['item'];swaps=move['swaps']
            started=process_time()
            try:
                variant=_source_gear_move_stage(stage=stage,class_key=class_key,
                    level=level,slot=slot,item=item,swaps=swaps)
                candidate=prepare_candidate(class_key=class_key,level=level,stage=variant,
                    strict_l2_item_effects=strict_l2_item_effects,
                    allow_partial_gear_stats=allow_partial_gear_stats)
                screen=evaluate_persistent_candidate(candidate,level=level,mobs=screen_mobs,
                    max_cpu_s=max(.001,max_cpu_s-(process_time()-c0)),
                    max_total_events=max(1,max_events-total_events))
            except (ValueError,KeyError,RuntimeError) as exc:
                screen={'status':'BLOCKED_CANDIDATE','reason':str(exc),'events':0}
                variant=None
            total_events+=int(screen.get('events') or 0)
            record={'round':round_id+1,'slot':slot,'item_id':move['item_id'],'name':move['name'],
                'swaps':swaps,'screen':screen,'screen_cpu_s':process_time()-started,'stage':variant}
            rows.append(record)
            if screen['status']=='COMPLETE':screened.append(record)
        screened.sort(key=lambda x:(x['screen']['mean_s_per_mob'],x['slot'],x['item_id']))
        # Keep baseline full-horizon result; never accept a 2/8-mob proxy win.
        finalist_results=[]
        for record in screened[:max_finalists]:
            if process_time()-c0>=max_cpu_s or total_events>=max_events:break
            candidate=prepare_candidate(class_key=class_key,level=level,stage=record['stage'],
                strict_l2_item_effects=strict_l2_item_effects,
                allow_partial_gear_stats=allow_partial_gear_stats)
            full=evaluate_persistent_candidate(candidate,level=level,mobs=finalist_mobs,
                max_cpu_s=max(.001,max_cpu_s-(process_time()-c0)),
                max_total_events=max(1,max_events-total_events))
            total_events+=int(full.get('events') or 0)
            record['persistent']=full
            finalist_results.append(record)
        completed=[r for r in finalist_results if r['persistent']['status']=='COMPLETE']
        completed.sort(key=lambda x:(x['persistent']['mean_s_per_mob'],x['slot'],x['item_id']))
        improvement=completed and completed[0]['persistent']['mean_s_per_mob'] < best['mean_s_per_mob']-1e-8
        history.append({'round':round_id+1,'available_per_slot':legal_counts,
                        'proposed':len(moves),'weapon_package_proposed':len(packages),
                        'weapon_package_source_counts':package_counts,'screen_completed':len(screened),
                        'full_completed':len(completed),
                        'best_candidate_s_per_mob':completed[0]['persistent']['mean_s_per_mob'] if completed else None,
                        'improved':bool(improvement)})
        if not improvement:break
        stage=completed[0]['stage'];best=completed[0]['persistent']
        best_screen=completed[0]['screen']['mean_s_per_mob']
    return {'status':'BOUNDED_COORDINATE_SEARCH','initial':initial,'winner':best,
        'winner_stage':stage,'winner_screen_s_per_mob':best_screen,
        'rounds':history,'attempts':len(rows),
        'full_100mob_evaluations':1+sum('persistent' in x for x in rows),
        'events':total_events,'cpu_s':process_time()-c0,'wall_s':monotonic()-t0,
        'unique_full_builds':_unique_source_builds(seed.source_stage,rows,
            require_full_100mob=False),
        'unique_full_100mob_builds':_unique_source_builds(seed.source_stage,rows,
            require_full_100mob=True),
        'weapon_package_attempts':sum(r['swaps'] is not None for r in rows),
        'weapon_package_full_100mob':sum(r['swaps'] is not None and 'persistent' in r for r in rows),
        'global_optimum_proven':False,'formal_checkpoint_accepted':False,
        'p3_l0_priority_used':p3_certificate is not None,
        'diagnostic_only':bool(allow_unattested_diagnostic or allow_partial_gear_stats),
        'strict_l2_item_effects':bool(strict_l2_item_effects),
        'limitations':['bounded candidate shortlist','fixed source policy and talents within each slot swap',
                       'unverified acquisition methods and source actions remain']}
