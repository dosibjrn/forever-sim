"""P4 measured partial: actual source-paid short whole-build probes.

The real 30 s whole-build + 100-mob acceptance still FAILS until Work2
exposes the complete source/native-world production acceptance path.
"""
from pathlib import Path
from tools.wf_gate_p4_p5_partial import run_paid_partial


def run_live(root: Path, class_key: str, level: int, *, spec: str = "unrestricted") -> dict:
    return run_paid_partial(root, class_key, level, spec=spec, gate="P4")
