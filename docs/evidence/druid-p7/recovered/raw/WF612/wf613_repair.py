"""WF613 generic compatibility-preserving structural proposal.

Construct an ordered, bounded set of legal neighbor configurations around a
parent. Every subcandidate still needs a real paid evaluation by the caller.
No game- or spec-specific scoring, items, talent presets, or winners.
"""
import copy


def repair_proposals(parent, rng, gear_mutate, talent_mutate, apl_mutate,
                     legal, width=5):
    if width < 1:
        raise ValueError('width must be positive')
    base = copy.deepcopy(parent)
    # Preserve two dimensions while locally changing a third. In later
    # proposals, co-change a dependent component from the *same* parent.
    actions = [
        ('talents',),
        ('talents', 'policy_spec'),
        ('gear_ids',),
        ('gear_ids', 'policy_spec'),
        ('policy_spec',),
        ('gear_ids', 'talents', 'policy_spec'),
    ]
    rng.shuffle(actions)
    produced = []
    seen = set()
    for keys in actions:
        if len(produced) >= width: break
        candidate = copy.deepcopy(base)
        for key in keys:
            if key == 'gear_ids': candidate[key] = list(gear_mutate(tuple(candidate[key]), rng))
            elif key == 'talents': candidate[key] = talent_mutate(candidate[key], rng)
            elif key == 'policy_spec': candidate[key] = apl_mutate(candidate[key], rng)
        fingerprint = repr(candidate)
        if fingerprint not in seen and candidate != base and legal(candidate):
            seen.add(fingerprint)
            produced.append(candidate)
    return produced


def best_paid(proposals, evaluator, budget_remaining):
    """Return best *actually evaluated* proposal, never a synthetic score."""
    best = None
    n = 0
    for config in proposals:
        if budget_remaining() <= 0: break
        value = evaluator(config)
        n += 1
        if best is None or value > best[1]: best = (config, value)
    return best, n
