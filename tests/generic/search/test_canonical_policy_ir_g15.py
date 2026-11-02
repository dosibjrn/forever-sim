from __future__ import annotations

from pathlib import Path
import threading

from src.game.data.forever import build_game_ir_slice
from src.game.policy import condition_matches, select_action
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.talents import apply_talent_selection
from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.generic_backend import build_partial_generic_records


def _record(level: int = 20):
    return build_partial_generic_records(class_names=("Druid",), selected_level=level)[0]


def test_g15_policy_is_canonical_game_ir_data_not_backend_constructed_rotation():
    ir = build_game_ir_slice(class_key="Druid", level=20)
    assert ir.schema_version == 16
    assert len(ir.policies) >= 1
    policy = next(p for p in ir.policies if p.id == "forever:druid:caster-priority@20")
    assert policy.provenance["authority"] == "canonical_game_ir"
    assert policy.provenance["search_performed"] is False
    assert [r.id for r in policy.rules] == ["periodic_if_missing", "direct_filler"]
    assert [c.kind for c in policy.rules[0].conditions] == [
        "target_state", "aura_missing", "resource_threshold",
    ]
    assert policy.rules[0].conditions[-1].threshold_source == "action_cost"

    backend_source = Path("src/v2/generic_backend.py").read_text(encoding="utf-8")
    assert "_explicit_caster_seed_policy" not in backend_source
    assert "PolicyRule(" not in backend_source
    assert "PriorityPolicy(" not in backend_source


def test_g15_generic_conditions_cover_aura_present_missing_resource_threshold_and_target_state():
    ir = build_game_ir_slice(class_key="Druid", level=20)
    talented, _ = apply_talent_selection(ir, {"improved_wrath": 5}, level=20)
    policy = talented.policies[0]
    moonfire_rule, wrath_rule = policy.rules
    moonfire = next(a for a in talented.actions if a.id == moonfire_rule.action_id)
    wrath = next(a for a in talented.actions if a.id == wrath_rule.action_id)

    actor = ActorState.from_ir(talented.actor, talented.resources)
    actor.resources["mana"] = 30.0  # below Moonfire, above talented Wrath cost (20)
    target = TargetState.with_health("policy-test", 100.0)
    runtime = CombatRuntime(actor=actor, target=target)

    rule, action, _ = select_action(policy, actions={a.id: a for a in talented.actions}, runtime=runtime)
    assert rule.id == "direct_filler"
    assert action.id == wrath.id
    assert wrath.costs[0].amount == 20.0  # threshold follows post-talent Action cost dynamically

    aura_id = moonfire_rule.conditions[1].aura_id
    missing = moonfire_rule.conditions[1]
    from src.game.model import PolicyCondition
    present = PolicyCondition(kind="aura_present", scope="target", aura_id=aura_id)
    assert condition_matches(missing, action=moonfire, runtime=runtime) is True
    assert condition_matches(present, action=moonfire, runtime=runtime) is False
    target.apply_aura(
        aura_id=aura_id, source_action_id=moonfire.id, applied_at_s=0.0,
        duration_s=12.0, refresh_rule="replace",
    )
    assert condition_matches(missing, action=moonfire, runtime=runtime) is False
    assert condition_matches(present, action=moonfire, runtime=runtime) is True

    alive_condition = moonfire_rule.conditions[0]
    assert condition_matches(alive_condition, action=moonfire, runtime=runtime) is True
    target.apply_damage(1000.0)
    assert condition_matches(alive_condition, action=moonfire, runtime=runtime) is False


def test_g15_runtime_executes_canonical_policy_and_publication_marks_execution_not_search():
    record = _record(20)
    assert record.capability["policy_ir"] is True
    assert record.capability["policy_execution"] is True
    assert record.capability["policy_search"] is True
    assert "policy_execution" not in record.unsupported_mechanics
    assert "policy_search" not in record.unsupported_mechanics
    # G15 source authority remains Canonical Game IR; G16 publishes a searched derivative.
    source_policy = record.provenance["game_ir"]["policies"][0]
    assert source_policy["provenance"]["authority"] == "canonical_game_ir"
    assert record.policy["provenance"]["source_policy_authority"] == "canonical_game_ir"
    assert record.provenance["evaluation"]["provenance"]["producer"] == "generic_searched_policy_ir"
    assert record.provenance["evaluation_seed"]["selection"] == "bounded searched Policy IR priority"
    assert record.provenance["legacy_fallback"] is False


def test_g15_common_decision_api_and_listener_surface_selected_policy_ir(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=2)
        payload = client.decisions(level=20, backend_id="generic")
        record = next(r for r in payload["decisions"] if str(r["identity"]["class_name"]).lower() == "druid")
        assert payload["active_backend"] == "generic"
        assert record["provenance"]["game_ir"]["policies"][0]["provenance"]["authority"] == "canonical_game_ir"
        assert record["policy"]["provenance"]["source_policy_authority"] == "canonical_game_ir"
        assert record["capability"]["policy_ir"] is True
        assert record["capability"]["policy_execution"] is True
        assert record["capability"]["policy_search"] is True
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    assert "const CURRENT_SOFTWARE_VERSION='0.11.48.153';" in DECISIONS_HTML
    assert "function genericPolicyCondition(c)" in DECISIONS_HTML
    assert "Canonical Policy IR" in DECISIONS_HTML
    start = DECISIONS_HTML.index("function genericPolicyCondition(c)")
    end = DECISIONS_HTML.index("function genericEvaluationSummary", start)
    renderer = DECISIONS_HTML[start:end].lower()
    assert "druid" not in renderer
    assert "moonfire" not in renderer
    assert "wrath" not in renderer
