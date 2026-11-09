"""Forever-only transport/scheduling regressions, not MythicSim game rules."""
import copy
import json
from pathlib import Path

from tools import wf_warlock_l20_unlock_probe as probe


def _source():
    return {"raid": {"parties": [{"players": [{
        "class": "ClassWarlock", "race": "RaceTroll",
        "talentsString": "110-0-0",
        "rotation": {"priorityList": [{"action": {"castSpell": {
            "spellId": {"spellId": 686}}}}]},
    }]}]}}


def _options():
    return {"class": "warlock", "level": 20,
            "source_revision": "selected-native", "talents": {"trees": []}}


def _proposals(_options, _original, _seed):
    yield {"talents": "110-0-0"}
    yield {"talents": "101-0-0"}


def test_prepared_action_ids_are_native_registry_not_source_spell_guess(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"native")
    requests = []
    def native_prepare(command, **kwargs):
        assert kwargs["check"] is False
        request = json.loads(open(command[command.index("--request") + 1]).read())
        requests.append(request)
        prepared = {"player": {"spells": [
            {"action_id": {"spell_id": 123}, "flags": ["SpellFlagAPL"]},
            {"action_id": {"spell_id": 456}, "flags": ["SpellFlagHidden"]},
            {"action_id": {"spell_id": 789}, "flags": ["SpellFlagAPL"]},
        ]}}
        with open(command[command.index("--outfile") + 1], "w") as f:
            json.dump(prepared, f)
        return type("Completed", (), {"returncode": 0})()
    ids = probe.prepared_apl_ids(binary, _source(), tmp_path / "prepare",
                                 runner=native_prepare)
    assert ids == {123, 789}
    assert requests[0]["raid"]["parties"][0]["players"][0]["class"] == "ClassWarlock"


def test_registered_differential_uses_only_native_prepared_talent_and_apl(tmp_path):
    reference = _source()
    original = copy.deepcopy(reference)
    observed = []
    def native_prepare(_binary, request, _out):
        actor = probe.player(request)
        observed.append(actor["talentsString"])
        return {686} if actor["talentsString"] == "110-0-0" else {686, 987}
    result = probe.find_native_registered_unlock(
        reference, _options(), binary=tmp_path / "native", out=tmp_path,
        seed=3, prepare=native_prepare, proposals=_proposals)
    assert observed == ["110-0-0", "101-0-0"]
    assert result["status"] == "NATIVE_TALENT_DEPENDENT_APL_PROPOSAL"
    assert result["new_native_registered_action_id"] == 987
    actor = probe.player(result["candidate_source"])
    assert actor["talentsString"] == "101-0-0"
    assert actor["rotation"]["priorityList"][0]["action"]["castSpell"]["spellId"]["spellId"] == 987
    assert actor["rotation"]["priorityList"][1:] == probe.player(reference)["rotation"]["priorityList"]
    assert reference == original


def test_paid_matched_native_comparison_cannot_claim_cast_or_gate_pass(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"rust-selected")
    calls = []
    def paid(_binary, candidate, _out, *, targets, timeout):
        calls.append((copy.deepcopy(candidate), targets, timeout))
        assert targets == 2
        return {"seconds_per_mob": 10.0 if len(calls) == 1 else 8.0,
                "native_source_damage_effects_by_caster": {"player": {"Spell-987": 9}}}
    result = probe.run_probe(
        _source(), _options(), binary=binary, out=tmp_path / "paid", seed=4,
        proposals=_proposals, chain=paid,
        prepare=lambda _bin, request, _out: (
            {686} if probe.player(request)["talentsString"] == "110-0-0"
            else {686, 987}))
    assert result["status"] == "NATIVE_PAID_2_TARGET_POLICIES_COMPARED"
    assert result["new_native_action_acked_damage_effects"] == 9
    assert result["native_cast_result_evidence_complete"] is False
    assert result["p4_pass"] is False and result["gate_recorded"] is False
    assert len(calls) == 2
    assert calls[0][0]["recovery"] == calls[1][0]["recovery"]
    assert result["paid_comparison"]["baseline"]["seconds_per_mob"] == 10.0
    assert (tmp_path / "paid/unlock_probe_summary.json").is_file()


def test_no_registered_action_or_native_refusal_is_not_absence_certificate(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"rust-selected")
    paid = []
    result = probe.run_probe(
        _source(), _options(), binary=binary, out=tmp_path / "probe", seed=4,
        proposals=_proposals,
        prepare=lambda _binary, request, _out: (
            {686} if probe.player(request)["talentsString"] == "110-0-0"
            else None),
        chain=lambda *args, **kwargs: paid.append(True))
    assert result["status"] == "NO_DIFFERENTIAL_NATIVE_APL_ACTION_IN_SAMPLED_TALENTS"
    assert result["native_prepare_refusals"] == 1
    assert result["native_source_unlocked_actions_available"] is None
    assert paid == []


def test_native_workflow_uses_the_existing_source_equipped_actor():
    """Pin the paid wiring to the proven equipped source, not a neutral actor."""
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/work2-warlock-l20-talent-unlock.yml")
    text = workflow.read_text()
    assert "--source ../engine/fixtures/warlock-l20-troll-native.request.json" in text
    assert "--talent-unlock-equipment-reference fixtures/warlock-l20-p71.request.json" in text
    assert "--source ../engine/fixtures/warlock-l20-troll-source-equipped.request.json" not in text


def test_refused_native_chain_keeps_actual_acked_effects_not_inferred_cast(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"selected-native")
    calls = []

    class NativeRefusal(RuntimeError):
        def __init__(self, raw):
            super().__init__("RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL")
            self.raw_response = raw

    def refused_chain(_binary, candidate, _out, *, targets, timeout):
        calls.append(copy.deepcopy(candidate))
        assert targets == 2
        raw = {"status": "RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL",
               "world_targets_killed": 0,
               "native_source_damage_effects_by_caster": {
                   "player": {"Spell-987": 2 if len(calls) == 2 else 0}}}
        raise NativeRefusal(raw)

    result = probe.run_probe(
        _source(), _options(), binary=binary, out=tmp_path / "refused",
        proposals=_proposals, chain=refused_chain,
        prepare=lambda _bin, request, _out: (
            {686} if probe.player(request)["talentsString"] == "110-0-0"
            else {686, 987}))
    assert len(calls) == 2
    assert result["status"] == "NATIVE_PAID_POLICY_REFUSAL_RETAINED"
    assert result["paid_comparison"]["baseline"]["status"] == "NATIVE_PAID_2_TARGET_REFUSED"
    assert result["paid_comparison"]["talent_action"]["native_response"]["world_targets_killed"] == 0
    assert result["new_native_action_acked_damage_effects"] == 2
    assert result["native_cast_result_evidence_complete"] is False
    assert result["p4_pass"] is False and result["gate_recorded"] is False


def test_unexpected_runner_error_is_not_labeled_a_native_refusal(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"selected-native")

    def crashed_chain(*_args, **_kwargs):
        raise RuntimeError("runner transport failed")

    result = probe.run_probe(
        _source(), _options(), binary=binary, out=tmp_path / "error",
        proposals=_proposals, chain=crashed_chain,
        prepare=lambda _bin, request, _out: (
            {686} if probe.player(request)["talentsString"] == "110-0-0"
            else {686, 987}))
    assert result["status"] == "NATIVE_PAID_POLICY_REFUSAL_RETAINED"
    assert result["paid_comparison"]["baseline"]["status"] == "NATIVE_PAID_2_TARGET_ERROR"
    assert result["paid_comparison"]["talent_action"]["status"] == "NATIVE_PAID_2_TARGET_ERROR"
    assert result["p4_pass"] is False


def test_recorded_source_equipment_overlay_is_exact_and_non_mutating():
    neutral = _source()
    neutral["raid"]["parties"][0]["players"][0]["equipment"] = {"items": []}
    recorded = {"player": {"equipment": {"items": [
        {"id": 253949}, {"id": 20442}, {"id": 4315}
    ]}}}
    original = copy.deepcopy(neutral)
    equipment = copy.deepcopy(recorded)
    result = probe.overlay_recorded_equipment(neutral, recorded)
    assert probe.player(result)["equipment"] == recorded["player"]["equipment"]
    assert neutral == original and recorded == equipment
    # No talents, policy, encounter, seed, or native request fields change.
    probe.player(result)["equipment"] = {"items": []}
    assert result == original
