from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src import game_context
from src.engine_registry import reset_engine_cache
from src.forever_build import LEGACY_COMPAT_AS_OF, configure, current
from src.rulesets.forever.shared.tuning import base_damage_multiplier
from src.service.checkpoints import Compatibility, compatibility_detail, classify_compatibility
from src.service.executors import MasterOptimizerExecutor, V2RunnerExecutor
from src.service.models import JobRequest
from src.service.publication import publish_attempt


def _req(**kw):
    base = dict(ruleset="forever", class_name="mage", start_level=11, end_level=60, endpoint_mode="mc")
    base.update(kw)
    return JobRequest(**base)


def test_tuning_uses_process_build_identity_when_call_omits_as_of(monkeypatch):
    monkeypatch.delenv("WOW_FOREVER_BUILD_AS_OF", raising=False)
    monkeypatch.delenv("WOW_FOREVER_BUILD_SOURCE", raising=False)
    assert current().as_of == LEGACY_COMPAT_AS_OF
    configure("2026-09-23", source="test")
    assert base_damage_multiplier("druid", "wrath") == 1.0
    configure("2026-09-24", source="test")
    assert base_damage_multiplier("druid", "wrath") == 1.5


def test_job_request_canonicalizes_forever_build_and_dedup_identity():
    implicit = _req().canonical_dict()
    explicit = _req(forever_build_as_of="2026-09-23").canonical_dict()
    assert implicit["forever_build_as_of"] == "2026-10-02"
    assert explicit["forever_build_as_of"] == "2026-09-23"
    assert _req().dedup_key() != _req(forever_build_as_of="2026-09-23").dedup_key()


def test_old_checkpoint_has_documented_legacy_mapping_and_build_drift_is_not_resume():
    target = _req().canonical_dict()
    legacy = dict(target); legacy.pop("forever_build_as_of")
    detail = compatibility_detail(legacy, target)
    assert detail["compatibility"] == Compatibility.RESUME.value
    assert "legacy Forever artifact assumes 2026-10-02" in detail["reasons"][0]

    older_build = _req(forever_build_as_of="2026-09-23").canonical_dict()
    detail = compatibility_detail(legacy, older_build)
    assert detail["compatibility"] == Compatibility.SEED_ONLY.value
    assert "Forever build drift" in detail["reasons"]
    assert classify_compatibility(target, older_build) is Compatibility.SEED_ONLY


def test_service_executors_pass_canonical_build_to_children():
    smooth = JobRequest(ruleset="forever", class_name="druid", start_level=20, end_level=20, endpoint_mode="smooth", forever_build_as_of="2026-09-24")
    cmd = V2RunnerExecutor().plan({"request": smooth.canonical_dict()}).command
    i = cmd.index("--forever-as-of")
    assert cmd[i + 1] == "2026-09-24"

    mc = _req(forever_build_as_of="2026-09-23")
    cmd = MasterOptimizerExecutor().plan({"request": mc.canonical_dict()}).command
    i = cmd.index("--forever-as-of")
    assert cmd[i + 1] == "2026-09-23"


def test_pnp_numeric_cache_hash_changes_with_forever_build(monkeypatch):
    previous = game_context.current()
    try:
        game_context.configure("forever", "mage"); reset_engine_cache()
        from src import pnp_cache
        configure("2026-09-23", source="test")
        a = pnp_cache.current_sim_hash()
        configure("2026-09-24", source="test")
        b = pnp_cache.current_sim_hash()
        assert a != b
    finally:
        game_context.configure(previous.ruleset, previous.class_name); reset_engine_cache()


def test_publication_request_exposes_build_identity(tmp_path: Path):
    req = JobRequest(ruleset="forever", class_name="druid", start_level=20, end_level=20, endpoint_mode="fast", forever_build_as_of="2026-09-24")
    job = {"id": "job", "request": req.canonical_dict()}
    run_root = tmp_path / "run"
    viewer = run_root / "state" / "games" / "forever-druid" / "v2" / "viewer.json"
    viewer.parent.mkdir(parents=True)
    viewer.write_text('{"running": false}', encoding="utf-8")
    pub = publish_attempt(tmp_path, job=job, attempt={"id": "attempt", "run_root": str(run_root)})
    assert pub["request"]["forever_build_as_of"] == "2026-09-24"


def test_v2_run_snapshot_contains_explicit_forever_build(monkeypatch):
    previous = game_context.current()
    try:
        game_context.configure("forever", "mage"); reset_engine_cache()
        configure("2026-09-24", source="test")
        from src.v2.runner import _base_snapshot
        args = SimpleNamespace(
            start_level=20, end_level=20, beam_width=4, family_keep=2, final_k=4,
            parent_k=1, workers=1, max_respecs=0, buy_water=True, view="smooth",
            school="frost", stat_weights=False, stat_weight_top_k=0,
            ruleset="forever", class_name="mage", forever_as_of="2026-09-24",
        )
        snap = _base_snapshot(args)
        assert snap["config"]["forever_build_as_of"] == "2026-09-24"
        assert snap["forever_build"]["build_id"] == "forever-beta@2026-09-24"
    finally:
        game_context.configure(previous.ruleset, previous.class_name); reset_engine_cache()
