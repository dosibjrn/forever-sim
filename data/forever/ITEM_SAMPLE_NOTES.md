# Forever item calibration samples

`item_samples_trusted.csv` contains only screenshots where both the required
level and the relevant displayed stats are visible in the tooltip.

Purpose: calibrate attainable normal gear curves. It is **not** an exhaustive
item database and it is not yet consumed automatically by the optimizer.

Excluded from this trusted table:

- random-suffix AH rows whose suffix stats were missing from the shown tooltip,
- items with visible stats but no visible required-level line,
- values inferred from item names or external databases rather than the captured
  tooltip.

Missing fields are unknown, not zero.

## Context-only Mage sample

`item_samples_context.csv` records **Staff of Orgrimmar** from the supplied tooltip:
31–47 damage, 3.30 speed (11.8 DPS), +4 Intellect, +5 Spirit, +18 spell damage/healing, +4 MP5.
The required-level line is not visible, so it is deliberately excluded from the trusted calibration table despite the user estimating the sample at about level 13.
