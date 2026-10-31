from dataclasses import dataclass

from src.v2.class_model import CandidateResult, ClassModel, Evaluation, LevelFrontier
from src.v2.decision_result import reports, solve_routes


@dataclass(frozen=True)
class Build:
    tree: str
    points: int


class RouteModel(ClassModel):
    name='fake-hunter'
    def evaluate(self,ctx): return Evaluation(score_s_per_100=100.0)
    def build_key(self,b): return (b.tree,b.points)
    def build_points(self,b): return b.points
    def legal_one_point_transition(self,parent,child):
        return 'p' if child.tree==parent.tree and child.points==parent.points+1 else None
    def route_matches(self,build,definition):
        if definition.get('kind') == 'tree_points':
            return build.tree == definition.get('tree') and build.points >= int(definition.get('minimum',1))
        return super().route_matches(build,definition)


def _candidate(level,tree,score):
    ev=Evaluation(score_s_per_100=float(score),kill_s_per_100=float(score)-20,recovery_s_per_100=10,travel_s_per_100=10)
    return CandidateResult(
        level=level,build=Build(tree,level-9),loadout=None,policy='p',evaluation=ev,
        metadata={'publication_row':{'level':level,'allocation':f'{tree}:{level-9}','talent_family':tree,
                                    'tree_points':{tree:level-9},'score_s_per_100':float(score),
                                    'mobs_per_hour':360000.0/float(score)}})


def test_hunter_declared_routes_are_solved_from_canonical_frontiers_not_publication_subset():
    # All three corridors are legal/reachable. A presentation frontier retaining
    # only the cheapest row would have dropped MM/Survival in the old pipeline.
    frontiers=[]
    for level in range(10,21):
        rows=(
            _candidate(level,'beast_mastery',80+level),
            _candidate(level,'marksmanship',100+level),
            _candidate(level,'survival',120+level),
        )
        frontiers.append(LevelFrontier(level,rows))
    result=solve_routes(frontiers,model=RouteModel(),class_name='hunter',targets=[20])
    target=result.targets[20]
    assert set(target) == {'unconstrained','beast_mastery','marksmanship','survival'}
    assert all(target[name].status == 'available' for name in target)
    route_report,_=reports(result,verified_level_cap=20)
    rows=route_report['targets']['20']['routes']
    assert all(rows[name]['status'] == 'available' for name in rows)
    assert all('declared route not preserved' not in str(rows[name]) for name in rows)


def test_druid_cat_and_bear_remain_distinct_routes_on_same_feral_path():
    # Route semantics differ in publication/scoring profile, not in talent path.
    class DruidRouteModel(RouteModel):
        def route_matches(self,build,definition):
            if definition.get('kind') == 'tree_points':
                return build.tree == definition.get('tree') and build.points >= int(definition.get('minimum',1))
            return super().route_matches(build,definition)
    frontiers=[LevelFrontier(level,(_candidate(level,'feral',100+level),)) for level in range(10,21)]
    result=solve_routes(frontiers,model=DruidRouteModel(),class_name='druid',targets=[20])
    assert result.targets[20]['feral_cat'].status == 'available'
    assert result.targets[20]['feral_bear'].status == 'available'
    assert result.targets[20]['feral_cat'].path.steps[-1].node.talents == result.targets[20]['feral_bear'].path.steps[-1].node.talents

def test_real_hunter_l20_route_definitions_all_match_canonical_endpoint_builds():
    from src.rulesets.forever.classes.hunter import engine as hunter
    from src.v2.class_model import EngineClassModel

    def build_tree(tree, target=11):
        t=hunter.Talents()
        while t.points() < target:
            for name, rule in hunter.TALENT_RULES.items():
                if rule[0] == tree and hunter.legal_add(t, name):
                    t=hunter.add_point(t, name)
                    break
            else:
                raise AssertionError(f'could not build {tree} to {target} points')
        return t

    rows=[]
    trees=('beast_mastery','marksmanship','survival')
    for tree in trees:
        t=build_tree(tree)
        rows.append(CandidateResult(
            level=20,build=t,loadout=None,policy=None,evaluation=Evaluation(score_s_per_100=1000.0),
            metadata={'publication_row':{'level':20,'allocation':hunter.final_allocation(t),
                                        'tree_points':{name:hunter.tree_points(t,name) for name in trees}}},
        ))
    result=solve_routes([LevelFrontier(20,tuple(rows))],model=EngineClassModel(hunter),class_name='hunter',targets=[20])
    assert {name:row.status for name,row in result.targets[20].items()} == {
        'unconstrained':'available','beast_mastery':'available','marksmanship':'available','survival':'available'
    }


def test_i15_generic_constraint_shares_canonical_dp_and_preserves_unconstrained():
    frontiers=[]
    for level in range(10,21):
        frontiers.append(LevelFrontier(level,(
            _candidate(level,'beast_mastery',80+level),
            _candidate(level,'survival',100+level),
        )))
    result=solve_routes(
        frontiers, model=RouteModel(), class_name='hunter', targets=[20],
        constraints={
            'pinned_survival': {
                'endpoint_definition': {'kind':'tree_points','tree':'survival','minimum':11},
                'source':'i15-test',
            },
        },
    )
    unconstrained=result.targets[20]['unconstrained']
    constrained=result.targets[20]['pinned_survival']
    assert unconstrained.status == constrained.status == 'available'
    assert unconstrained.path is not constrained.path
    assert unconstrained.path.cumulative_s <= constrained.path.cumulative_s
    assert constrained.path.steps[-1].node.talents.tree == 'survival'
    # Both decisions live in the same canonical DecisionResult rather than a
    # second publication-side scorer/result object.
    assert result.authority == 'canonical_level_frontier_dp'


def test_i15_generic_constraint_can_pin_reference_progression_prefix():
    frontiers=[]
    for level in range(10,14):
        frontiers.append(LevelFrontier(level,(
            _candidate(level,'beast_mastery',80+level),
            _candidate(level,'survival',100+level),
        )))
    result=solve_routes(
        frontiers, model=RouteModel(), class_name='hunter', targets=[13],
        constraints={
            'reference_prefix': {
                'path_build_keys': {
                    '11': ('survival',2),
                    '12': ('survival',3),
                    '13': ('survival',4),
                },
                'source':'talentsforever_reference',
            },
        },
    )
    path=result.targets[13]['reference_prefix'].path
    assert path is not None
    assert [(s.node.level,s.node.talents.tree) for s in path.steps if s.node.level>=11] == [
        (11,'survival'),(12,'survival'),(13,'survival')
    ]


def test_i15_illegal_or_impossible_generic_constraint_fails_closed():
    frontiers=[LevelFrontier(level,(_candidate(level,'beast_mastery',80+level),)) for level in range(10,13)]
    result=solve_routes(
        frontiers, model=RouteModel(), class_name='hunter', targets=[12],
        constraints={'impossible': {'endpoint_build_key': ('survival',3)}},
    )
    row=result.targets[12]['impossible']
    assert row.status == 'unavailable'
    assert 'eliminates canonical candidates' in str(row.reason)

    import pytest
    with pytest.raises(ValueError, match='restrict at least one'):
        solve_routes(frontiers,model=RouteModel(),class_name='hunter',targets=[12],constraints={'empty':{}})
    with pytest.raises(ValueError, match='collides'):
        solve_routes(frontiers,model=RouteModel(),class_name='hunter',targets=[12],constraints={'unconstrained':{'endpoint_build_key':('beast_mastery',3)}})
