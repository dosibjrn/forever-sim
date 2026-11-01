from __future__ import annotations

import hashlib
from pathlib import Path
import threading

import pytest

from src.listener import DECISIONS_HTML
from src.rulesets.forever.items.runtime_selection import clear_runtime_item_cache, select_gear
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.generic_backend import build_partial_generic_records


CANONICAL_DB_SHA = "d7d5a8519b227a761312bf4d1da56955b58184239a5a2ed7a06f84eb134dc854"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record():
    return build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]


def test_g20_named_catalogue_gear_changes_exact_joint_generic_result():
    r = _record()
    assert r.gear["status"] == "selected_named_catalogue_gear"
    assert r.gear["selection_method"] == "explicit_bounded_optimizer_fixed_point"
    assert r.gear["fixed_point_complete"] is True
    assert r.gear["item_count"] == 15
    assert r.gear["aggregate_stats"]["spell_power"] == pytest.approx(76.0)
    assert r.gear["aggregate_stats"]["intellect"] == pytest.approx(28.0)
    assert r.gear["aggregate_stats"]["spirit"] == pytest.approx(16.0)
    assert r.gear["aggregate_stats"]["mp5"] == pytest.approx(2.0)
    assert r.gear["naked_seconds_per_mob"] == pytest.approx(18.608695652173914)
    assert r.timing["seconds_per_mob"] == pytest.approx(11.5)
    assert r.timing["kill_seconds_per_mob"] == pytest.approx(9.0)
    assert r.timing["recovery_seconds_per_mob"] == pytest.approx(2.5)
    assert r.talents["ranks"] == {"improved_wrath": 5}
    assert r.policy["provenance"]["candidate_id"] == "priority:direct_filler|thresholds:direct_filler.resource.mana=20"
    assert r.capability["gear_optimization"] is True
    assert r.capability["gear_optimization_scope"] == "explicit_bounded_optimizer_fixed_point"
    assert r.capability["stat_weight_evaluation"] is True
    assert "gear_optimization" not in r.unsupported_mechanics
    assert "stat_weight_evaluation" not in r.unsupported_mechanics
    assert r.provenance["legacy_fallback"] is False


def test_g20_exact_scorer_stat_sensitivity_uses_first_effective_probe():
    r = _record()
    assert r.stat_weights["method"] == "generic_exact_state_first_effect_forward_difference"
    rows = {row["stat"]: row for row in r.stat_weights["ranked"]}
    assert rows["spell_power"]["first_effective_delta"] == pytest.approx(5.0)
    assert rows["spell_power"]["value"] == pytest.approx(0.3833333333333336)
    assert rows["mp5"]["first_effective_delta"] == pytest.approx(1.0)
    assert rows["mp5"]["value"] == pytest.approx(0.010373443983404229)
    assert rows["spirit"]["first_effective_delta"] == pytest.approx(1.0)
    assert rows["spirit"]["value"] == pytest.approx(0.0051975051975077236)
    assert rows["intellect"]["first_effective_delta"] is None
    assert rows["intellect"]["value"] == pytest.approx(0.0)


def test_g20_runtime_catalogue_reads_do_not_mutate_canonical_sqlite_bytes():
    db = Path("data/forever/catalogue/items_2026-09-29.sqlite")
    assert _sha(db) == CANONICAL_DB_SHA
    clear_runtime_item_cache()
    selected = select_gear(
        "druid", 20, "druid_balance",
        weights={"spell_power": 1.0, "intellect": 0.2, "spirit": 0.1, "mp5": 0.5},
    )
    assert selected
    assert _sha(db) == CANONICAL_DB_SHA
    _record()
    assert _sha(db) == CANONICAL_DB_SHA


def test_g20_real_service_and_listener_surface_gear_and_sensitivities(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=5)
        payload = client.decisions(level=20, backend_id="generic")
        r = next(x for x in payload["decisions"] if str(x["identity"]["class_name"]).lower() == "druid")
        assert r["gear"]["item_count"] == 15
        assert r["timing"]["seconds_per_mob"] == pytest.approx(11.5)
        assert r["stat_weights"]["values"]["spell_power"] > r["stat_weights"]["values"]["spirit"]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    assert "const CURRENT_SOFTWARE_VERSION='0.11.48.157';" in DECISIONS_HTML
    assert "Generic Gear + Stat Sensitivity" in DECISIONS_HTML
    assert "explicit_bounded_optimizer_fixed_point" not in DECISIONS_HTML  # rendered from data, not hard-coded method value
    assert "fixed point" in DECISIONS_HTML
