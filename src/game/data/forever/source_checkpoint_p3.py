"""Source-bounded item L0 inventory for one class/level/profile checkpoint.

An item gets a source stat-domain vector or an explicit unknown/zero-context
classification. L0 is an *ordering prior*, not an invented damage model. Every
legal catalogue row is retained in the certificate, including proc-only relics.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Mapping

from src.rulesets.forever.items.runtime_selection import (
    BODY_SLOTS, available_items, catalogue_path, item_vector,
)


_DISPLAY_SOURCE_STATS = ('hit', 'crit', 'defense', 'dodge')
_EXTRAS_ALREADY_BRIDGED = frozenset(('spldmg',))


def source_item_slots(item) -> tuple[str, ...]:
    """Equipment slots, not a list of optimizer-selected equipment."""
    raw = str(item.slot)
    if raw in BODY_SLOTS or raw in ('shirt', 'relic'):
        return (raw,)
    if raw == 'finger':
        return ('ring1', 'ring2')
    if raw == 'trinket':
        return ('trinket1', 'trinket2')
    if raw in ('one_hand', 'main_hand', 'two_hand'):
        return ('weapon',)
    if raw == 'off_hand':
        return ('offhand',)
    if raw in ('ranged','thrown'):
        return ('wand',) if item.weapon_type == 'wand' else ('ranged',)
    if raw == 'tabard':
        return ('tabard',)
    # Do not silently drop new catalogue slot types.
    raise ValueError(f'P3_UNRECOGNIZED_ITEM_SLOT:{raw}:{item.item_id}')


def source_item_l0(item) -> dict:
    from src.rulesets.forever.items.source_equipment_semantics import semantic_for_item
    semantic=semantic_for_item(item)
    if semantic and semantic.equip_semantics=='NON_EQUIPPABLE_RUNE_LEARNING_ITEM':
        raise ValueError('P3_NON_EQUIPPABLE_SOURCE_ITEM')
    vector = {k:float(v) for k,v in item_vector(item).items()}
    typed_effects=[]
    if semantic:
        for kind,stat,multiplier in semantic.typed_effects:
            if kind=='multiply_actor_stat':
                vector[stat+'_percent']=vector.get(stat+'_percent',0.)+100.*(multiplier-1.)
            elif kind=='add_actor_stat':
                vector[stat]=vector.get(stat,0.)+multiplier
            else:raise ValueError('P3_UNKNOWN_TYPED_ITEM_EFFECT')
            typed_effects.append({'kind':kind,'stat':stat,
                                  'multiplier' if kind=='multiply_actor_stat' else 'amount':multiplier,
                                  'source_url':semantic.source_url,'source_scope':semantic.source_scope})
        for kind,stat,amount,environments in semantic.conditional_effects:
            typed_effects.append({'kind':kind,'stat':stat,'amount':amount,
                'environments':list(environments),'source_url':semantic.source_url,
                'source_scope':semantic.source_scope,
                'conditional_context':'requires_explicit_environment_tag'})
    # The canonical catalogue stores raw display-unit item stats, not TBC
    # level-scaled ratings. Preserve the raw values for the sourced adapter.
    vector.update({stat:float(getattr(item,stat) or 0.) for stat in _DISPLAY_SOURCE_STATS})
    from src.rulesets.forever.items.source_numeric_extras import modeled_source_numeric_extras,NUMERIC_EXTRA_TO_ACTOR_STAT
    vector.update(modeled_source_numeric_extras(item))
    if any(not isfinite(v) for v in vector.values()):
        raise ValueError(f'P3_NONFINITE_ITEM_STAT:{item.item_id}')
    unknown=[]
    if float(getattr(item,'defense',0.) or 0.):
        unknown.append('partial_defense_skill_effect_parry_block_incoming_crit_unmodeled')
    # Some catalogue raw columns encode a conditional item's *maximum*
    # possible resistance (2 base + 4 biome bonus). Count the typed source
    # once, not as five separate unknown 6-point effects or five free +6s.
    resist_source_covered=bool(semantic and any(
        kind=='add_actor_stat' and stat=='resistance_all' for kind,stat,_ in semantic.typed_effects))
    conditional_amount=sum(amount for _,stat,amount,_ in
        (semantic.conditional_effects if semantic else ()) if stat=='resistance_all')
    unconditional_amount=sum(value for kind,stat,value in
        (semantic.typed_effects if semantic else ())
        if kind=='add_actor_stat' and stat=='resistance_all')
    raw_resistance_keys={'arcres','firres','frores','holres','natres','shares','shadowres'}
    for name,value in sorted(item.extra_stats.items()):
        covered=(resist_source_covered and name in raw_resistance_keys
                 and float(value or 0.)==unconditional_amount+conditional_amount)
        if name not in _EXTRAS_ALREADY_BRIDGED and name not in NUMERIC_EXTRA_TO_ACTOR_STAT and float(value or 0.) and not covered:
            unknown.append('unmodeled_source_extra:'+name)
    # A listview does not include the full on-equip/on-use tooltip. A relic or
    # trinket may have a non-stat effect even when all numerical fields are 0.
    if item.slot in ('relic', 'trinket') and not typed_effects:
        # A sourced visual-only, combat-disabled use has no effect on the
        # kill/recovery/survival clock. Other trinket effects remain UNKNOWN.
        if not (semantic and semantic.equip_semantics=='EQUIPPABLE_NONCOMBAT_USE'):
            unknown.append('item_effect_tooltip_not_typed')
    nonzero = any(v != 0 for v in vector.values())
    if not nonzero and item.slot not in ('shirt','tabard') and not unknown:
        unknown.append('no_numeric_stats_effect_unverified')
    return {'numeric_source_domains':vector,'typed_source_effects':typed_effects,
            'unresolved_effects':unknown,
            'contextual_zero':item.slot in ('shirt','tabard') and not nonzero and not unknown,
            'l0_assessed':True,
            'l2_effect_fully_supported':not unknown,
            'comparison_unit':'SOURCE_ITEM_STAT_DOMAINS_NOT_SECONDS_PER_MOB'}


def checkpoint_item_l0(*,class_key:str,level:int,profile:str='unrestricted',
                       use_runes:bool=False,required_level_policy:str='observed') -> dict:
    if not class_key or not 1 <= int(level) <= 60 or not profile:
        raise ValueError('P3_INVALID_CHECKPOINT')
    if profile!='unrestricted':
        raise ValueError('P3_SPEC_PROFILE_REQUIRES_EXPLICIT_EQUIPMENT_RULES')
    if use_runes:
        raise ValueError('P3_RUNE_EQUIPMENT_EFFECTS_NOT_SOURCED')
    from src.rulesets.forever.items.source_equipment_semantics import ledger_path
    path=Path(catalogue_path()).resolve()
    if not path.is_file():
        raise ValueError('P3_MISSING_CANONICAL_ITEM_CATALOGUE')
    rows=available_items(class_key,level,required_level_policy=required_level_policy)
    if not rows:
        raise ValueError('P3_NO_SOURCE_LEGAL_ITEMS')
    items=[]; by_slot=defaultdict(list)
    seen=set()
    for item in rows:
        iid=int(item.item_id)
        if iid in seen:raise ValueError('P3_DUPLICATE_ITEM_ID')
        seen.add(iid)
        slots=source_item_slots(item)
        l0=source_item_l0(item)
        record={'item_id':iid,'name':item.name,'catalogue_slot':item.slot,
            'slots':list(slots),'required_level':item.required_level,
            'required_level_origin':item.required_level_origin,
            'source_url':item.source_url,'fetch_status':item.fetch_status,
            'source_identity_origin':item.identity_origin,
            **l0}
        items.append(record)
        for slot in slots:by_slot[slot].append(record)
    # Every item remains in the slot frontier; only paid candidates are
    # budget-pruned. Axis round-robin supplies alternatives to one role weight.
    slot_frontiers={}
    for slot,records in sorted(by_slot.items()):
        axes=sorted({k for r in records for k,v in r['numeric_source_domains'].items() if v})
        ordered=[];chosen=set()
        rankings=[sorted(records,key=lambda r:(-r['numeric_source_domains'].get(axis,0.),r['item_id']))
                  for axis in axes]
        rankings.append(sorted(records,key=lambda r:(-bool(r['unresolved_effects']),r['item_id'])))
        for depth in range(len(records)):
            for ranking in rankings:
                if depth < len(ranking):
                    iid=ranking[depth]['item_id']
                    if iid not in chosen:chosen.add(iid);ordered.append(iid)
        if len(ordered)!=len(records):raise AssertionError('P3_FRONTIER_INCOMPLETE')
        slot_frontiers[slot]={'legal_item_count':len(records),
            'priority_item_ids':ordered,
            'numeric_axes':axes,
            'unresolved_effect_items':sum(bool(r['unresolved_effects']) for r in records)}
    from src.rulesets.forever.items.runtime_selection import _source_class_profile
    profile_data=_source_class_profile(class_key)
    from src.rulesets.forever.items.runtime_selection import source_class_item_membership_verified
    membership_verified=source_class_item_membership_verified(class_key,path)
    required_slots=set(profile_data.get('required_fillable_slots',())) if profile_data else set()
    missing_slots=sorted(required_slots-set(slot_frontiers))
    return {'checkpoint':{'class_key':class_key,'level':int(level),'profile':profile,
                          'use_runes':use_runes,'required_level_policy':required_level_policy},
            'catalogue_sha256':sha256(path.read_bytes()).hexdigest(),
            'equipment_semantics_sha256':sha256(ledger_path().read_bytes()).hexdigest(),
            'catalogue_path':str(path),
            'legal_item_count':len(items),'l0_assessed_count':sum(r['l0_assessed'] for r in items),
            'unknown_effect_item_count':sum(bool(r['unresolved_effects']) for r in items),
            'source_items':items,'slot_frontiers':slot_frontiers,
            'source_membership_verified':membership_verified,
            'missing_required_slots':missing_slots,
            'p3_pass':membership_verified and not missing_slots
                and len(items)==sum(r['l0_assessed'] for r in items) and all(
                len(v['priority_item_ids'])>0 for v in slot_frontiers.values()),
            'limitations':['Item L0 is a stat-domain opportunity prior, not L2 execution',
                'Unmodeled procs, relics, and partial Defense mechanisms remain explicitly uncertain',
                'Catalogue observed-level source does not prove individual loot possession']}


def _p3_membership_state(certificate:Mapping) -> tuple[bool,bool]:
    """Attested upstream membership and a complete L0 frontier are distinct."""
    attested=bool(certificate.get('source_membership_verified'))
    return attested, bool(certificate.get('p3_pass')) and attested


def verify_checkpoint_item_l0(certificate:Mapping,*,class_key:str,level:int,
                              allow_unattested_diagnostic:bool=False) -> dict:
    """Verify the entire CURRENT candidate pool, not its upstream completeness.

    The opt-in diagnostic validates all available item IDs and L0 vectors but
    does not turn an unverified source universe into an accepted P3 gate.
    """
    scope=certificate.get('checkpoint') or {}
    attested,p3_pass=_p3_membership_state(certificate)
    if (scope.get('class_key')!=class_key or scope.get('level')!=level
        or scope.get('profile')!='unrestricted' or scope.get('use_runes') is not False
        or scope.get('required_level_policy')!='observed'
        or (not allow_unattested_diagnostic and not p3_pass)):
        raise ValueError('P3_CERTIFICATE_CHECKPOINT_MISMATCH')
    from src.rulesets.forever.items.source_equipment_semantics import ledger_path
    path=Path(catalogue_path())
    if sha256(ledger_path().read_bytes()).hexdigest()!=certificate.get('equipment_semantics_sha256'):
        raise ValueError('P3_STALE_EQUIPMENT_SEMANTICS_SHA')
    if sha256(path.read_bytes()).hexdigest()!=certificate.get('catalogue_sha256'):
        raise ValueError('P3_STALE_CATALOGUE_SHA')
    live={int(x.item_id):x for x in available_items(class_key,level,required_level_policy='observed')}
    published={int(x['item_id']):x for x in certificate.get('source_items',())}
    if set(live)!=set(published) or len(published)!=len(certificate['source_items']):
        raise ValueError('P3_INCOMPLETE_OR_DUPLICATE_ITEM_UNIVERSE')
    for iid,item in live.items():
        if (published[iid]['numeric_source_domains']!=source_item_l0(item)['numeric_source_domains']
            or published[iid]['typed_source_effects']!=source_item_l0(item)['typed_source_effects']
            or published[iid]['unresolved_effects']!=source_item_l0(item)['unresolved_effects']):
            raise ValueError('P3_TAMPERED_ITEM_VECTOR')
    for slot,record in certificate['slot_frontiers'].items():
        actual={iid for iid,x in published.items() if slot in x['slots']}
        ids=record['priority_item_ids']
        if set(ids)!=actual or len(ids)!=len(actual):
            raise ValueError('P3_SLOT_FRONTIER_INCOMPLETE')
    return {'diagnostic_only':not attested,
            'p3_pass':p3_pass,
            'assessed_count':len(published),'slot_count':len(certificate['slot_frontiers'])}
