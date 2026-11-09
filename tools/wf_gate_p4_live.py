"""P4 measured partial: actual source-paid short whole-build probes.

The real 30 s whole-build + 100-mob acceptance still FAILS until Work2
exposes the complete source/native-world production acceptance path.
"""
from pathlib import Path
from tools.wf_gate_p4_p5_partial import run_paid_partial


def run_live(root: Path, class_key: str, level: int, *, spec: str = "unrestricted") -> dict:
    # Expensive Warlock acceptance is opt-in and explicitly paired: one paid
    # cold producer serves P4/P5/P6, not three independent cold starts.
    import os
    from tools.wf_warlock_l20_gate_bridge import OPT_IN, PAIR, run_warlock_l20_gate
    if (class_key, level, spec) == PAIR and os.environ.get(OPT_IN) == "1":
        return run_warlock_l20_gate(class_key, level, spec, gate="P4")
    return run_paid_partial(root, class_key, level, spec=spec, gate="P4")
