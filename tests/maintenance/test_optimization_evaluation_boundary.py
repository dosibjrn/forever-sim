import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_optimizer_evaluation_contract_is_game_runtime_independent_with_legacy_aliases():
    source = """
import sys
from src.optimization.evaluation import Evaluation
from src.v2.class_model import Evaluation as OptimizerEvaluation
assert Evaluation is OptimizerEvaluation
assert Evaluation.__module__ == "src.optimization.evaluation"
assert not any(name == "src.game" or name.startswith("src.game.") for name in sys.modules)
from src.game.evaluation import Evaluation as LegacyEvaluation
assert LegacyEvaluation is Evaluation
assert "src.game.runtime.simulator" in sys.modules
from src.game import Evaluation as PublicGameEvaluation
assert PublicGameEvaluation is Evaluation
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"optimizer Evaluation import boundary / legacy alias failed: "
        f"{result.stdout}\n{result.stderr}"
    )
