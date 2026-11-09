"""M1 owns one native Warlock P4/P5/P6 cold run, not three paid restarts.

These are Forever-owned dispatch/receipt-wiring regressions. They do not
validate MythicSim legality, ranks, spell effects or Warcraft source facts.
"""
from pathlib import Path

WORKFLOW = Path(".github/workflows/m1-on-demand-record.yml")
ENGINE = "febc1d703e022265ed61ede3fec9b05416282536"


def test_heavy_warlock_p4_p5_pairs_only_on_exact_checkpoint():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert '"$heavy" == true' in workflow
    assert 'warlock_shared_needed=false' in workflow
    assert 'warlock_shared_needed=true' in workflow
    assert '" ${unique[*]} " == *" warlock:20:unrestricted:P4 "*' in workflow
    assert '" ${unique[*]} " == *" warlock:20:unrestricted:P5 "*' in workflow
    assert '" $TARGETS " == *" warlock:20:unrestricted:P6 "*' in workflow


def test_one_official_paired_cli_shares_p4_p5_p6_native_receipt():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'warlock_pair=false' in workflow
    assert 'warlock_triple=false' in workflow
    assert '"$warlock_pair" == true &&' in workflow
    assert '"$entry" == warlock:20:unrestricted:P5' in workflow
    assert '"$entry" == warlock:20:unrestricted:P6' in workflow
    assert 'cli_gate="P4+P5+P6"' in workflow
    assert 'FOREVER_P4_P5_WARLOCK_L20_COLD_SEARCH=1' in workflow
    assert 'FOREVER_P4_P5_WARLOCK_L20_RECEIPT_DIR=' in workflow
    assert 'timeout "${timeout_s}s" python tools/wf_gate.py' in workflow


def test_official_warlock_engine_and_raw_receipts_are_pinned():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert f"ref: {ENGINE}" in workflow
    assert f'test "$(git rev-parse HEAD)" = {ENGINE}' in workflow
    assert 'if: steps.targets.outputs.warlock_shared_needed == \'true\'' in workflow
    assert 'cargo build --locked --bin forever-engine' in workflow
    assert 'warlock-native-engine/target/debug/forever-engine' in workflow
    assert 'warlock-l20-troll-native.request.json' in workflow
    assert 'if: always() && steps.targets.outputs.warlock_shared_needed' in workflow
    assert 'warlock-l20-official-cold/' in workflow
