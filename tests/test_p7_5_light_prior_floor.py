from pathlib import Path

from tools import wf_gate_p7_5_prior
from tools.wf_gate_coverage import p7_required_dps


def test_p75_accepted_prior_floor_is_available_without_full_search(monkeypatch):
    receipt = {
        "dps": 753.775605,
        "compatible_gates": ["P7.4"],
        "run_urls": ["https://github.com/dosibjrn/forever-sim/actions/runs/123"],
    }
    monkeypatch.setattr(
        wf_gate_p7_5_prior,
        "strongest_accepted_prior",
        lambda *args, **kwargs: receipt,
    )

    prior, prior_dps, required = wf_gate_p7_5_prior.p75_accepted_prior_floor(
        Path("."),
        "druid",
        60,
        "balance",
        engine_revision="deb366e986dbc156e2242ddac3ac8c4ac854c107",
        source_sha256="a" * 64,
        reference_dps=720.9117,
    )

    assert prior is receipt
    assert prior_dps == receipt["dps"]
    assert required == p7_required_dps(
        "P7.5",
        720.9117,
        strongest_accepted_compatible_prior=receipt["dps"],
    )


def test_p75_prior_floor_is_none_when_no_compatible_receipt_exists(monkeypatch):
    monkeypatch.setattr(
        wf_gate_p7_5_prior,
        "strongest_accepted_prior",
        lambda *args, **kwargs: None,
    )
    prior, prior_dps, required = wf_gate_p7_5_prior.p75_accepted_prior_floor(
        Path("."),
        "druid",
        60,
        "balance",
        engine_revision="deb366e986dbc156e2242ddac3ac8c4ac854c107",
        source_sha256="a" * 64,
        reference_dps=720.9117,
    )
    assert prior is None
    assert prior_dps is None
    assert required is None


def test_live_p75_provider_resolves_prior_floor_outside_full_search_branch():
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "wf_gate_p7_5_live.py"
    ).read_text()
    assert "prior, prior_dps, required = p75_accepted_prior_floor(" in source
    assert "if complete_search else None" not in source
