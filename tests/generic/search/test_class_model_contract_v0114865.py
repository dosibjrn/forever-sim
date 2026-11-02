from dataclasses import dataclass

from src.v2.class_model import ClassModel, Evaluation, SearchContext
from src.v2.path_dp import LevelNode, solve_path_dp


@dataclass(frozen=True)
class FakeBuild:
    points_: tuple[str, ...]


class FakeClass(ClassModel):
    name = "fake"

    def evaluate(self, ctx):
        return Evaluation(score_s_per_100=float(ctx.metadata.get("score", 100.0)))

    def build_key(self, build):
        return build.points_

    def build_points(self, build):
        return len(build.points_)

    def legal_one_point_transition(self, parent, child):
        if len(child.points_) != len(parent.points_) + 1:
            return None
        if child.points_[:-1] == parent.points_:
            return child.points_[-1]
        return None


def b(*xs):
    return FakeBuild(tuple(xs))


def test_shared_evaluation_contract_is_class_agnostic():
    ev = FakeClass().evaluate(SearchContext(level=20, metadata={"score": 850.0}))
    assert ev.score_s_per_100 == 850.0
    assert ev.seconds_per_mob == 8.5


def test_route_dp_accepts_opaque_builds_through_class_model():
    model = FakeClass()
    pools = {
        11: [LevelNode(11, b("a", "b"), 100.0), LevelNode(11, b("x", "y"), 80.0)],
        12: [LevelNode(12, b("a", "b", "c"), 90.0), LevelNode(12, b("x", "y", "z"), 70.0)],
        13: [LevelNode(13, b("a", "b", "c", "d"), 60.0), LevelNode(13, b("x", "y", "z", "q"), 50.0)],
    }
    out = solve_path_dp(pools, max_respecs=0, weights={11:1,12:1,13:1}, model=model)
    assert [step.node.talents.points_ for step in out.steps] == [
        ("x", "y"), ("x", "y", "z"), ("x", "y", "z", "q")
    ]
    assert out.cumulative_s == 200.0


def test_route_dp_respec_is_generic_and_does_not_require_engine_dataclass():
    model = FakeClass()
    pools = {
        11: [LevelNode(11, b("a", "b"), 10.0)],
        12: [LevelNode(12, b("x", "y", "z"), 1.0)],
    }
    out = solve_path_dp(pools, max_respecs=1, weights={11:1,12:1}, model=model)
    assert out.respecs_used == 1
    assert out.steps[-1].kind == "respec"
    assert out.cumulative_s == 11.0
