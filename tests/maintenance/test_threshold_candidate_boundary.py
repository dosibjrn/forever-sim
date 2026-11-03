"""G17 candidate enumeration belongs to optimization, not the GameIR adapter."""
from __future__ import annotations

import subprocess
import sys

from src.optimization.threshold_candidates import ThresholdAxis, iter_threshold_candidates


def test_threshold_frontier_is_game_independent_and_bounded():
    axes = (
        ThresholdAxis(key="mana", values=(5.0, 10.0), baseline_value=5.0),
        ThresholdAxis(key="health", values=(0.0, 0.5), baseline_value=0.0),
    )
    rows = list(iter_threshold_candidates("priority:a>b", axes, limit=3))
    assert [r.values for r in rows] == [(5.0, 0.0), (5.0, 0.5), (10.0, 0.0)]
    assert [r.candidate_id for r in rows] == [
        "priority:a>b|thresholds:mana=5;health=0",
        "priority:a>b|thresholds:mana=5;health=0.5",
        "priority:a>b|thresholds:mana=10;health=0",
    ]
    assert rows[0].is_baseline is True
    assert rows[1].is_baseline is False
    assert rows[0].distance == 0.0
    assert rows[1].distance == 0.5
    assert rows[2].distance == 5.0 / 6.0
    assert rows[1].thresholds == {"mana": 5.0, "health": 0.5}
    assert list(iter_threshold_candidates("priority:none", (), limit=1))[0].candidate_id == "priority:none|thresholds:none"
    assert list(iter_threshold_candidates("priority:none", (), limit=0)) == []
    assert list(iter_threshold_candidates("priority:empty", (ThresholdAxis("empty", (), 0.0),), limit=3)) == []


def test_threshold_core_does_not_import_game_model():
    code = ("import src.optimization.threshold_candidates; import sys; "
            "assert 'src.game' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_live_g17_adapter_uses_optimizer_enumerator():
    from src.game import policy_threshold_search as adapter
    from src.optimization import threshold_candidates as core

    assert adapter.iter_threshold_candidates is core.iter_threshold_candidates
    assert not hasattr(adapter, "_threshold_identity")
