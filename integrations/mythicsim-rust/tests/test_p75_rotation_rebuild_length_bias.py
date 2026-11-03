"""P7.5 paid-parent rotation rebuild must explore longer source-legal APLs."""
import json
import random
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))

import p75_joint_search as search


def test_paid_rotation_rebuild_uses_long_cold_source_grammar(monkeypatch):
    reference = json.loads(
        (REPO / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json").read_text()
    )
    template = search.player(reference)["equipment"]["items"]
    pools = [[item["id"]] for item in template]
    enchant_pools = {i: [None] for i in range(len(template))}

    observed = []
    original = search.mutate_apl

    def spy(actions, source_actions, rng, *, cold=False, min_length=2):
        observed.append((cold, min_length))
        if min_length == 2:
            return original(actions, source_actions, rng, cold=cold)
        return original(
            actions, source_actions, rng, cold=cold, min_length=min_length
        )

    monkeypatch.setattr(search, "mutate_apl", spy)
    candidate = search.make_candidate(
        reference,
        pools,
        random.Random(29),
        elite=reference,
        enchant_pools=enchant_pools,
        repair_axes=("rotation_rebuild",),
    )

    assert observed == [(True, 14)]
    generated = search.player(candidate)["rotation"]["priorityList"]
    assert 14 <= len(generated) <= 20
