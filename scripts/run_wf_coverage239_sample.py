"""WF239 deterministic sample replay, using the shared WF238 sampler."""
import argparse
from pathlib import Path

from scripts.run_wf_coverage238_sample import run as _shared_run


def run(output: Path, *, sample_count: int = 160, policy_cap: int = 24):
    return _shared_run(output, sample_count=sample_count, policy_cap=policy_cap,
                       finalist_talent_count=8, version='0.11.48.239')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--sample-count', type=int, default=160)
    p.add_argument('--policy-cap', type=int, default=24)
    a = p.parse_args()
    run(a.output, sample_count=a.sample_count, policy_cap=a.policy_cap)
