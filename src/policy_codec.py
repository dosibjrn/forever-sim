from __future__ import annotations

"""Canonical persisted policy semantics shared by Fast and MC.

Presentation names are never identity.  The compact engine descriptor is the
persisted contract; parsing is strict so an unknown descriptor cannot silently
validate as another rotation.
"""

from src.engine_registry import eng


def normalize_descriptor(desc: str) -> str:
    return (desc or '').replace('Ã','×').replace('â','→').replace('â¤','≤').replace('â¥','≥').strip()


def descriptor(policy: eng.Policy, level: int) -> str:
    return eng.policy_desc(policy, int(level))


def canonical_policy_payload(policy: eng.Policy, level: int) -> dict:
    """Minimal effective identity used by stochastic cache metadata/keys.

    `policy_desc` intentionally omits presentation name and behavior that cannot
    exist yet (e.g. Blink before level 20), so it is a better cache identity
    than serializing the raw dataclass.
    """
    return {'descriptor': descriptor(policy, level)}


def parse_descriptor(desc: str, level: int) -> eng.Policy:
    d = normalize_descriptor(desc)
    if not d or d == 'unscored':
        raise ValueError(f'policy descriptor is not replayable at level {level}: {desc!r}')
    parts = [x.strip() for x in d.split('|') if x.strip()]
    head = parts[0]

    primary_map = {'FBo':'frostbolt','FBa':'fireball','AM':'arcane_missiles','Sc':'scorch'}
    primary = primary_map.get(head)
    scorch_to_stacks = 0
    fireball_block = 0
    scorch_block = 0

    if head.startswith('FBa') and '/Sc' in head:
        primary = 'fireball'
        try:
            lhs, rhs = head.split('/Sc', 1)
            fireball_block = int(lhs[3:])
            scorch_block = int(rhs)
        except Exception as e:
            raise ValueError(f'invalid mixed-Fire policy head: {head!r}') from e
        if fireball_block <= 0 or scorch_block <= 0:
            raise ValueError(f'invalid mixed-Fire block sizes: {head!r}')
    elif head.startswith('Sc×') and '→FBa' in head:
        primary = 'fireball'
        try:
            scorch_to_stacks = int(head.split('×',1)[1].split('→',1)[0])
        except Exception as e:
            raise ValueError(f'invalid legacy Scorch policy head: {head!r}') from e
        if scorch_to_stacks <= 0:
            raise ValueError(f'invalid Scorch stack target: {head!r}')
    elif primary is None:
        raise ValueError(f'unknown policy primary/head: {head!r}')

    kwargs = dict(
        name='replay '+d,
        primary=primary,
        use_fireblast=False,
        use_nova=False,
        use_blink=False,
        use_ice_barrier=False,
        clearcast_am=False,
        fireball_block=fireball_block,
        scorch_block=scorch_block,
        fire_cycle_phase=0,
        nova_cycle_pos=-1,
        pyro_opener=False,
        scorch_to_stacks=scorch_to_stacks,
        fbo_r1_mode='none',
    )
    for token in parts[1:]:
        if token.startswith('Phase='):
            try: kwargs['fire_cycle_phase'] = int(token.split('=',1)[1])
            except Exception as e: raise ValueError(f'invalid Phase token: {token!r}') from e
        elif token.startswith('FNpos='):
            try: kwargs['nova_cycle_pos'] = int(token.split('=',1)[1])
            except Exception as e: raise ValueError(f'invalid FNpos token: {token!r}') from e
        elif token == 'PyroOpen':
            kwargs['pyro_opener'] = True
        elif token.startswith('FBoR1:'):
            mode = token.split(':',1)[1]
            if mode not in {'opener','maintain'}:
                raise ValueError(f'invalid FBoR1 mode: {mode!r}')
            kwargs['fbo_r1_mode'] = mode
        elif token.startswith('FBl≤'):
            kwargs['use_fireblast'] = True
            try: kwargs['fireblast_execute_frac'] = float(token.split('≤',1)[1].rstrip('%')) / 100.0
            except Exception as e: raise ValueError(f'invalid Fire Blast token: {token!r}') from e
        elif token.startswith('FN') and '+step' in token:
            kwargs['use_nova'] = True
            kwargs['nova_rank1'] = token.startswith('FNR1')
            if not (token.startswith('FNR1') or token.startswith('FNmax')):
                raise ValueError(f'invalid Frost Nova token: {token!r}')
            try: kwargs['nova_move_yards'] = float(token.split('+step',1)[1])
            except Exception as e: raise ValueError(f'invalid Frost Nova step: {token!r}') from e
        elif token.startswith('Blink≥'):
            if int(level) < 20:
                raise ValueError(f'Blink descriptor before level 20: {token!r}')
            kwargs['use_blink'] = True
            try: kwargs['blink_min_hp_frac'] = float(token.split('≥',1)[1].rstrip('%')) / 100.0
            except Exception as e: raise ValueError(f'invalid Blink token: {token!r}') from e
        elif token == 'IceBarrier':
            if eng.ice_barrier_rank(int(level)) is None:
                raise ValueError(f'Ice Barrier descriptor before level 40: {token!r}')
            kwargs['use_ice_barrier'] = True
        elif token == 'CC→AM':
            kwargs['clearcast_am'] = True
        else:
            raise ValueError(f'unknown policy token: {token!r}')
    return eng.Policy(**kwargs)
