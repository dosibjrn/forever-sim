# Druid L60 Balance — owner-accepted P7.1 Rust evidence

**Owner status: CLOSED / PASS** using the pinned **MythicSim Rust** engine and exact tested 10,000-fight Rust input. This page implements the owner's specific P7.1 acceptance decision; it does not assert that native MythicSim Go or live gsim-2D↔Go tests were executed.

- [Pinned runnable full request](../../wf633/rust_request_reconstructed.json)
- [Raw full simulation result](../../wf633/rust_result.json)
- [Validation including request SHA256](../../wf633/WF633_VALIDATION.json)
- [Rust replay procedure](../../wf633/README.md)
- [Explicit owner decision and evidence gaps](../../druid-p7/README.md)

Engine source revision: `666fe17a42682068a3c8497d88d5fa3732cbdfb9`. 10,000 iterations, seed `1179706472`, 120 ± 15 s, class Druid / Balance L60 / Night Elf, talents `5532220115501351--505`. Saved reference DPS = Rust DPS = **728.1936126415858**. Request SHA256 `d4f659e066a9aaf7ba9f389391e2490415308b65a9e074fa696b18e97ec83226`.

The original raw request bytes were not authenticated; this is the reconstructed request that produced identical simulation output. The reproducible request includes item/enchant IDs, full buffs/debuffs, consumes, spell/rotation conditions and encounter details. Under approved [PROCESS v2.9](../../../../PROCESS.md), native MythicSim Rust **or** Go is acceptable, Rust preferred. New/current live production gates still require genuine causal gsim-2D ↔ selected native integration. This historical owner-specific P7.1 Rust approval remains recorded without inventing an unexecuted live-2D run.

**Full checkpoint certification remains 0/148**; P1–P6 and other P7 gates are not inferred from this approval.
