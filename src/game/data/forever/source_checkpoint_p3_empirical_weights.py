"""Measured, build-conditional L0 stat contributions from real 100-mob swaps.

This is a regularized empirical proxy, NOT a damage formula or a guarantee of
Top5 correctness. Missing effects and unidentifiable axes stay UNKNOWN.
"""
from __future__ import annotations
from collections import defaultdict
from math import isfinite
import numpy as np
from src.game.data.forever.source_checkpoint_p3_weights import _features
from src.rulesets.forever.items.runtime_selection import available_items


def fit_swap_weights(*,stage,results,baseline_s_per_mob,class_key,level):
    if not isfinite(float(baseline_s_per_mob)) or baseline_s_per_mob<=0:
        raise ValueError('P3_INVALID_BASELINE')
    legal={int(i.item_id):i for i in available_items(class_key,level,required_level_policy='observed')}
    equipped={s:int(v['item_id']) for s,v in stage['gear_policy_result']['winner']['gear']['slots'].items()}
    # Explicit zero feature vector for an empty slot, not a zero *effect* item.
    def delta_for(swaps):
        delta=defaultdict(float)
        for slot,new_id in swaps.items():
            if int(new_id) not in legal:raise ValueError('P3_UNSOURCED_ITEM_IN_TRAINING')
            old=legal.get(equipped.get(slot))
            if old:
                for k,v in _features(old).items():delta[k]-=float(v)
            for k,v in _features(legal[int(new_id)]).items():delta[k]+=float(v)
        return {k:v for k,v in delta.items() if abs(v)>1e-12}
    train=[]
    for row in results:
        r=row['result']
        if r.get('status')!='COMPLETE' or r.get('evaluation_source')=='EXACT_BASELINE_REUSE_NO_NEW_100MOB':continue
        if row.get('unresolved_effects'):continue
        score=float(r['mean_s_per_mob'])
        if not isfinite(score) or score<=0:continue
        train.append((row,delta_for(row['swaps']),float(baseline_s_per_mob)-score))
    axes=sorted({k for _,d,_ in train for k in d})
    if len(train)<max(8,len(axes)):
        return {'status':'INSUFFICIENT_MEASURED_ITEM_SWAPS','n':len(train),'axes':axes,
                'weights':{},'per_item':[]}
    X=np.array([[d.get(k,0.) for k in axes] for _,d,_ in train],dtype=float)
    y=np.array([v for _,_,v in train],dtype=float)
    scale=np.maximum(1.,np.quantile(np.abs(X),.9,axis=0))
    Z=X/scale
    n=len(y);folds=np.arange(n)%min(5,n)
    # Fold selection is deterministic and based only on paid, complete 100mob.
    candidates=(.01,.1,1.,10.,100.)
    cv=[]
    for lam in candidates:
        err=[]
        for fold in sorted(set(folds)):
            a=Z[folds!=fold];b=y[folds!=fold]
            w=np.linalg.solve(a.T@a+lam*np.eye(len(axes)),a.T@b)
            err.extend((y[folds==fold]-Z[folds==fold]@w).tolist())
        cv.append((float(np.mean(np.abs(err))),lam))
    mae,lam=min(cv)
    w=np.linalg.solve(Z.T@Z+lam*np.eye(len(axes)),Z.T@y)/scale
    pred=X@w;rmse=float(np.sqrt(np.mean((pred-y)**2)))
    support=np.sum(np.abs(X)>1e-10,axis=0)
    weights={k:{'weight_s_saved_per_mob_per_raw_unit':float(w[i]) if support[i]>=2 else None,
                'status':'EMPIRICAL_100MOB_SWAP_RIDGE_PROXY_NONLINEAR_UNCERTAINTY'
                         if support[i]>=2 else 'UNIDENTIFIABLE_FROM_MEASURED_SWAPS',
                'independent_nonzero_swaps':int(support[i]),'source':'same_build_same_recovery_100mob_swaps'}
             for i,k in enumerate(axes)}
    per_item=[]
    for (row,d,observed),prediction in zip(train,pred):
        parts={k:float(d[k]*w[axes.index(k)]) if support[axes.index(k)]>=2 else None for k in d}
        per_item.append({'slot':row['slot'],'item_id':row['item_id'],
            'actual_improvement_s_per_mob':observed,'proxy_improvement_s_per_mob':float(prediction),
            'unexplained_residual_s_per_mob':float(observed-prediction),
            'stat_deltas':d,'stat_contributions_s_per_mob':parts,
            'source_url':row['source_url']})
    return {'status':'MEASURED_100MOB_REGULARIZED_NONLINEAR_UNCERTAINTY',
            'method':'source_item_delta_features_to_paid_100mob_ridge_zero_intercept',
            'n':n,'axes':axes,'weights':weights,'cv_mae_s_per_mob':mae,
            'in_sample_rmse_s_per_mob':rmse,'regularization':lam,
            'limitations':['discrete kill thresholds and stat interactions mean weights are only a local proxy',
                'unmeasured or untyped item effects are not assigned zero value',
                'coefficients are not a proof of strongest global item ranking'],
            'per_item':per_item}


def rank_all_legal_items_with_proxy(*,stage,model,class_key,level,paired_offhand_weapon_id):
    """Score every legal item with paid-100mob-trained *known* contributions.

    The proxy does not silently zero unmeasured stats, unknown procs, or the
    mandatory weapon change for an offhand in a two-hand context.
    """
    from src.game.data.forever.source_checkpoint_p3 import source_item_l0,source_item_slots
    from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids
    from src.rulesets.forever.items.runtime_selection import catalogue_path
    import sqlite3
    legal={int(i.item_id):i for i in available_items(class_key,level,required_level_policy='observed')}
    # Load source availability *once*. Full named-gear auditing for every item
    # used to reload the entire catalogue and hash it ~2,000 times, taking
    # minutes/hours. These source/legal fast filters are conservative; final
    # Top5 candidates are separately checked by the full source audit.
    with sqlite3.connect(f'file:{catalogue_path().resolve()}?mode=ro',uri=True) as db:
        has_source={int(row[0]) for row in db.execute('SELECT DISTINCT item_id FROM item_sources')}
    equipped={s:int(v['item_id']) for s,v in stage['gear_policy_result']['winner']['gear']['slots'].items()}
    byslot=defaultdict(list)
    for item in legal.values():
        for slot in source_item_slots(item):
            swaps={slot:int(item.item_id)}
            if slot=='offhand' and slot not in equipped:
                swaps={'weapon':int(paired_offhand_weapon_id),'offhand':int(item.item_id)}
            if any(int(iid) not in has_source for iid in swaps.values()):continue
            final_ids={**equipped,**swaps}
            if len(final_ids)!=len(set(final_ids)):
                raise AssertionError('P3_DUPLICATE_SLOT_KEYS')
            if 'offhand' in final_ids and legal[int(final_ids['weapon'])].weapon_hands==2:
                continue
            try:validate_equipped_item_ids(final_ids.values())
            except ValueError:continue
            delta=defaultdict(float)
            for name,iid in swaps.items():
                if name in equipped:
                    for stat,val in _features(legal[equipped[name]]).items():delta[stat]-=float(val)
                for stat,val in _features(legal[int(iid)]).items():delta[stat]+=float(val)
            parts=[];unknown=[];score=0.
            for stat,amount in sorted(delta.items()):
                if abs(amount)<1e-10:continue
                w=model['weights'].get(stat)
                weight=w.get('weight_s_saved_per_mob_per_raw_unit') if w else None
                if weight is None:
                    unknown.append({'stat':stat,'amount':amount,'reason':w['status'] if w else 'NO_MEASURED_AXIS'})
                else:
                    contribution=float(amount*weight);score+=contribution
                    parts.append({'stat':stat,'amount':amount,'weight':weight,
                                  'contribution_s_saved_per_mob':contribution})
            effects=source_item_l0(item)['unresolved_effects']
            byslot[slot].append({'item_id':int(item.item_id),'name':item.name,
                'source_url':item.source_url,'swaps':swaps,
                'known_proxy_improvement_s_per_mob':score,
                'stat_contributions':parts,'unidentified_stats':unknown,
                'unresolved_source_effects':effects,
                'full_proxy_certainty':not unknown and not effects})
    return {slot:{'evaluated_legal_equipment_packages':len(rows),
        'known_component_top5':sorted(rows,key=lambda r:(-r['known_proxy_improvement_s_per_mob'],
            len(r['unidentified_stats'])+len(r['unresolved_source_effects']),r['item_id']))[:5],
        'unidentified_item_count':sum(not r['full_proxy_certainty'] for r in rows),
        'ranking_uncertainty':'unknown channels and discrete stat thresholds; measured swaps supersede proxy'}
        for slot,rows in sorted(byslot.items())}
