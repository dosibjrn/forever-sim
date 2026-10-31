from __future__ import annotations

from pathlib import Path
import threading

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_search import enumerate_legal_talent_allocations, talent_candidate_id
from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.generic_backend import build_partial_generic_records


def _record():
    return build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]


def test_g19_executable_talent_ir_enumerates_exact_legal_candidate_space():
    ir = build_game_ir_slice(class_key="druid", level=20)
    allocations, truncated = enumerate_legal_talent_allocations(ir, level=20)
    assert truncated is False
    assert len(allocations) == 51
    assert "talents:none" in [talent_candidate_id(x) for x in allocations]
    assert "talents:ferocity=1" in [talent_candidate_id(x) for x in allocations]
    assert "talents:ferocity=1;improved_wrath=5" in [talent_candidate_id(x) for x in allocations]
    assert "talents:improved_wrath=5" in [talent_candidate_id(x) for x in allocations]


def test_g19_joint_search_selects_exact_talent_allocation_and_policy():
    record = _record()
    search = record.provenance["naked_talent_search"]
    assert record.talents["status"] == "joint_talent_policy_search"
    assert search["candidate_count"] == 51
    assert search["valid_candidate_count"] == 51
    assert search["truncated"] is False
    assert search["executable_talent_ids"] == ["improved_wrath", "ferocity", "savage_fury"]
    assert search["complete_source_talent_coverage"] is False
    assert search["selected_candidate_id"] == "talents:improved_wrath=5"
    assert search["selected_selection"] == {"improved_wrath": 5}
    assert search["selected_seconds_per_mob"] == pytest.approx(18.608695652173914)
    assert search["selected_detail"]["policy_candidate_id"] == record.provenance["naked_policy"]["provenance"]["candidate_id"]
    assert record.talents["ranks"] == {"improved_wrath": 5}
    assert record.capability["talent_search"] is True
    assert record.capability["talent_search_scope"] == "executable_talent_ir"
    assert record.capability["talent_search_executable_families"] == ["improved_wrath", "ferocity", "savage_fury"]
    assert "talent_search" not in record.unsupported_mechanics
    assert record.provenance["legacy_fallback"] is False


def test_g19_talent_rank_changes_joint_optimum_and_policy_thresholds():
    search = _record().provenance["naked_talent_search"]
    rows = {x["candidate_id"]: x for x in search["candidates"]}
    expected = {
        "talents:none": (26.08695652173913, 0.25, 40.0),
        "talents:improved_wrath=1": (24.591304347826085, 0.25, 36.0),
        "talents:improved_wrath=2": (23.095652173913045, 0.25, 32.0),
        "talents:improved_wrath=3": (21.6, 0.10, 28.0),
        "talents:improved_wrath=4": (20.104347826086954, 0.10, 24.0),
        "talents:improved_wrath=5": (18.608695652173914, 0.10, 20.0),
    }
    for cid, (seconds, hp_gate, mana_gate) in expected.items():
        row = rows[cid]
        assert row["seconds_per_mob"] == pytest.approx(seconds)
        policy_id = row["detail"]["policy_candidate_id"]
        assert f"target.health_pct={hp_gate:g}" in policy_id
        assert f"direct_filler.resource.mana={mana_gate:g}" in policy_id
    assert rows["talents:improved_wrath=2"]["detail"]["policy_candidate_id"] != rows["talents:improved_wrath=3"]["detail"]["policy_candidate_id"]


def test_g19_real_service_and_listener_surface_joint_search(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=3)
        payload = client.decisions(level=20, backend_id="generic")
        record = next(r for r in payload["decisions"] if str(r["identity"]["class_name"]).lower() == "druid")
        assert record["provenance"]["naked_talent_search"]["selected_candidate_id"] == "talents:improved_wrath=5"
        assert record["provenance"]["naked_talent_search"]["selected_detail"]["policy_candidate_id"] == record["provenance"]["naked_policy"]["provenance"]["candidate_id"]
        assert record["provenance"]["naked_evaluation"]["seconds_per_mob"] == pytest.approx(18.608695652173914)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    from src.version import SOFTWARE_VERSION
    assert f"const CURRENT_SOFTWARE_VERSION='{SOFTWARE_VERSION}';" in DECISIONS_HTML
    assert "joint talent + policy search" in DECISIONS_HTML
    assert "talent candidates" in DECISIONS_HTML
    assert "executable families" in DECISIONS_HTML


def test_g19_talent_search_kernel_has_no_class_spell_or_legacy_dispatch():
    source = Path("src/game/talent_search.py").read_text(encoding="utf-8").lower()
    for forbidden in ("druid", "moonfire", "wrath", "legacy", "mage", "paladin", "hunter"):
        assert forbidden not in source
