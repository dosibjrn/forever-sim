from dataclasses import dataclass

from src.v2.class_model import CandidateResult, ClassModel, Evaluation, LevelFrontier
from src.v2.decision_result import reports, solve_routes


@dataclass(frozen=True)
class MageBuild:
    points: int = 31
    ice_lance: int = 1


class MagePublicationModel(ClassModel):
    name = 'mage'
    def evaluate(self, ctx):
        return Evaluation(score_s_per_100=1.0)
    def build_key(self, build):
        return (build.points, build.ice_lance)
    def build_points(self, build):
        return int(build.points)
    def legal_one_point_transition(self, parent, child):
        return None
    def route_matches(self, build, definition):
        return False


def test_canonical_decision_result_keeps_mage_structural_winner_identity_for_listener():
    """Post-.69 replacement for the old runner-overlay authority regression."""
    model=MagePublicationModel()
    ev=Evaluation(
        score_s_per_100=360000.0/170.5,
        kill_s_per_100=1500.0,recovery_s_per_100=500.0,
        travel_s_per_100=(360000.0/170.5)-2000.0,mobs_per_hour=170.5,
    )
    row={
        'level':40,'allocation':'structural ice lance','talent_ranks':{'ice_lance':1},
        'rotation':'Frozen/FoF→IL(move)','policy':'Frozen/FoF→IL(move)',
        **ev.published_fields(),
    }
    frontier=LevelFrontier(40,(CandidateResult(
        level=40,build=MageBuild(),loadout=None,policy=row['policy'],evaluation=ev,
        metadata={'source':'test-structural','publication_row':row},
    ),))
    result=solve_routes([frontier],model=model,class_name='mage',targets=[40])
    route_report,_=reports(result,verified_level_cap=60)
    published=route_report['targets']['40']['routes']['unconstrained']['path']
    assert published['talent_ranks'].get('ice_lance') == 1
    assert published['mobs_per_hour'] == 170.5
    assert 'Frozen/FoF' in published['policy']
    assert published['source'] == 'canonical_decision_result'
