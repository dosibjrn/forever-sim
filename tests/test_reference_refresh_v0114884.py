from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.capture_talentsforever_references import normalize_capture, publish_capture
from src.rulesets.forever.classes.druid.reference_builds import reference_build_snapshot


def _raw():
    return {
        "schema_version": 1,
        "class": "druid",
        "url": "https://talentsforever.com/druid/60/example",
        "accepted": True,
        "capture_backend": "fixture",
        "captured_at": "2026-10-03T10:00:00Z",
        "source_build": "1.60.1.70009",
        "raw_sha256": "abc123",
        "candidates": [
            {"text": "#1 11/5/35 shared 157 saved 422 opened 3,280 close builds 49", "overall_rank": 1},
            {"text": "#2 9/37/5 shared 131 saved 248 opened 1,963 close builds 108", "overall_rank": 2},
            {"text": "#3 36/0/15 shared 35 saved 144 opened 879 close builds 54", "overall_rank": 3,
             "href": "https://talentsforever.com/druid/60/exact", "talent_ranks": {
                 "improved_wrath": 5, "moonglow": 3, "improved_moonfire": 2, "natures_majesty": 2,
                 "natures_reach": 2, "natures_splendor": 1, "insect_swarm": 1, "vengeance": 5,
                 "improved_starfire": 5, "natures_grace": 1, "eclipse": 3, "moonfury": 5,
                 "moonkin_form": 1, "natures_focus": 5, "naturalist": 5, "subtlety": 2, "reflection": 3,
             }},
            {"text": "#4 9/42/0 shared 70 saved 158 opened 1,351 close builds 63", "overall_rank": 4},
            {"text": "#5 0/46/5 shared 44 saved 104 opened 715 close builds 40", "overall_rank": 5},
        ],
    }


def test_reference_capture_normalizes_deterministically_with_provenance_and_coverage():
    a = normalize_capture(_raw())
    b = normalize_capture(_raw())
    assert a == b
    assert a["content_sha256"] == b["content_sha256"]
    assert [x["overall_rank"] for x in a["builds"]] == [1, 2, 3, 4, 5]
    assert a["groups"]["balance"]["available"] == 1
    assert a["groups"]["feral"]["available"] == 3
    assert a["groups"]["restoration"]["available"] == 1
    assert a["capture"]["provenance_url"].startswith("https://talentsforever.com/")
    assert a["capture"]["raw_sha256"] == "abc123"
    assert a["builds"][2]["allocation_detail_status"] == "exact"


def test_invalid_capture_preserves_last_known_good_canonical_bytes(tmp_path: Path):
    canonical = tmp_path / "druid.json"
    canonical.write_bytes(b'{"known":"good"}\n')
    before = canonical.read_bytes()
    bad = _raw(); bad["accepted"] = False
    with pytest.raises(ValueError):
        publish_capture(bad, canonical)
    assert canonical.read_bytes() == before


def test_runtime_provider_reads_canonical_snapshot_only():
    snap = reference_build_snapshot()
    assert snap["schema_version"] == 2
    assert snap["capture"]["provider"] == "Talents Forever"
    assert snap["content_sha256"]
