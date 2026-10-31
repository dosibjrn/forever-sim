"""Reproduce WF256 source-legal Paladin L20 independent search (not OG-seeded).

Budget is explicit and bounded; this is not a global-optimum certificate.
"""
from __future__ import annotations
import json
from pathlib import Path
from src.v2.source_legal_beam import search_source_legal_beam

OUT=Path(__file__).resolve().parents[1]/'WF256_SEARCH.json'

def run():
    return search_source_legal_beam(class_key='paladin',level=20,pulls=3,
        max_allocations=64,screening_gear_count=3,finalists=7,
        policy_cap=48,beam_width=5)

if __name__=='__main__':
    r=run();OUT.write_text(json.dumps(r,indent=2)+'\n')
    w=r['independent_winner']
    print(json.dumps({'winner_s_per_mob':w['seconds_per_mob'],
        'talents':w['talent_allocation'],
        'evaluated_allocations':r['total_independent_evaluated_allocations'],
        'valid_policy_evaluations':r['valid_policy_evaluations'],
        'elapsed_s':r['elapsed_s']},indent=2))
