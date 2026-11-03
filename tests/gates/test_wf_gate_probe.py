"""A direct gate probe must actually execute production code, never saved evidence."""
from tools.wf_gate_probe import probe_gate


def test_retired_p2_probe_does_not_execute_a_gate():
    row = probe_gate("druid", 60, "balance", "P2", timeout_s=45.0)
    assert row["status"] == "RETIRED", row
    assert row["reason"] == "GATE_NOT_IN_ACTIVE_ACCEPTANCE_SCOPE"
