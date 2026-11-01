from types import SimpleNamespace

import pytest

from src.rulesets.forever.classes.mage import engine as mage
from src.v2.mage_class_model import MageClassModel
from src.v2.analytic_scorer import AnalyticOptions
from src.service.executors import V2RunnerExecutor


def test_server_profile_blizzard_toggle_is_explicit_and_default_off():
    p = mage.CURRENT_TARGET_SERVER_PROFILE
    assert p.blizzard_aoe_leveling_enabled is False
    on = p.with_blizzard_aoe_leveling(True)
    assert on.blizzard_aoe_leveling_enabled is True
    assert on.capabilities()["mage.blizzard_aoe_leveling"] is True
    assert on.key.endswith(":aoe_on")
    assert p.blizzard_aoe_leveling_enabled is False


def test_mage_class_model_fails_closed_when_aoe_capability_is_enabled():
    model = MageClassModel(mage)
    cfg = mage.SimConfig(server_profile=mage.CURRENT_TARGET_SERVER_PROFILE.with_blizzard_aoe_leveling(True))
    with pytest.raises(RuntimeError, match="Refusing to publish the single-target search as an AoE result"):
        model.prepare_level_candidates(20, cfg, options=AnalyticOptions(), beam_width=2, family_keep=1, final_k=2)


def test_service_compiles_blizzard_aoe_optin_only_for_forever_mage():
    job={"request":{"endpoint_mode":"smooth","ruleset":"forever","class_name":"mage",
         "start_level":20,"end_level":20,"forever_build_as_of":"2026-10-02",
         "config":{"workers":1,"mage_blizzard_aoe":True}}}
    plan=V2RunnerExecutor().plan(job)
    assert "--mage-blizzard-aoe" in plan.command

    bad={"request":dict(job["request"], class_name="druid")}
    with pytest.raises(ValueError, match="valid only for forever/mage"):
        V2RunnerExecutor().plan(bad)
