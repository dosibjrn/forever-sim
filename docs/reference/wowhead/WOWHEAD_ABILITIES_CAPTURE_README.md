# WoW Forever: class abilities + talents → SQLite

This is a **source capture**, not yet a complete executable game-rules database.
It uses the current Wowhead Forever class pages:

- `https://www.wowhead.com/forever/spells/abilities/{class}`
- `https://www.wowhead.com/forever/spells/talents/{class}`

Supported: `warrior paladin hunter rogue priest shaman mage warlock druid`.

## Install (once)

In the project folder in a Bash shell (Git Bash/WSL/Linux/macOS):

```bash
python -m pip install playwright
```

The existing capture uses your installed Google Chrome via Playwright's `chrome` channel. Use the same Chrome profile as the original item capture. **Do not run both capture scripts concurrently**, because they use the same persistent browser profile.

## Recommended capture sequence

First, a quick proof for the two current melee classes:

```bash
./wowhead-abilities-capture.sh --classes warrior rogue
```

Then a new snapshot for all nine classes (18 category lists):

```bash
./wowhead-abilities-capture.sh
```

The output contains a batch ID (e.g. `20261008T140000Z`). To fetch **individual spell/talent pages** into the same DB, preserving the previous list results:

```bash
./wowhead-abilities-capture.sh --batch-id YOUR_BATCH_ID --resume --details
```

This last step may make ~2,000 page requests; it is **optional**, slower and more likely to hit Wowhead rate limits. You can try `--max-details 20` first. Incomplete detail captures remain explicitly marked and can be resumed. Run only against pages you are permitted to access; respect site limitations and do not attempt to evade blocks.

Output (under project root):

- `data/forever/catalogue/forever_abilities.sqlite`
- `data/forever/catalogue/wowhead_abilities_manifest_<batch>.json`

Upload **both** back into the chat. They are separate from `items_2026-09-29.sqlite`, which must not be changed.

## Database contract

- `capture_batches`: snapshot metadata + completion state
- `capture_lists`: expected vs actual per-class abilities/talents counts, status, hashes
- `spell_index`: source URL, spell ID, class, category, observed name, raw Wowhead list row and unverified rank/level hints
- `spell_details`: source-page text and SHA, per-ID capture status
- `spell_detail_snapshots`: full compressed HTML evidence, HTTP/final URL and byte/hash checks, required for a detail to count as verified capture

**Fail closed**: a list is not `complete` unless its count is present and enough **unique spell IDs** were captured. Individual detail captures require matching spell ID/name, HTTP 200, and durable hash-verifiable HTML; a text-only legacy row is not accepted as a verified detail. Browser blocks, truncated results and missing IDs are not converted into positive assertions.

**Important:** Wowhead's `talents` listing does *not* necessarily include full talent-tree coordinates, prerequisites, all talent rank spell IDs, or effect semantics. Those must be joined separately from verified Forever client Trait/Spell DB2 facts. Likewise, only class ability/talent listings are captured: this is not a dump of every NPC, item-proc or hidden spell in the game. Raw tooltip text and compressed HTML are preserved as evidence, not parsed into guessed modifiers. A verified HTML snapshot does **not** certify executable damage, resource costs, cooldowns, or effects.

The SQLite is a factual ingestion layer; it must not be used as optimized simulator output until facts pass provenance/coverage/semantic checks.

## Known limitation

The browser has to actually render Wowhead's JavaScript data. The extractor prefers `window.listviewspells`; it falls back to rendered rows and paginated list traversal. Live Wowhead behavior has not yet been verified against your local Chrome profile. If the site changes its JS or blocks automated browsing, the manifest marks the affected class/category as incomplete. Send the manifest even if the command exits nonzero so the parser can be adapted without trusting partial data.
