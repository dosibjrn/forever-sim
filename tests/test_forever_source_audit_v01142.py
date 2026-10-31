from __future__ import annotations

from src.rulesets.forever.data.audit import audit_catalogue
from src.rulesets.forever.data.catalogue import ForeverSourceCatalogue


def test_source_coverage_audit_is_green_and_status_complete():
    report = audit_catalogue(ForeverSourceCatalogue())
    assert report["ok"], report["issues"]
    for row in report["classes"].values():
        assert row["coverage"]["talent_status_pct"] == 100.0
        assert row["coverage"]["spell_status_pct"] == 100.0
    assert report["wowhead_resolved_refs"] >= 100


def test_source_coverage_exposes_partial_id_coverage_instead_of_claiming_full_support():
    report = audit_catalogue(ForeverSourceCatalogue())
    assert report["classes"]["druid"]["coverage"]["talent_id_pct"] < 100.0
    assert report["unresolved_reasons"]["wowhead_talent_id_not_confidently_resolved"] > 0
    assert report["unresolved_reasons"]["spell_family_rank_ids_not_imported"] > 0


def test_server_side_and_ambiguous_effects_are_counted():
    report = audit_catalogue(ForeverSourceCatalogue())
    assert report["effect_status"]["server_side_script"] > 0
    assert report["effect_status"]["unsupported_or_ambiguous"] > 0
