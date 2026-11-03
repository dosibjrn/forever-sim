from __future__ import annotations

import builtins
import sys

import pytest

from tools import wf_gate
from tools import wf_gate_p1_live


@pytest.mark.parametrize(
    ("class_key", "level", "spec"),
    [
        ("druid", 60, "balance"),
        ("mage", 40, "frost"),
    ],
)
def test_p1_formal_provider_blocks_before_gameir_or_source_db(
    monkeypatch, tmp_path, class_key, level, spec
):
    original_import = builtins.__import__
    attempted_gameir_imports = []

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith(("src.game", "src.v2")):
            attempted_gameir_imports.append(name)
            raise AssertionError(
                "Formal P1 must not fall back to Forever GameIR/source legality"
            )
        return original_import(name, globals, locals, fromlist, level)

    def forbidden_legacy_helper(*args, **kwargs):
        pytest.fail("Formal P1 called a legacy GameIR/source-inventory helper")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(wf_gate_p1_live, "audit_inventory", forbidden_legacy_helper)
    monkeypatch.setattr(wf_gate_p1_live, "_source_rows", forbidden_legacy_helper)
    before_path = list(sys.path)

    report = wf_gate._run_live_gate(
        tmp_path,
        class_key,
        level,
        spec,
        "P1",
        wf_gate_p1_live.P1_DEFAULT_SCENARIO,
    )

    assert report["status"] == "BLOCKED"
    assert report["reasons"] == [
        "NATIVE_P1_ACTION_ENUMERATION_UNAVAILABLE",
        "NATIVE_P1_ROLE_OBSERVATIONS_UNAVAILABLE:damage,buff,debuff,cc",
        "NATIVE_P1_100MOB_WORLD_ACK_CAUSALITY_UNAVAILABLE",
        "NATIVE_P1_SINGLE_ACTION_PROBE_INSUFFICIENT_FOR_FORMAL_ACCEPTANCE",
    ]
    assert report["native_capability_blockers"]["action_enumeration"] == (
        "MISSING_NATIVE_CANDIDATE_ACTION_ENUMERATION"
    )
    assert set(report["native_capability_blockers"]["role_observations"]) == {
        "damage", "buff", "debuff", "cc"
    }
    assert report["gameir_runtime_executed"] is False
    assert report["source_db_read"] is False
    assert report["source_legal_abilities_checked"] is False
    assert report["checkpoint_certified"] is False
    assert attempted_gameir_imports == []
    assert sys.path == before_path
