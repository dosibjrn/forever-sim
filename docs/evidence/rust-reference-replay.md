# WF633 — Rust Balance reference replay

Status: **PASS (standalone Rust replay only)**. This is **not** P7.1.2 Go PASS, P7.1.3 live 2D PASS, or a certified checkpoint.

## Reproducibility
- Rust upstream: [sage3648/mythicsim-forever-engine](https://github.com/sage3648/mythicsim-forever-engine/tree/666fe17a42682068a3c8497d88d5fa3732cbdfb9)
- Rust source commit: `666fe17a42682068a3c8497d88d5fa3732cbdfb9`
- Binary build: [GitHub Actions WF632](https://github.com/dosibjrn/dite/actions/runs/40879414059)
- Artifact: `wf632-forever-engine-linux-x64` (GitHub Actions run artifact)
- Build: `cargo build --release --locked`
- Reference report: https://api.mythicsim.com/api/forever/ranking-sims/d9d85974-a1f7-4700-ab22-2335d767a944/report

## Exact evidence from WF633 local execution
- Class: Druid, level 60, Balance, Night Elf
- Talents: `5532220115501351--505`
- Iterations: **10,000**; seed: **1179706472**; encounter 120 seconds ±15 seconds
- Rust result DPS: **728.1936126415858**
- Saved reference DPS: **728.1936126415858**
- DPS difference: **0.0000000000000**
- Reference DPS standard deviation: **43.420319553486735**
- Reconstructed input used a Go-schema probe plus restored consumables and raid buffs. This is not proof of raw byte-identical original request.
- Known gear IDs in slot order: `18727,12103,18681,272411,18385,18497,13253,11662,252486,18322,272407,12543,12930,11832,20069,272430`
- Raid buffs: Arcane Brilliance, Fire Resistance Aura, Fire Resistance Totem, Gift of the Wild, Prayer of Spirit
- Raid debuffs: Curse of Elements, Faerie Fire, Judgement of Wisdom
- Party: Grace of Air, Leader of the Pack, Mana Spring, Moonkin Aura, Strength of Earth, Windfury
- Player buffs: Greater Blessing of Kings and Greater Blessing of Wisdom
- Consumes (item IDs): `13512,250337,20749,250937,250343,13454,8423`
- Prepull: Moonkin Form -4.5s; Starfire -3s
- Abilities in APL include Innervate, Hurricane, Insect Swarm, Moonfire, Wrath, Starfire.

## Source artifacts and limitations
The complete local WF633 run contains `rust_request_reconstructed.json`, `rust_result.json`, `WF633_VALIDATION.json`, and `WF633_REPORT.md`; those files were generated in the execution workspace and **have not all been committed to this repository**. Avoid claiming that this Markdown summary replaces raw logs. Binary and build evidence is linked above.

## Pending gates
- Native Go exact reference parity: not certified
- Live gsim 2D↔combat-backend integration: not certified
- Probability-balanced Rust source, hit table coverage, and stochastic regression: not certified.
