"""WF241 historical bounded replay, sharing WF240's actual implementation.

Preserve the old entry point, score signature, budgets, version and evidence
filename without maintaining a second copy of the sampling/engine logic.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Direct python tools/wf241_source_joint_replay.py works outside the repo cwd.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.wf240_source_joint_replay import score as _shared_score, run as _shared_run


def score(ir, gear, allocation):
    return _shared_score(ir, gear, allocation,
                         caster_max_policies=24, mode_max_policies=24)


def run():
    return _shared_run(
        caster_max_policies=24,
        mode_max_policies=24,
        version='0.11.48.241',
        output_path='WF241_DRUID_L20_JOINT_REPLAY.json',
        last_limitation='mixed direct/HoT recovery now executable; HoT continuation into the next pull not yet rehydrated',
    )


if __name__ == '__main__':
    run()
