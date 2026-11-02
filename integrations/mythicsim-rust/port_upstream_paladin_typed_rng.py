#!/usr/bin/env python3
"""Fail-closed port of new upstream Paladin Bernoulli rolls to typed RNG.

These are new MythicSim upstream mechanics absent from original 666fe17.
Preserve their probabilities and order but route BOTH through the existing
Forever SimRng::sample(Bernoulli), for stochastic as well as BalancedRng.
This creates ordinary reviewed Rust source commits in our public fork.
"""
from pathlib import Path
import argparse

PATCHES = {
    "src/classes/paladin/spells/strikes.rs": (
        '&& fight.random("Shield Specialization - Shieldsworn") > specialization.chance',
        '&& !fight.proc(specialization.chance, "Shield Specialization - Shieldsworn")',
    ),
    "src/classes/paladin/spells/heals.rs": (
        'if fight.random("Oath of Light") < oath.holder_share {',
        'if fight.proc(oath.holder_share, "Oath of Light") {',
    ),
}


def migrate(root: Path) -> int:
    updated = 0
    for name, (before, after) in PATCHES.items():
        path = root / name
        code = path.read_text()
        # Either exactly the documented upstream form, or already migrated.
        # Any changed mechanism/unknown code must be reviewed, never skipped.
        if code.count(after) == 1 and before not in code:
            continue
        if code.count(before) != 1 or after in code:
            raise SystemExit(f"UPSTREAM_TYPED_RNG_NEW_CALLSITE_DRIFT {name}")
        path.write_text(code.replace(before, after))
        updated += 1
    return updated


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("rust_checkout", type=Path)
    a = p.parse_args()
    count = migrate(a.rust_checkout.resolve())
    print(f"UPSTREAM_PALADIN_TYPED_RNG_PORTED_FILES={count}")
