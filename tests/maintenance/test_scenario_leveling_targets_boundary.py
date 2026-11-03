"""Scenario-owned Classic-proxy leveling target boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_classic_proxy_target_curve_has_one_scenario_owner_and_legacy_identity_alias():
    from src.scenarios import leveling_targets
    from src.shared.leveling import objective as legacy

    assert legacy.MOB_BASE_HP is leveling_targets.MOB_BASE_HP
    assert legacy.mob_hp is leveling_targets.mob_hp
    assert legacy.representative_hp is leveling_targets.representative_hp
    assert [leveling_targets.representative_hp(level) for level in range(1, 12)] == [
        42., 55., 71., 86., 102., 120., 137., 156., 176., 198., 222.
    ]
    assert leveling_targets.representative_hp(20) == 484.
    source = (ROOT / "src/scenarios/leveling_targets.py").read_text(encoding="utf-8")
    assert "CMaNGOS/mangoszero" in source
    assert "NOT verified Forever" in source


def test_live_leveling_target_consumers_import_the_scenario_boundary():
    consumers = (
        "src/game/checkpoint_pipeline.py",
        "src/game/data/forever/source_checkpoint_l0.py",
        "src/v2/generic_backend.py",
        "src/v2/source_legal_beam.py",
        "src/v2/source_legal_level_corridor.py",
        "src/v2/source_multi_pull_joint.py",
        "src/v2/source_persistent_joint_finalists.py",
        "src/v2/source_stateful_budgeted.py",
        "src/rulesets/forever/classes/druid/mechanics.py",
        "src/rulesets/forever/classes/hunter/mechanics.py",
        "src/rulesets/forever/classes/paladin/mechanics.py",
        "src/rulesets/forever/classes/paladin/event_replay.py",
        "tools/wf299_100_mob_continuity_probe.py",
    )
    for relative in consumers:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "src.scenarios.leveling_targets" in source, relative

def test_legacy_objective_contains_no_second_target_curve_copy():
    source = (ROOT / "src/shared/leveling/objective.py").read_text(encoding="utf-8")
    assert "from src.scenarios.leveling_targets import MOB_BASE_HP, mob_hp, representative_hp" in source
    assert "MOB_BASE_HP =" not in source
    assert "def representative_hp(" not in source
    assert "def mob_hp(" not in source
