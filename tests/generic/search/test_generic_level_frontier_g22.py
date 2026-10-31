from __future__ import annotations

import hashlib
from pathlib import Path
import threading

import pytest

from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.class_model import CandidateResult, LevelFrontier
from src.v2.generic_frontier import (
    FRONTIER_AUTHORITY,
    GenericTalentBuild,
    build_generic_level_frontiers,
    serialize_generic_frontiers,
)


CANONICAL_DB_SHA = "d7d5a8519b227a761312bf4d1da56955b58184239a5a2ed7a06f84eb134dc854"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_g22_native_generic_frontier_contains_real_scored_candidates():
    frontiers = build_generic_level_frontiers(class_name="Druid", levels=(19, 20, 21))
    assert tuple(f.level for f in frontiers) == (19, 20, 21)
    assert all(isinstance(f, LevelFrontier) for f in frontiers)
    assert all(len(f.candidates) == 6 for f in frontiers)
    assert all(isinstance(c, CandidateResult) for f in frontiers for c in f.candidates)
    assert all(isinstance(c.build, GenericTalentBuild) for f in frontiers for c in f.candidates)
    assert all(c.metadata["source"] == FRONTIER_AUTHORITY for f in frontiers for c in f.candidates)
    assert all(c.metadata["legacy_fallback"] is False for f in frontiers for c in f.candidates)
    assert all(c.evaluation.seconds_per_mob > 0 for f in frontiers for c in f.candidates)

    l20 = next(f for f in frontiers if f.level == 20)
    assert {c.build.candidate_id for c in l20.candidates} == {
        "talents:none",
        "talents:improved_wrath=1",
        "talents:improved_wrath=2",
        "talents:improved_wrath=3",
        "talents:improved_wrath=4",
        "talents:improved_wrath=5",
    }
    assert [c.evaluation.seconds_per_mob for c in l20.candidates] == sorted(
        c.evaluation.seconds_per_mob for c in l20.candidates
    )
    assert l20.candidates[0].evaluation.seconds_per_mob == pytest.approx(11.5)
    assert l20.candidates[0].metadata["selected_fixed_point_candidate"] is True
    assert l20.candidates[-1].metadata["selected_fixed_point_candidate"] is False


def test_g22_frontier_publication_is_bounded_and_route_gated():
    payload = serialize_generic_frontiers(
        build_generic_level_frontiers(class_name="Druid", levels=(19, 20, 21)),
        class_name="Druid",
    )
    assert payload["authority"] == FRONTIER_AUTHORITY
    assert payload["levels"] == [19, 20, 21]
    assert payload["frontier_count"] == 3
    assert payload["candidate_count"] == 18
    assert payload["route_solving"] is False
    assert payload["legacy_fallback"] is False
    assert "talent-tree point continuity" in payload["route_blocker"]
    assert payload["frontiers"][1]["winner"]["talent_candidate_id"] == "talents:improved_wrath=5"
    assert payload["frontiers"][1]["winner"]["seconds_per_mob"] == pytest.approx(11.5)


def test_g22_frontier_preserves_canonical_catalogue_bytes():
    db = Path("data/forever/catalogue/items_2026-09-29.sqlite")
    before = _sha(db)
    assert before == CANONICAL_DB_SHA
    build_generic_level_frontiers(class_name="Druid", levels=(19, 20, 21))
    assert _sha(db) == before


def test_g22_real_service_and_listener_publish_frontier(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=20)
        payload = client.decisions(level=20, backend_id="generic")
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    gf = payload["generic_frontiers"]
    # G32 supersedes the transitional three-level product preview with one
    # selected-level frontier plus canonical route navigation.  The direct G22
    # builder tests above still prove native multi-level frontier production.
    assert gf["levels"] == [20]
    assert gf["candidate_count"] == 6
    assert gf["route_solving"] is False
    r = next(x for x in payload["decisions"] if str(x["identity"]["class_name"]).lower() == "druid")
    assert r["capability"]["level_frontier_generation"] is True
    assert r["capability"]["level_frontier_scope"] == "bounded_native_generic_candidate_result"
    assert "level_frontier_generation" not in r["unsupported_mechanics"]
    assert r["provenance"]["generic_level_frontier"]["candidate_count"] == 6
    assert r["provenance"]["legacy_fallback"] is False

    assert "const CURRENT_SOFTWARE_VERSION='0.11.48.157';" in DECISIONS_HTML
    assert "Generic LevelFrontier" in DECISIONS_HTML
    assert "route solving ${gf.route_solving===true?'enabled':'gated'}" in DECISIONS_HTML
