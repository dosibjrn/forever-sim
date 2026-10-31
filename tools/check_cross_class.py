"""Nine fixed-allocation scorer checks; does not claim optimized/BIS builds."""
import dataclasses
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import game_context
from src.engine_registry import get_engine, reset_engine_cache
from src.v2.spec_matrix import build_matrix
from src.v2.decision_dashboard import _canonical_route_rows


def run(cls):
    game_context.configure('forever', cls)
    reset_engine_cache()
    engine = get_engine()
    family = {'mage':'frost', 'druid':'feral', 'paladin':'protection'}[cls]
    talents = engine.Talents()
    steps = []
    for level in range(10, 61):
        legal = [k for k in engine.TALENT_RULES if engine.legal_add(talents, k)]
        legal.sort(key=lambda k: engine.TALENT_RULES[k][0] != family)
        talents = engine.add_point(talents, legal[0])
        if level in (19,20,39,40,59,60):
            ranks = {k:v for k,v in dataclasses.asdict(talents).items() if v}
            steps.append({'level':level,'talent_ranks':ranks,'allocation':engine.final_allocation(talents)})
    matrix = build_matrix(engine, {'steps':steps}, class_name=cls, route='fixture', target=60)
    endpoint = {'targets':{'60':{'routes':{'fixture':{'status':'available','path':{'steps':steps}}}}}}
    canonical = _canonical_route_rows(cls, endpoint, {'matrices':{'60:fixture':matrix}})
    rows = canonical['60']['routes']['fixture']['rows']
    for row in rows:
        assert row['stat_weights'] and not row.get('stat_weights_error'), row
        assert sum(t['points'] for t in row['talent_trees'].values()) == row['level']-9
        assert row['mobs_per_hour'] > 0
        assert row['gear_stats']['slots']
    output=ROOT/f'docs/validation/CROSS_CLASS_{cls}_v0.11.41.json'
    output.write_text(json.dumps({'scope':'Deterministic legal fixed-allocation contract fixtures; not optimized builds. L40/L60 remain provisional model checks.', 'matrix':matrix,'rows':rows},indent=2)+'\n')
    print(cls,[(r['level'],round(r['mobs_per_hour'],1),r['stat_weights']['reference_stat']) for r in rows])


if __name__ == '__main__':
    run(sys.argv[1])
