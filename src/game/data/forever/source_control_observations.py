"""Strict grammar for externally observed source control facts.

A rendered web transcription is provenance, NOT verified source HTML or
unrestricted checkpoint proof. Parsing must fail closed on extra effects.
"""
from __future__ import annotations
import re

_COST=re.compile(r'^(\d+(?:\.\d+)?) (Mana|Rage|Energy)$',re.I)
_DURATION=re.compile(r'^Stuns the target for (\d+(?:\.\d+)?) sec\.$',re.I)
_CAST=re.compile(r'^(Instant|\d+(?:\.\d+)? sec cast)$',re.I)
_COOLDOWN=re.compile(r'^(\d+(?:\.\d+)?) (sec|min)$',re.I)
_GCD=re.compile(r'^(\d+(?:\.\d+)?) sec$',re.I)


def parse_control_observation(obs:dict)->dict:
    if not isinstance(obs,dict) or any(k not in obs for k in ('cost','cast','cooldown','gcd','effect_text','required_mode_id','form_requirement')):
        raise ValueError('SOURCE_CONTROL_OBSERVATION_INCOMPLETE')
    cost=_COST.fullmatch(str(obs['cost']));duration=_DURATION.fullmatch(str(obs['effect_text']))
    cast=_CAST.fullmatch(str(obs['cast']));cooldown=_COOLDOWN.fullmatch(str(obs['cooldown']));gcd=_GCD.fullmatch(str(obs['gcd']))
    mode=str(obs['required_mode_id']).strip()
    # Compare supplied mode to the observed form name. Do not infer or invent
    # another legal form when text and canonical IR disagree.
    form=(mode.replace('_',' ').title()+' Form').lower()
    if not all((cost,duration,cast,cooldown,gcd)) or not mode or form not in str(obs['form_requirement']).lower():
        raise ValueError('SOURCE_CONTROL_UNPARSED_TOOLTIP')
    kind='stun'
    values={
        'cost_resource':cost.group(2).lower(),'cost_amount':float(cost.group(1)),
        'cast_time_s':0.0 if cast.group(1)=='Instant' else float(str(obs['cast']).split()[0]),
        'gcd_s':float(gcd.group(1)),
        'cooldown_s':float(cooldown.group(1))*(60 if cooldown.group(2)=='min' else 1),
        'effect_kind':kind,'duration_s':float(duration.group(1)),
        'required_mode_id':mode,
    }
    if not (0<values['duration_s']<=120 and 0<=values['cost_amount']<=1e5
            and 0<=values['cast_time_s']<=120 and 0<=values['gcd_s']<=10
            and 0<=values['cooldown_s']<=3600):
        raise ValueError('SOURCE_CONTROL_VALUES_OUT_OF_RANGE')
    return values
