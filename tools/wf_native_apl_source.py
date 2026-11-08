"""Build native APL requests from canonical Rust get_options; no combat model.

Only converts Rust-owned spell/action identities into the engine's APL JSON.
OtherActionShoot is discovered from Rust-prepared actor, not get_options
(class spells); see wf_warlock_eight_mob_joint_search.native_cast_identifiers.
"""


def native_spell_candidates(options: dict, request: dict) -> list[dict]:
    by_name = {}
    for source in options.get("spells", []):
        spell_id = source.get("spell_id")
        level = source.get("minimum_level")
        name = source.get("name")
        if (type(spell_id) is not int or spell_id <= 0
                or not isinstance(name, str) or not name.strip()
                or (level is not None and
                    (type(level) is not int or level > options["level"]))):
            continue
        label = name.strip().casefold()
        old = by_name.get(label)
        if old is None or (level or 0, spell_id) > (
                old.get("minimum_level") or 0, old["spell_id"]):
            by_name[label] = source
    spells = sorted(by_name.values(), key=lambda x: (
        -(x.get("minimum_level") or 0), x["spell_id"]))
    used_ids = {row["spell_id"] for row in spells}
    for entry in request["raid"]["parties"][0]["players"][0].get(
            "rotation", {}).get("priorityList", []):
        identity = ((entry.get("action") or {}).get("castSpell") or {}).get(
            "spellId") or {}
        spell_id = identity.get("spellId")
        if type(spell_id) is int and spell_id not in used_ids:
            spells.insert(0, {"spell_id": spell_id,
                              "name": "source_apl_" + str(spell_id),
                              "minimum_level": None,
                              "source": "existing_source_request"})
            used_ids.add(spell_id)
    return spells


def cast_apl(spell_id, *, guard=None):
    entry = {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}
    if guard == "dot_missing":
        entry["action"]["condition"] = {"not": {"val": {
            "dotIsActive": {"spellId": {"spellId": spell_id}}}}}
    elif guard == "aura_missing":
        entry["action"]["condition"] = {"not": {"val": {
            "auraIsActive": {"auraId": {"spellId": spell_id},
                             "sourceUnit": {"type": "CurrentTarget"}}}}}
    elif guard is not None:
        raise ValueError("Unknown native APL condition guard: " + repr(guard))
    return entry


def mana_conditioned_apl(spell_id, percent: int):
    entry = cast_apl(spell_id)
    entry["action"]["condition"] = {"cmp": {
        "lhs": {"currentManaPercent": {}}, "op": "OpLt",
        "rhs": {"const": {"val": str(percent) + "%"}}}}
    return entry


def multi_apl(spells):
    return [cast_apl(spell_id, guard=guard) for spell_id, guard in spells]
