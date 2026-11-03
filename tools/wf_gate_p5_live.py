"""P5 measured partial using the SAME source-paid production search as P4.

The diagnostic samples a short cold run; it never asserts 300 s acceptance,
2x breadth or 100-mob finalist without executing those conditions.
"""
from pathlib import Path
from tools.wf_gate_p4_p5_partial import run_paid_partial


def run_live(root: Path, class_key: str, level: int, *, spec: str = "unrestricted") -> dict:
    return run_paid_partial(root, class_key, level, spec=spec, gate="P5")
