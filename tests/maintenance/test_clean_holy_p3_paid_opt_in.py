"""Holy P3 paid replay is opt-in; shared helper PRs keep focused tests."""
from pathlib import Path


WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/work2-paladin-holy-p3.yml")


def test_holy_p3_runs_unit_regressions_without_automatic_paid_replay():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "types: [opened, synchronize, reopened, labeled]" in text
    assert "tools/wf_gate_p3_live.py" in text
    assert "Focused Forever HPS, identity, routing, refusal regressions" in text
    opt_in = "contains(github.event.pull_request.labels.*.name, 'holy-p3-paid-no-record')"
    for name in ("Build exact selected Rust CLI",
                 "One genuine Holy HPS paid P3, no M1 write"):
        segment = text.split("      - name: " + name, 1)[1].split(
            "      - name:", 1)[0]
        assert "if: " + opt_in in segment
    receipt = text.split("      - name: Preserve exact Holy native gate receipt", 1)[1]
    assert "if: always() && " + opt_in in receipt
    # No opt-in on the focused unit regressions themselves.
    unit_segment = text.split(
        "      - name: Focused Forever HPS, identity, routing, refusal regressions", 1
    )[1].split("      - name:", 1)[0]
    assert opt_in not in unit_segment
