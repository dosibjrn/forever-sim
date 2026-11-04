"""Architecture regression for scenario-owned 2D pack geometry."""
import ast
from pathlib import Path

from src.scenarios.spaced_pulls import SpacedPullLayout
from src.shared.leveling.spaced_pulls import SpacedPullLayout as LegacySpacedPullLayout

ROOT = Path(__file__).resolve().parents[2]


def test_spaced_pull_geometry_is_scenario_owned_with_identity_compatibility():
    canonical = ROOT / "src/scenarios/spaced_pulls.py"
    legacy = ROOT / "src/shared/leveling/spaced_pulls.py"
    assert canonical.is_file()
    legacy_tree = ast.parse(legacy.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(legacy_tree)
    )
    assert any(
        node.module == "src.scenarios.spaced_pulls"
        and any(alias.name == "SpacedPullLayout" for alias in node.names)
        for node in ast.walk(legacy_tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert LegacySpacedPullLayout is SpacedPullLayout

    layout = SpacedPullLayout(3, spacing_yards=20, movement_speed_yards_s=7)
    assert layout.positions_yards[0] == (0.0, 0.0)
    assert layout.positions_yards[1] == (20.0, 0.0)
    assert layout.distance_yards(0, 2) == 20 * 2**0.5
    assert layout.initial_melee_targets() == (0,)
    assert layout.minimum_walk_to_tag_farthest_s == 30 / 7


def test_live_python_consumers_import_scenario_geometry():
    consumers = (
        "src/game/multi_pull.py",
        "src/v2/source_persistent_joint_finalists.py",
        "src/rulesets/forever/classes/druid/mechanics.py",
        "integrations/mythicsim-rust/live_two_world_pulls.py",
    )
    for relative in consumers:
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert "src.scenarios.spaced_pulls" in content, relative
