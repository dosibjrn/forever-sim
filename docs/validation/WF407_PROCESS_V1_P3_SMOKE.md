# WF407 — approved PROCESS v1 P3, no extra catalogue-attestation gate

**Authority:** immutable `PROCESS_WOW_FOREVER_v1_2026-10-15.md` SHA256
`ce936f4d6a054333ef92541f1878855179ec8d1732669f7e0b044aa74632c4d5`.
Historical overall plan v4.2 SHA256
`1e801f8b58d2ae1a1952935f17035376b42af9aefa0c4e3ca73ca62a0f2b415b`.
The proposed v5 overall plan is NOT active. Protected documents were not edited.

The former WF406 preflight unconditionally failed P3 if a complete class-filtered
1–255 Wowhead capture was missing. That requirement was expressly removed by
PROCESS v1. This release adds a fast, build-weight-conditioned **P3 smoke**:
select up to five legal items **by descending ilvl** in each current SQLite
slot; score their ordinary sourced stats; fail on missing, negative or
nonpositive required context weights; derive mean weapon-hit damage from the
source IR's actually selected APL actions. No positive epsilons or guessed
class coefficients are introduced. Special procs are not modeled here.

This is not global BiS certification, and a PASS on a synthetic unit-test
fixture is not a checkpoint PASS. The actual Druid L20 historical measured
weights still fail for the named axes in `evidence/wf407/WF407_DRUID_L20_FAST_P3_LIVE.json`.
The source-IR and weight evidence must match the real evaluated build before
P3 is promoted. P4 talent-unlocked spell execution, P5 10x, P6 replay, and
P7 same-context Decisions challenger remain separate gates.

The historical `WF403` gate contract is preserved as immutable historical
implementation evidence; active acceptance follows PROCESS v1.
