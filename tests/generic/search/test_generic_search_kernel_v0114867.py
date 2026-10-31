from dataclasses import dataclass

from src.v2.class_model import ClassModel, Evaluation, SearchContext
from src.v2.search_kernel import SearchParent, evaluate_candidate, search_level


@dataclass(frozen=True)
class Build:
    points: tuple[str, ...]


class FakeClass(ClassModel):
    name = "fake"

    def get_talent_candidates(self, ctx):
        # Two parents can deliberately reach the same child; kernel must retain
        # deterministic first-parent-wins behavior without inspecting Build.
        if ctx.level == 11:
            return (Build(ctx.build.points + ("x",)), Build(ctx.build.points + ("y",)))
        return (Build(ctx.build.points + ("z",)),)

    def get_rotation_candidates(self, ctx):
        return ("slow", "fast")

    def optimize_policy(self, ctx):
        return ctx.policy

    def evaluate(self, ctx):
        base = 100.0 + 10.0 * len(ctx.build.points)
        if ctx.policy == "fast":
            base -= 20.0
        return Evaluation(
            score_s_per_100=base,
            kill_s_per_100=base - 10.0,
            recovery_s_per_100=5.0,
            travel_s_per_100=5.0,
            diagnostics={"policy": ctx.policy, "build": ctx.build.points},
        )

    def build_key(self, build):
        return build.points

    def build_points(self, build):
        return len(build.points)

    def legal_one_point_transition(self, parent, child):
        if len(child.points) != len(parent.points) + 1:
            return None
        if child.points[:-1] != parent.points:
            return None
        return child.points[-1]


def test_evaluate_candidate_uses_generic_rotation_hook_and_shared_result():
    model = FakeClass()
    result = evaluate_candidate(model, SearchContext(level=11, build=Build(("a", "b"))))
    assert result.policy == "fast"
    assert result.evaluation.score_s_per_100 == 100.0
    assert result.evaluation.timing_consistent is True


def test_search_level_expands_opaque_builds_and_adds_weighted_cost():
    model = FakeClass()
    out = search_level(
        model,
        11,
        [SearchParent(Build(("a",)), 7.0, "parent")],
        level_weight=2.0,
    )
    assert out.generated_count == 2
    assert [c.transition_label for c in out.candidates] == ["x", "y"]
    assert all(c.result.policy == "fast" for c in out.candidates)
    # len(build)=2 -> base 120, fast 100; 7 + 2*100
    assert [c.cumulative_s for c in out.candidates] == [207.0, 207.0]
    assert all(c.parent.payload == "parent" for c in out.candidates)


def test_search_level_first_parent_wins_when_build_keys_collide():
    class MergeClass(FakeClass):
        def get_talent_candidates(self, ctx):
            return (Build(("shared",)),)

        def legal_one_point_transition(self, parent, child):
            return "shared"

    model = MergeClass()
    first = SearchParent(Build(tuple()), 1.0, "first")
    second = SearchParent(Build(("other",)), 99.0, "second")
    out = search_level(model, 10, [first, second])
    assert out.generated_count == 1
    assert out.candidates[0].parent.payload == "first"
    assert out.candidates[0].cumulative_s < 99.0


def test_generic_kernel_owns_policy_statweight_gear_fixed_point_for_new_plugins():
    class GearClass(FakeClass):
        def initialize_item_options(self, ctx):
            return "starter"

        def evaluate(self, ctx):
            # upgraded gear is genuinely faster; policy remains plugin-owned
            total = 80.0 if ctx.loadout == "upgrade" else 120.0
            return Evaluation(
                score_s_per_100=total,
                kill_s_per_100=total - 10.0,
                recovery_s_per_100=5.0,
                travel_s_per_100=5.0,
                diagnostics={"gear": ctx.loadout, "policy": ctx.policy},
            )

        def stat_weights(self, ctx, evaluation):
            return {"power": 2.0 if ctx.loadout == "starter" else 1.0}

        def optimize_gear(self, ctx, stat_weights):
            return "upgrade" if stat_weights.get("power", 0.0) > 1.5 else ctx.loadout

    result = evaluate_candidate(
        GearClass(), SearchContext(level=20, build=Build(("a",))), derive_stat_weights=True
    )
    assert result.loadout == "upgrade"
    assert result.evaluation.score_s_per_100 == 80.0
    assert result.metadata["fixed_point_owner"] == "generic_search_kernel"
    assert result.metadata["fixed_point_converged"] is True
    assert result.metadata["fixed_point_iterations"] == 2
    assert result.stat_weights == {"power": 1.0}
