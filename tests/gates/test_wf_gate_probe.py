"""A direct gate probe must actually execute production code, never saved evidence."""
from tools.wf_gate_probe import probe_gate


def test_live_p2_probe_executes_real_druid_source_runtime():
    row = probe_gate("druid", 60, "balance", "P2", timeout_s=45.0)
    # The exact PASS count may improve as real production mechanics are fixed.
    assert row["status"] in {"PASS", "FAIL"}, row
    assert row["verified"] > 0, row
    assert row["applicable"] >= row["verified"], row
    assert row["engine_id"] == "live_game_ir_compiler_and_runtime", row
    assert len(row["source_id"]) == 64, row
    assert row["status"] != "TIMEOUT", row
