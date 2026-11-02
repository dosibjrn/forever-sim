"""Source staging removes default-DB executable actions, not provider facts."""
from dataclasses import dataclass

from src.game.data.forever.source_stage_isolation import strip_precompiled_source_actions


@dataclass(frozen=True)
class _Action:
    id: str
    metadata: dict


@dataclass(frozen=True)
class _Mode:
    enabled_action_ids: tuple[str, ...] | None


@dataclass(frozen=True)
class _Slice:
    actions: tuple[_Action, ...]
    modes: tuple[_Mode, ...]
    source_facts: tuple[object, ...]


def test_staged_override_preserves_unrelated_actions_and_mode_semantics():
    canonical = _Action("compiled", {"source_semantic_type": "damage"})
    provider = _Action("provider", {})
    facts = (
        {"fact_kind": "source_indexed_executable_ability"},
        {"fact_kind": "provider_reference"},
        "retain-other-facts",
    )
    original = _Slice(
        actions=(canonical, provider),
        modes=(_Mode(("compiled", "provider")), _Mode(None), _Mode(("compiled",))),
        source_facts=facts,
    )
    staged = strip_precompiled_source_actions(original)
    assert staged.actions == (provider,)
    assert staged.modes == (_Mode(("provider",)), _Mode(None), _Mode(()))
    assert staged.source_facts == facts[1:]
    assert strip_precompiled_source_actions(staged) == staged
    assert original.actions == (canonical, provider)


def test_no_canonical_compiler_actions_is_exact_noop():
    original = _Slice(
        actions=(_Action("provider", {}),),
        modes=(_Mode(("provider",)),),
        source_facts=({"fact_kind": "source_indexed_executable_ability"},),
    )
    assert strip_precompiled_source_actions(original) is original
