"""The legacy source IR assembly import must remain lazy until execution."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_source_ir_assembly_import_is_not_a_game_ir_import():
    """Importing the legacy assembly entrypoint must not load its game rules.

    Actual assemble_source_ir() still resolves the original overlays on use;
    the separate ordered-pipeline regression proves that runtime contract.
    """
    source = """
import sys
from src.game.data.forever import source_ir_assembly

assert callable(source_ir_assembly.assemble_source_ir)
for module in (
    'src.game.model.ir',
    'src.game.runtime.simulator',
    'src.game.data.forever.source_rank_overlay',
    'src.game.data.forever.source_talent_overlay',
    'src.game.data.forever.primary_stat_conversions',
):
    assert module not in sys.modules, module
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"Source IR assembly import loaded legacy GameIR: {result.stdout}\\n{result.stderr}"
    )
