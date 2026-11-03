"""Clean boundary: P2's selected-Rust adapter belongs to engine_client."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_native_p2_client_is_single_owner_and_gate_uses_it():
    canonical = ROOT / "src/engine_client/native_p2_rank_probe.py"
    assert canonical.is_file()
    assert not (ROOT / "src/game/native_p2_rank_probe.py").exists()
    gate = (ROOT / "tools/wf_gate_p2_live.py").read_text(encoding="utf-8")
    assert "from src.engine_client.native_p2_rank_probe import NativeRngMode, run_native_rank_pair" in gate
    assert "src.game.native_p2_rank_probe" not in gate
    tree = ast.parse(canonical.read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.module]
    imports += [alias.name for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names]
    assert not any(name == "src.game" or name.startswith("src.game.")
                   for name in imports)
    # Moving the adapter must not change how it locates the selected pinned fork.
    assert "_REPO_ROOT = Path(__file__).resolve().parents[2]" in canonical.read_text(encoding="utf-8")


def test_python_gameir_only_p2_report_cli_is_retired():
    """P2 acceptance belongs to the selected production engine, not a GameIR report CLI."""
    legacy_report = ROOT / "tools/wf430_p2_gate_report.py"
    assert not legacy_report.exists()

    p2_contract = (ROOT / "docs/gates/P1-P2.md").read_text(encoding="utf-8")
    assert "A Python GameIR-only run is diagnostic" in p2_contract
    assert (ROOT / "tools/wf_gate_p2_live.py").is_file()
