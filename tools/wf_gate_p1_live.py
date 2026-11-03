"""PROCESS v2.1 P1: source -> GameIR -> optimizer -> production runtime.

Class neutral. Never reads a user-written verdict/evidence JSON to award PASS.
This is a targeted, bounded *availability* smoke, not a P2 semantics test or P4 search.
This is a source-index effect diagnostic, not an acquisition proof. MythicSim
owns spell/rank legality; actual applicable effects must still be executed.
"""
from __future__ import annotations

import json
import os
import hashlib
from math import isfinite
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any


class P1SetupError(RuntimeError):
    pass


def _db_fingerprint(path: Path) -> str:
    with path.open('rb') as f:
        digest = __import__('hashlib').sha256()
        for piece in iter(lambda: f.read(1024*1024), b''):
            digest.update(piece)
    return digest.hexdigest()


def _source_code_fingerprint(root: Path) -> str:
    """Reproducibility metadata, not an eighth acceptance gate."""
    digest = hashlib.sha256()
    paths = sorted((root/'src').rglob('*.py')) + [Path(__file__)]
    for path in paths:
        digest.update(str(path.relative_to(root) if path.is_relative_to(root) else path.name).encode())
        digest.update(b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _source_rows(db_path: Path, class_key: str, level: int | None):
    """Legal/conditional inventory from canonical index, not a hardcoded list.

    The index is not proof of a learned spell; spell legality is native-owned.
    Unknown level metadata remain visible in diagnostics.
    """
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = {x[0] for x in db.execute("select name from sqlite_master where type='table'")}
        if 'spell_index' not in tables:
            raise P1SetupError('SOURCE_DB_MISSING_SPELL_INDEX')
        rows = list(db.execute('SELECT spell_id,name,rank_hint,level_hint,source_url,raw_listview_json '
                               'FROM spell_index WHERE class_key=? AND kind=? ORDER BY spell_id',
                               (class_key,'abilities')))
    if not rows:
        raise P1SetupError('SOURCE_HAS_NO_CLASS_ABILITIES:'+class_key)
    return [dict(r) for r in rows if level is None or r['level_hint'] is None or int(r['level_hint']) <= level]


def _source_ids(action, source_id_parser) -> set[int]:
    """Use the production index-to-IR trace, with a canonical action-ID fallback."""
    result = {int(x) for x in source_id_parser(action)}
    m = re.fullmatch(r'source_spell:(\d+)', str(action.id))
    if m:
        result.add(int(m.group(1)))
    return result


def _id_label(row):
    return f"{row['spell_id']}:{row['name']}:rank={row.get('rank_hint')}:level={row.get('level_hint')}"


# Explicitly recognised prerequisites: a conditional test without its trigger
# is not an executor failure, but an arbitrary runtime error is not one either.
SUPPORTED_REQUIREMENTS = frozenset({
    'minimum_level', 'mode_is', 'relative_position_is', 'aura_any_present',
    'aura_present', 'resource_below_capacity', 'resource_min', 'out_of_combat', 'aura_missing',
})


def _requirements_well_formed(action) -> list[str]:
    issues = []
    for requirement in getattr(action, 'requirements', ()):
        if not isinstance(requirement, dict) and not hasattr(requirement, 'get'):
            issues.append('non-mapping requirement')
            continue
        kind = str(requirement.get('kind') or '')
        if kind not in SUPPORTED_REQUIREMENTS:
            issues.append('unsupported requirement: ' + (kind or '<missing>'))
        elif kind == 'minimum_level':
            try:
                if int(requirement.get('value')) < 1:
                    issues.append('non-positive minimum level')
            except (TypeError, ValueError):
                issues.append('invalid minimum level')
        elif kind == 'mode_is' and not requirement.get('value'):
            issues.append('missing mode value')
        elif kind == 'relative_position_is' and not requirement.get('value'):
            issues.append('missing required relative position')
        elif kind in ('aura_any_present', 'aura_present'):
            ids = requirement.get('aura_ids') if kind == 'aura_any_present' else [requirement.get('aura_id')]
            if not isinstance(ids, (list, tuple)) or not ids or not all(isinstance(v, str) and v for v in ids):
                issues.append('invalid aura prerequisite')
        elif kind in ('resource_min', 'resource_below_capacity') and not requirement.get('resource_id'):
            issues.append('missing prerequisite resource id')
    return issues


def _legitimate_conditional(action, reason: str) -> bool:
    """Recognise a *matching* unmet source requirement, not a generic error.

    P1 does not need to fabricate a proc to run a conditional ability. But a
    resource prerequisite must never let an unrelated `requires ...` exception
    pass. The prefixes below match the production generic eligibility strings.
    """
    if not isinstance(reason, str) or not reason or 'unsupported' in reason.lower():
        return False
    for req in getattr(action, 'requirements', ()):
        if not hasattr(req, 'get'):
            continue
        kind = req.get('kind')
        if kind == 'relative_position_is' and reason.startswith(
                'requires relative position ' + repr(str(req.get('value')))):
            return True
        if kind == 'mode_is' and reason.startswith(
                'requires mode ' + repr(str(req.get('value')))):
            return True
        if kind == 'aura_present' and reason.startswith(
                'requires active aura ' + str(req.get('aura_id'))):
            return True
        if kind == 'aura_any_present' and reason == 'requires one active sourced aura':
            return True
        resource = str(req.get('resource_id') or '')
        if kind == 'resource_below_capacity' and resource and reason == 'requires room in ' + resource:
            return True
        if kind == 'resource_min' and resource and (
                re.match(r'^requires [0-9.eE+-]+ ' + re.escape(resource) + r'; have ', reason)
                or reason.startswith('insufficient ' + resource + ':')):
            return True
    return False


# Events attributable to the probed action that demonstrate the generic
# CombatRuntime reached an effect or persistent state change. Runtime queue
# housekeeping and unrelated passive regeneration are not an effect witness.
# This is generic runtime vocabulary, NEVER a class/spell whitelist.
P1_EFFECT_EVENTS = frozenset({
    'Damage', 'Heal', 'AuraApplied', 'AuraReplaced', 'AuraRemovedExclusive',
    'ResourceChange', 'ResourceChanged', 'ModeChanged',
    'ControlApplied', 'ControlTargetCapEvicted', 'AbsorbShieldGranted',
    'AutoAttackStarted', 'QueuedSwingArmed', 'SummonSpawn', 'SummonDespawn',
    'TargetStatDebuffApplied', 'SchoolPowerDebuffApplied',
    'NextCastInstantGranted', 'CastChargeGranted', 'TimedSpellCritHasteGranted',
    'SpatialChargeArrival', 'PeriodicTick', 'TriggerFired', 'ResourceEventGain',
})


def _p1_effect_observed(event) -> bool:
    """Require an actual runtime effect, not a zero-delta event receipt.

    Production emits ResourceChange/ResourceChanged even when the requested
    gain is capped at full resources. Damage and Heal can also resolve to zero.
    Those event kinds alone cannot certify P1 behavior.
    """
    if event.kind not in P1_EFFECT_EVENTS:
        return False
    if event.kind == 'ControlApplied':
        # CombatRuntime emits ControlApplied even when a proc roll fails or
        # the target is already dead. Only an applied control changes state.
        return getattr(event, 'payload', {}).get('applied') is True
    if event.kind in ('ResourceChange', 'ResourceChanged'):
        payload = getattr(event, 'payload', {})
        before, after = payload.get('before'), payload.get('after')
        return (type(before) in (int, float) and type(after) in (int, float)
                and isfinite(before)
                and isfinite(after)
                and abs(after - before) > 1e-9)
    if event.kind == 'ResourceEventGain':
        gained = getattr(event, 'payload', {}).get('gained')
        return (type(gained) in (int, float)
                and isfinite(gained) and gained > 1e-9)
    if event.kind in ('Damage', 'Heal'):
        payload = getattr(event, 'payload', {})
        # CombatRuntime preserves ignored damage receipts after target death;
        # a positive requested amount is not an applied combat effect.
        if event.kind == 'Damage' and payload.get('applied') is False:
            return False
        # A heal at full resources emits positive requested amount with zero
        # restored health. Only the production-applied delta is a witness.
        value = payload.get('restored') if event.kind == 'Heal' else payload.get('amount')
        return (type(value) in (int, float)
                and isfinite(value) and value > 1e-9)
    if event.kind == 'PeriodicTick':
        # Tick dispatch alone is bookkeeping: subsequent Damage/Heal events
        # prove their own effects; resource ticks mutate the actor in-place.
        gained = getattr(event, 'payload', {}).get('gained')
        return (type(gained) in (int, float)
                and isfinite(gained) and gained > 1e-9)
    return True


# P1 is a bounded combat-action gate: damage, buffs/debuffs and CC only.
# Role facts live in sourced data rather than a class/spell name allowlist.
P1_REQUIRED_ROLES = frozenset({'damage', 'buff', 'debuff', 'cc'})
P1_DEFAULT_SCENARIO = 'current_solo_leveling_100mob_v1'


def _highest_usable_ranks(rows):
    """Keep one highest learned rank per ability family at the checkpoint.

    Compare rank when known, then learned level. This is *not* a suffix/name
    heuristic; the canonical spell index provides exact ranks and levels.
    """
    by_name = {}
    for row in rows:
        key = str(row['name']).strip().casefold()
        def order(r):
            return (int(r.get('rank_hint') or 0), int(r.get('level_hint') or 0))
        if key not in by_name or order(row) > order(by_name[key][0]):
            by_name[key] = [row]
        elif order(row) == order(by_name[key][0]) and all(
                int(row['spell_id']) != int(x['spell_id']) for x in by_name[key]):
            # Different source IDs with exactly the same family/rank/level
            # cannot be dismissed as downranking. Keep both: the gate must
            # report source ambiguity rather than silently drop one.
            by_name[key].append(row)
    return [row for rows in by_name.values() for row in rows]


def _effect_scope(row, scope_facts, context_exclusions):
    """Class-neutral evidence triage, never a spell-name whitelist.

    Unknown evidence for a *missing* legal action is an explicit unresolved
    classification, not silently judged irrelevant.
    """
    sid = int(row['spell_id'])
    if sid in scope_facts:
        fact = scope_facts[sid]
        if fact['name'] != row['name']:
            raise ValueError('P1_SOURCE_SCOPE_ID_NAME_MISMATCH:' + str(sid))
        roles = set(fact['roles'])
        if roles & P1_REQUIRED_ROLES:
            return 'IN_SCOPE', sorted(roles), 'SOURCE_ROLE_FACT'
        # A positive, unclassified numeric effect can still be a buff/debuff
        # or control. Never waive P1 on a partial healing-only observation.
        if fact.get('unresolved_domains'):
            return 'UNRESOLVED', sorted(roles), 'SOURCE_EFFECT_DOMAIN_UNRESOLVED'
        return 'EXCLUDED', sorted(roles), 'SOURCE_ROLE_FACT'
    if row['name'] in context_exclusions:
        return 'EXCLUDED', ['utility'], str(context_exclusions[row['name']])
    try:
        raw = json.loads(row['raw_listview_json'])
        after = (raw.get('envChange') or {}).get('after') or {}
        text = str(after.get('text') or '').lower()
    except (TypeError, ValueError, AttributeError):
        text = ''
    roles = set()
    if re.search(r'\b(?:damage|damages|damaging)\b', text):
        roles.add('damage')
    if re.search(r'\b(?:stuns?|stunned|asleep|sleep|fear|roots?|entangl|immobili|silenc|incapacitat|disorient)\w*', text):
        roles.add('cc')
    if re.search(r'\b(?:increases?|decreases?|reduces?|slows?|stealth|shields?|buffs?)\b', text):
        roles.add('buff')
    if roles:
        return 'IN_SCOPE', sorted(roles), 'SOURCE_EFFECT_TOOLTIP'
    if re.search(r'\b(?:heals?|healing|restores? .*health)\b', text):
        return 'EXCLUDED', ['healing'], 'SOURCE_EFFECT_TOOLTIP'
    return 'UNRESOLVED', [], 'NO_SOURCED_EFFECT_ROLE'


def _load_source_scope_facts(db_path, class_key):
    """Load category facts from the same canonical SQLite as the spell index.

    Sourced role observations are ingested with ID/name/source URL and index
    fingerprint checks. A sidecar JSON must never directly certify P1 scope.
    """
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='p1_source_effect_role_facts'").fetchone():
            return {}
        rows=conn.execute('SELECT f.*,i.name AS index_name,i.source_url AS index_url, '
            'i.raw_listview_json AS index_raw FROM p1_source_effect_role_facts f '
            'JOIN spell_index i ON i.class_key=f.class_key AND i.spell_id=f.spell_id '
            "AND i.kind='abilities' WHERE f.class_key=?",(class_key,)).fetchall()
    result={}
    for r in rows:
        if (r['name']!=r['index_name'] or r['source_index_url']!=r['index_url']
                or r['source_index_sha256'] != hashlib.sha256(r['index_raw'].encode()).hexdigest()):
            raise P1SetupError('P1_SCOPE_SOURCE_INDEX_IDENTITY_DRIFT:'+str(r['spell_id']))
        result[int(r['spell_id'])]={'name':r['name'],'roles':json.loads(r['roles_json']),
                                   'source_url':r['evidence_url']}
    return result



# Source-observed *numeric* spell effects can establish P1 scope, but not
# acquisition, GameIR execution or a P2 effect witness. The vocabulary is
# class-independent; unknown source domains remain unresolved.
_SPELLBOOK_OBSERVED_DOMAIN_ROLES = {
    'damage_per_activation': 'damage',
    'direct_damage': 'damage',
    'periodic_damage_total': 'damage',
    'queued_swing_bonus_damage': 'damage',
    'weapon_bonus_damage': 'damage',
    'weapon_damage_multiplier': 'damage',
    'enemy_armor_reduction': 'debuff',
    'enemy_hit_chance_reduction_pct': 'debuff',
    'movement_speed_increase_pct': 'buff',
    'target_control_seconds': 'cc',
    # 'heal_or_absorb_per_activation' is ambiguous: a shield is a P1 buff.
    # Never exclude it as healing without more specific source evidence.
    'channeled_healing_per_party_target_over_10s': 'healing',
}


def _load_spellbook_observed_scope_facts(root: Path, spellbook_path: str | None,
                                          source_rows: list[dict]) -> dict[int,dict]:
    """Use the exact-ID numeric observations from the already source-bound spellbook.

    _source_legality selected this file only after its source-index fingerprint
    matched the canonical frontier. Recheck each observation's spell ID, name,
    learned level and URL; a name match alone never grants a P1 scope waiver.
    """
    if spellbook_path is None:
        return {}
    try:
        document = json.loads((root / spellbook_path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise P1SetupError('P1_SPELLBOOK_OBSERVED_SCOPE_UNAVAILABLE') from exc
    if document.get('schema') != 'forever_spellbook_level_ranks_v1':
        raise P1SetupError('P1_SPELLBOOK_OBSERVED_SCOPE_SCHEMA_INVALID')
    rows = {int(row['spell_id']): row for row in source_rows}
    facts = {}
    observations = document.get('observed_rank_numeric_by_id', {})
    if not isinstance(observations, dict):
        raise P1SetupError('P1_SPELLBOOK_OBSERVED_SCOPE_INVALID')
    for raw_id, observation in observations.items():
        try:
            spell_id = int(raw_id)
        except (ValueError, TypeError) as exc:
            raise P1SetupError('P1_SPELLBOOK_OBSERVED_SCOPE_ID_INVALID') from exc
        row = rows.get(spell_id)
        if row is None:
            continue  # The source observation is above this checkpoint.
        if (not isinstance(observation, dict)
                or observation.get('name') != row['name']
                or observation.get('learned_level') != row.get('level_hint')
                or not isinstance(observation.get('source_url'), str)
                or not observation['source_url'].startswith('https://')):
            raise P1SetupError('P1_SPELLBOOK_OBSERVED_SCOPE_IDENTITY_DRIFT:' + str(spell_id))
        domains = observation.get('domains')
        if not isinstance(domains, dict) or not domains:
            raise P1SetupError('P1_SPELLBOOK_OBSERVED_SCOPE_DOMAINS_INVALID:' + str(spell_id))
        roles = sorted({_SPELLBOOK_OBSERVED_DOMAIN_ROLES[domain]
                        for domain, amount in domains.items()
                        if domain in _SPELLBOOK_OBSERVED_DOMAIN_ROLES
                        and type(amount) in (int, float) and amount > 0})
        unknown_positive = sorted(domain for domain, amount in domains.items()
            if domain not in _SPELLBOOK_OBSERVED_DOMAIN_ROLES
            and type(amount) in (int, float) and amount > 0)
        if roles or unknown_positive:
            # Unknown-only positive effects must remain visible to the gate.
            # Otherwise a healing tooltip fallback could incorrectly waive a
            # sourced shield/control whose numeric domain is not yet typed.
            facts[spell_id] = {'name': row['name'], 'roles': roles,
                               'unresolved_domains': unknown_positive,
                               'source_url': observation['source_url']}
    return facts


def _load_p1_scenario_nonimpact(root: Path, class_key: str, level: int,
                                scenario_id: str) -> dict[int,dict]:
    """Load explicit, checkpoint-scoped acceptance decisions, NEVER engine facts.

    These exclusions mean only that an action does not affect the selected
    optimization objective. They do not assert that the ability is absent,
    unsupported, incorrectly implemented, or unimportant in other scenarios.
    The JSON is owned by the P1 gate; the canonical spell DB stays unchanged.
    """
    path = root / 'config' / 'gates' / 'p1_scenario_applicability_v1.json'
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise P1SetupError('P1_SCENARIO_LEDGER_UNAVAILABLE:' + str(exc)) from exc
    if document.get('schema') != 'wf_p1_scenario_applicability_v1':
        raise P1SetupError('P1_SCENARIO_LEDGER_SCHEMA_INVALID')
    scenarios = document.get('scenarios')
    if not isinstance(scenarios, list) or scenario_id not in [s.get('id') for s in scenarios if isinstance(s, dict)]:
        raise P1SetupError('P1_SCENARIO_UNDECLARED:' + scenario_id)
    result: dict[int,dict] = {}
    for rec in document.get('records', []):
        if not isinstance(rec, dict):
            raise P1SetupError('INVALID_P1_NONIMPACT_RECORD')
        if rec.get('scenario_id') != scenario_id or rec.get('class_key') != class_key:
            continue
        sid = rec.get('spell_id')
        if (type(sid) is not int or sid <= 0 or not isinstance(rec.get('name'), str)
                or not rec['name'].strip() or rec.get('decision') != 'DOES_NOT_AFFECT_SIM'
                or not isinstance(rec.get('reason'), str) or len(rec['reason'].strip()) < 16
                or not isinstance(rec.get('review_if'), str) or len(rec['review_if'].strip()) < 8
                or type(rec.get('min_level')) is not int or type(rec.get('max_level')) is not int
                or rec['min_level'] < 1 or rec['min_level'] > rec['max_level']):
            raise P1SetupError('INVALID_P1_NONIMPACT_RECORD:' + str(sid))
        if sid in result:
            raise P1SetupError('DUPLICATE_P1_NONIMPACT_RECORD:' + str(sid))
        if rec['min_level'] <= level <= rec['max_level']:
            result[sid] = rec
    return result


def audit_inventory(source_rows, ir, *, parser, source_classifier, policy_builder,
                    scratch_builder, executor, max_errors=10000,
                    effect_checker=None, native_source_spell_ids=(), native_executor=None,
                    scope_facts=None, context_exclusions=None, scenario_exclusions=None,
                    scenario_id=P1_DEFAULT_SCENARIO):
    """PROCESS P1 live inventory with an incremental native-owned action path.

    Source rows select candidate action identities; they are not acquisition
    proof. IDs in native_source_spell_ids bypass Forever/GameIR legality and
    effect checks and must be decided by native_executor. Candidate reachability
    remains checked separately. Other legacy actions retain the transitional
    GameIR runtime path until migrated.
    """
    problems: list[dict[str,Any]] = []
    conditional: list[dict[str,str]] = []
    exercised: list[str] = []
    native_action_results: list[dict[str,Any]] = []
    native_source_spell_ids = {int(sid) for sid in (native_source_spell_ids or ())}
    scope_facts = scope_facts or {}
    context_exclusions = context_exclusions or {}
    scenario_nonimpact = scenario_nonimpact or {}
    nonimpact: list[dict[str,Any]] = []
    def issue(code, row=None, detail=None):
        if len(problems) < max_errors:
            problems.append({'code':code, 'ability':_id_label(row) if row else None,
                             'detail':str(detail)[:240] if detail is not None else None})

    actions = tuple(a for a in ir.actions if a.owner_actor_id == ir.actor.id)
    indexed: dict[int,list] = {}
    for action in actions:
        action_source_ids = {int(sid) for sid in _source_ids(action, parser)}
        if (not isinstance(getattr(action,'effects',None),(list,tuple))
                and not action_source_ids.intersection(native_source_spell_ids)):
            issue('INVALID_TYPED_ACTION', detail=action.id)
        for sid in action_source_ids:
            indexed.setdefault(sid,[]).append(action)
    if not actions:
        issue('EMPTY_GAME_IR')
    eligible: list[dict] = []
    ignored: list[dict] = []
    for row in source_rows:
        sid = int(row['spell_id'])
        # The selected native action is a test selector only. Do not let a
        # Forever source classifier, learned-state flag, level hint, or
        # spellbook scope record veto the native prepare/execute response.
        if sid in native_source_spell_ids:
            eligible.append(row)
            continue
        try:
            classification = source_classifier(row, row['raw_listview_json'])
        except (TypeError, KeyError, ValueError) as exc:
            issue('SOURCE_CLASSIFICATION_FAILED',row,f'{type(exc).__name__}:{exc}')
            continue
        role = classification.get('role') if isinstance(classification,dict) else None
        if role == 'SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP':
            ignored.append({'source_spell_id':sid,'role':role})
            if indexed.get(sid):
                issue('NONACTION_SOURCE_ROW_ENTERED_GAME_IR',row,role)
            continue
        # The source index includes zero-level passive talent ranks inside
        # kind=abilities. A rank with no minimum player level and no compiled
        # action is not a checkpoint-legal castable ability. Report it; never
        # treat it as an executor failure or silently erase a compiled action.
        if (row.get('level_hint') == 0 and row.get('rank_hint') is not None
                and not indexed.get(sid)):
            ignored.append({'source_spell_id':sid,'role':'ZERO_LEVEL_NONACTION_RANK',
                            'reason':'source level zero, no actionable GameIR mapping'})
            continue
        eligible.append(row)

    # Legacy candidates retain the historical highest-rank inventory shape.
    # Native-owned IDs are passed through unchanged: the selected engine, not
    # Forever's rank/level hints, decides their validity.
    native_rows = [row for row in eligible if int(row['spell_id']) in native_source_spell_ids]
    legacy_rows = [row for row in eligible if int(row['spell_id']) not in native_source_spell_ids]
    highest = _highest_usable_ranks(legacy_rows) + native_rows
    checked = []
    for row in eligible:
        if row not in highest and int(row['spell_id']) not in native_source_spell_ids:
            ignored.append({'source_spell_id':int(row['spell_id']), 'role':'LOWER_LEARNED_RANK',
                            'reason':'P1_CHECKS_HIGHEST_SOURCE_RANK_ONLY'})
    for row in highest:
        sid=int(row['spell_id'])
        if sid in native_source_spell_ids:
            checked.append(row)
            continue
        decision=scenario_nonimpact.get(sid)
        if decision is not None:
            if decision.get('name') != row['name']:
                issue('P1_NONIMPACT_ID_NAME_MISMATCH',row,decision.get('name'))
                checked.append(row)  # A bad waiver cannot suppress coverage.
                continue
            entry={'source_spell_id':sid, 'name':row['name'],
                   'role':'DOES_NOT_AFFECT_SIM', 'scenario_id':scenario_id,
                   'reason':decision['reason'], 'review_if':decision['review_if'],
                   'basis':'P1_USER_APPROVED_SCENARIO_DECISION'}
            ignored.append(entry)
            nonimpact.append(entry)
            continue
        rivals=[r for r in highest if r['name'].casefold() == row['name'].casefold()
                and r['spell_id'] != row['spell_id']]
        if rivals:
            issue('AMBIGUOUS_HIGHEST_SOURCE_RANK',row,','.join(str(r['spell_id']) for r in rivals))
        scope, roles, evidence = _effect_scope(row, scope_facts, context_exclusions)
        if scope == 'EXCLUDED':
            ignored.append({'source_spell_id':int(row['spell_id']), 'role':'OUT_OF_P1_EFFECT_SCOPE',
                            'reason':evidence, 'effect_roles':roles})
            continue
        if scope == 'UNRESOLVED' and not indexed.get(int(row['spell_id'])):
            issue('P1_EFFECT_SCOPE_UNRESOLVED',row,evidence)
            # Still expose the actionable missing-ID problem. The unresolved
            # category prevents accepting or dismissing the missing action.
            issue('MISSING_GAME_IR_ACTION',row,'SCOPE_UNRESOLVED')
            continue
        checked.append(row)
    eligible = checked

    for row in eligible:
        matches = indexed.get(int(row['spell_id']),())
        if not matches:
            issue('MISSING_GAME_IR_ACTION',row)
            continue
        if len(matches)>1:
            issue('DUPLICATE_GAME_IR_SOURCE_MATCH',row,','.join(a.id for a in matches))
        for action in matches:
            native_action = sid in native_source_spell_ids
            if not native_action:
                for err in _requirements_well_formed(action):
                    issue('INVALID_OR_UNSUPPORTED_PREREQUISITE',row,f'{action.id}:{err}')
                known_modes = {m.id for m in ir.modes}
                known_resources = {r.id for r in ir.resources}
                for req in action.requirements:
                    if not hasattr(req, 'get'):
                        continue  # already reported as INVALID_OR_UNSUPPORTED_PREREQUISITE
                    if req.get('kind') == 'mode_is' and req.get('value') not in known_modes:
                        issue('UNKNOWN_PREREQUISITE_MODE', row, f"{action.id}:{req.get('value')}")
                    if req.get('kind') in ('resource_min','resource_below_capacity') and req.get('resource_id') not in known_resources:
                        issue('UNKNOWN_PREREQUISITE_RESOURCE', row, f"{action.id}:{req.get('resource_id')}")
                if not action.effects:
                    issue('EMPTY_GAME_IR_EFFECT',row,action.id)
                if not getattr(action,'provenance',None) and not getattr(action,'metadata',{}).get('source_semantic_type'):
                    issue('ACTION_MISSING_SOURCE_TRACE',row,action.id)
                if effect_checker is None:
                    issue('MISSING_PRODUCTION_EFFECT_DISPATCH_CHECKER',row,action.id)
                else:
                    for index, effect in enumerate(action.effects):
                        try:
                            kind = effect_checker(effect)
                            if not isinstance(kind,str) or not kind or kind in ('unsupported','unknown','noop','not_implemented'):
                                issue('UNSUPPORTED_EFFECT_DISPATCH',row,f'{action.id}:effect[{index}]={kind}')
                        except (ValueError, TypeError, KeyError, NotImplementedError) as exc:
                            issue('UNSUPPORTED_EFFECT_DISPATCH',row,f'{action.id}:effect[{index}]:{exc}')
            try:
                p=policy_builder(ir,((action.id,()),))
                if not any(rule.action_id==action.id for rule in p.rules):
                    issue('POLICY_DROPS_ACTION',row,action.id)
            except (TypeError,ValueError,KeyError) as exc:
                issue('POLICY_CANNOT_REFER_TO_ACTION',row,f'{action.id}:{type(exc).__name__}:{exc}')
    # Test the production scratch generator with enough room for a one-action
    # witness each. Do not require a deeply optimised rotation (P4/P5).
    try:
        generated = scratch_builder(ir,max_candidates=max(8,4*len(actions)+1))
        offered={rule.action_id for p in generated for rule in p.rules}
    except (TypeError,ValueError,KeyError) as exc:
        generated=(); offered=set()
        issue('SCRATCH_POLICY_GENERATION_FAILED',detail=f'{type(exc).__name__}:{exc}')
    for row in eligible:
        for action in indexed.get(int(row['spell_id']),()):
            if action.id not in offered:
                issue('OPTIMIZER_OMITS_LEGAL_ACTION',row,action.id)

    for row in eligible:
        sid = int(row['spell_id'])
        for action in indexed.get(sid,()):
            if sid in native_source_spell_ids:
                if native_executor is None:
                    outcome = {
                        'status':'BLOCKED', 'native_status':'BLOCKED',
                        'reason':'NATIVE_P1_EXECUTOR_MISSING',
                        'effect_observed':False,
                    }
                else:
                    try:
                        outcome = native_executor(ir, action, row)
                    except Exception as exc:
                        outcome = {
                            'status':'ERROR', 'native_status':'ERROR',
                            'reason':f'{type(exc).__name__}:{exc}',
                            'effect_observed':False,
                        }
                if not isinstance(outcome, dict):
                    outcome = {
                        'status':'ERROR', 'native_status':'ERROR',
                        'reason':'NATIVE_P1_EXECUTOR_RETURNED_NON_OBJECT',
                        'effect_observed':False,
                    }
                native_result = outcome.get('native_result')
                if not isinstance(native_result, dict):
                    native_result = {}
                native_status = str(
                    outcome.get('native_status') or native_result.get('status')
                    or outcome.get('status') or 'ERROR'
                )
                observable = native_result.get('observable_effects')
                if not isinstance(observable, dict):
                    observable = {}
                native_action_results.append({
                    'action_id':action.id,
                    'source_spell_id':sid,
                    'status':native_status,
                    'reason':outcome.get('reason') or native_result.get('reason'),
                    'effect_observed':outcome.get('effect_observed') is True,
                    'engine_identity':native_result.get('engine_identity'),
                    'scenario':native_result.get('scenario'),
                    'dps_delta':observable.get('dps_delta'),
                    'world_required':native_result.get('world_required'),
                })
                if outcome.get('status')=='executed' and outcome.get('effect_observed') is True:
                    exercised.append(action.id)
                else:
                    code = (
                        f'NATIVE_{native_status}'
                        if native_status in {'INVALID','UNSUPPORTED','ERROR','BLOCKED',
                                             'NO_DIRECT_EFFECT_OBSERVED'}
                        else 'NATIVE_ACTION_NOT_EXECUTED'
                    )
                    issue(code,row,f'{action.id}:{outcome.get("reason") or native_status}')
                continue
            try:
                outcome=executor(ir,action)
            except Exception as exc:
                issue('COMBAT_RUNTIME_EXCEPTION',row,f'{action.id}:{type(exc).__name__}:{exc}')
                continue
            if outcome.get('status')=='executed' and outcome.get('effect_observed') is True:
                exercised.append(action.id)
            elif (outcome.get('status')=='conditional' and
                  _legitimate_conditional(action, str(outcome.get('reason') or ''))):
                conditional.append({'action_id':action.id,'ability':_id_label(row),
                                    'reason':str(outcome['reason'])})
                issue('CONDITIONAL_EFFECT_NOT_EXECUTED',row,
                      f"{action.id}:{outcome['reason']}")
            else:
                issue('COMBAT_ACTION_NOT_EXECUTED',row,f'{action.id}:{outcome}')
    # PARTIAL diagnostic: the denominator is the selected source-action
    # candidate set. Native-owned IDs count only after PreparedV2 observes a
    # positive controlled effect; remaining legacy actions use the transitional
    # GameIR runtime path. No independent spell acquisition proof is required.
    observed_source_abilities = sum(
        bool({action.id for action in indexed.get(int(row['spell_id']), ())}
             & set(exercised))
        for row in eligible
    )
    return {'status':'PASS' if not problems and eligible else 'FAIL',
            'reachability_count':len(eligible),
            'pass_count':observed_source_abilities,
            'behavior_probes_executed':len(exercised),
            'partial_scope':'OBSERVED_SOURCE_ELIGIBLE_ABILITY_EFFECTS',
            'coverage_basis':'executed_behavior_assertions',
            'coverage_scope_complete':not any(
                p['code'] == 'P1_EFFECT_SCOPE_UNRESOLVED'
                for p in problems),
            'total_source_rows_at_or_below_level_or_unknown':len(source_rows),
            'excluded_nonaction_or_inactive_rows':ignored,
            'excluded_setup_rows':[r for r in ignored if r['role']=='SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP'],
            'checked_source_abilities':len(eligible),
            'highest_usable_source_rank_count':len(highest),
            'effect_scope_policy':'damage_buff_debuff_cc_highest_rank_only',
            'p1_scenario_id':scenario_id,
            'does_not_affect_sim':nonimpact,
            'does_not_affect_sim_count':len(nonimpact),
            'matched_source_abilities':sum(bool(indexed.get(int(r['spell_id']))) for r in eligible),
            'production_runtime_exercises':len(exercised),
            'native_action_results':native_action_results,
            'native_source_spell_ids':sorted(native_source_spell_ids),
            'conditional_actions':conditional,
            'actual_scratch_policy_count':len(generated),
            'problems':problems,
            'problem_count':len(problems)}


def _runtime_exercise(ir,action,level):
    """One fresh actor/target with source legal mode/resources per action.

    No special spell setup; conditional prerequisites are surfaced with exact
    executor eligibility reasons, not silently forced or misreported as green.
    """
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    from src.game.runtime.simulator import action_eligibility
    from src.game.model.ir import HealEffect, PeriodicHealEffect
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    if isinstance(actor.metadata,dict):
        actor.metadata['level']=level
    mode_candidates=[m.id for m in ir.modes
                     if m.enabled_action_ids is None or action.id in m.enabled_action_ids]
    if not ir.modes:mode_candidates=[None]
    if not mode_candidates:
        return {'status':'invalid','reason':'NO_LEGAL_MODE_ENABLES_ACTION'}
    first_ineligibility=None
    first_error=None
    first_no_effect=None
    for mode in mode_candidates:
        try:
            actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
            # Reuse *sourced* enemy stats from the production IR. An empty
            # target is not a valid probe for an armor/hit debuff.
            from src.game.data.forever.target_combat_source import target_combat_metadata
            target_meta = (target_combat_metadata(ir)
                           if getattr(ir,'provenance',{}).get('target_combat_profile') else {})
            target=TargetState.with_health('p1_probe_target',100000., **target_meta)
            # Target-owned combo points / resource banks belong to the current
            # target. A legal finisher should be tested with an attainable
            # resource prerequisite, not excused as a conditional no-op.
            if hasattr(target,'bind_resource_definitions'):
                target.bind_resource_definitions(ir.resources)
            for requirement in action.requirements:
                if not hasattr(requirement,'get'):
                    continue
                if requirement.get('kind')=='resource_min':
                    rid=str(requirement.get('resource_id') or '')
                    amount=float(requirement.get('value') or 0.)
                    if rid in getattr(target,'resources',{}):
                        cap=getattr(target,'resource_capacity',{}).get(rid)
                        if cap is None or amount<=cap:
                            target.resources[rid]=max(float(target.resources[rid]),amount)
            if isinstance(actor.metadata,dict):actor.metadata['level']=level
            if mode != actor.current_mode_id:
                actor.transition_mode(mode)
            for rid,cap in actor.resource_capacity.items():
                if rid in actor.resources and actor.resource_is_active(rid):
                    actor.resources[rid]=float(cap)
            # Real healing requires missing health. The old probe ran heals
            # on a full-health actor and mistook overheal receipts for effect.
            # Only source actions with an actual health-healing effect get this
            # legal wounded-actor precondition; no combat effect is simulated.
            if (any(isinstance(effect, (HealEffect, PeriodicHealEffect))
                    and effect.resource_id == 'health' for effect in action.effects)
                    and 'health' in actor.resources
                    and float(actor.resource_capacity.get('health', 0.)) > 0.):
                actor.resources['health'] = float(actor.resource_capacity['health']) * 0.5
            # Satisfy deterministic encounter conditions generically, so a
            # back-position action is *executed* rather than papered over as
            # 'conditional'. Keep external aura/proc triggers conditional: P1
            # does not fabricate a proc just to force a cast.
            for requirement in action.requirements:
                if not hasattr(requirement,'get'):
                    return {'status':'invalid','reason':'INVALID_SOURCE_REQUIREMENT_STRUCTURE'}
                if requirement.get('kind') == 'relative_position_is':
                    target.metadata['attacker_relative_position'] = str(requirement['value'])
                elif requirement.get('kind') == 'resource_below_capacity':
                    rid = str(requirement.get('resource_id') or '')
                    if rid in actor.resources and rid in actor.resource_capacity:
                        cap = float(actor.resource_capacity[rid])
                        actor.resources[rid] = min(float(actor.resources[rid]), max(0., cap-1.))
            eligibility=action_eligibility(action=action,actor=actor,target=target)
            if not eligibility.eligible:
                first_ineligibility=first_ineligibility or str(eligibility.reason)
                continue
            queued = [e for e in action.effects if getattr(e, 'effect_type', None) == 'queued_swing']
            # Queued swings are only useful on the next actual white swing.
            # Instantiate production's matching auto-attack rather than
            # accepting QueuedSwingArmed as damage evidence.
            if queued:
                attacks=[a for a in ir.auto_attacks if a.id in {e.auto_attack_id for e in queued}]
                if len(attacks)!=len(queued):
                    return {'status':'invalid','reason':'QUEUED_SWING_SOURCE_AUTO_ATTACK_MISSING'}
                runtime=CombatRuntime(actor=actor,target=target,auto_attacks=attacks)
            else:
                runtime=CombatRuntime(actor=actor,target=target)
            runtime.schedule_action(action)
            if queued:
                runtime.advance_to(max(a.swing_time_s for a in attacks) + 0.01)
            else:
                runtime.run_until_idle()
            result=runtime.result()
            events=[ev for ev in result.events if ev.action_id == action.id]
            completed=any(ev.kind=='ActionCompleted' for ev in events)
            effective=any(_p1_effect_observed(ev) for ev in events)
            if queued:
                effective=any(ev.kind=='Damage' and ev.payload.get('queued_swing_replacement')
                              for ev in events)
            # Starter/completion bookkeeping alone is NOT effect execution.
            if (completed or queued) and effective:
                return {'status':'executed','events':len(events),'effect_observed':True,'mode':mode}
            if completed:
                first_no_effect=first_no_effect or 'ACTION_COMPLETED_WITHOUT_OBSERVABLE_EFFECT'
                continue  # another source-legal mode may execute the effect
        except (ValueError,TypeError,RuntimeError,KeyError,AssertionError) as exc:
            # One broken legal mode must not hide a second executable mode.
            first_error=first_error or f'{type(exc).__name__}:{exc}'
            continue
    if first_error:
        return {'status':'error','reason':first_error}
    if first_no_effect:
        return {'status':'invalid','reason':first_no_effect}
    return {'status':'conditional','reason':first_ineligibility or 'NO_EXECUTABLE_SOURCE_LEGAL_MODE_OR_PRECONDITION'}


def _p1_scope_metadata(root: Path, class_key: str, level: int) -> dict:
    """Read optional effect-role observations, never acquisition permissions.

    Native MythicSim owns skill acquisition and rank availability. These
    historical snapshots only help classify observable effect types.
    """
    choices = []
    for path in (root / 'evidence').rglob('*.json'):
        if 'spellbook' not in path.name.lower():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        span = data.get('level_range_covered', ())
        if (data.get('schema') == 'forever_spellbook_level_ranks_v1'
                and data.get('class_key') == class_key
                and isinstance(span, (list, tuple)) and len(span) == 2
                and int(span[0]) <= level <= int(span[1])
                and not data.get('runes_enabled', False)):
            choices.append((int(span[1])-level, level-int(span[0]),
                            str(path), path, data))
    if not choices:
        return {'spellbook_file': None, 'scope_context_exclusions': {}}
    choices.sort()
    _, _, _, path, data = choices[0]
    return {'spellbook_file': str(path.relative_to(root)),
            'scope_context_exclusions': dict(
                data.get('contextual_zero_when_solo_land_mob_no_allies_or_debuffs', {}))}


def run_live(root: Path,class_key:str,level:int,db_override:Path|None=None,
             spec:str='unrestricted',scenario_id:str=P1_DEFAULT_SCENARIO)->dict:
    report={'class':class_key,'level':level,'spec':spec,'gate':'P1',
            'status':'FAIL','source':'live_production','reasons':[],
            'p1_scenario_id':scenario_id}
    try:
        sys.path.insert(0,str(root))
        from src.game.data.forever.registry import build_game_ir_slice
        from src.game.data.forever.source_action_scope import classify_indexed_ability
        from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
        from src.game.data.forever.sqlite_talents import DEFAULT_DB
        from src.game.policy_evolution import from_source_rules,scratch_policies
        from src.game.runtime import ActorState,CombatRuntime,TargetState
        from src.game.runtime.effect_capabilities import effect_execution_kind
        source_db=Path(db_override or DEFAULT_DB)
        if not source_db.is_absolute():source_db=root/source_db
        if not source_db.is_file():raise P1SetupError('SOURCE_DB_NOT_FOUND:'+str(source_db))
        rows=_source_rows(source_db,class_key,level)
        ir=build_game_ir_slice(class_key=class_key,level=level,ability_db_path=source_db)
        if ir is None:raise P1SetupError('CLASS_LEVEL_NOT_SUPPORTED_BY_LIVE_SOURCE_PROVIDER')
        scope_meta = _p1_scope_metadata(root,class_key,level)
        report.update(scope_meta)
        from src.forever_build import metadata as build_metadata
        report['build_identity'] = build_metadata()
        report['source_id']=_db_fingerprint(source_db)
        report['engine_id']=_source_code_fingerprint(root)
        report['ir_id']=ir.id
        nonimpact=_load_p1_scenario_nonimpact(root,class_key,level,scenario_id)
        native_source_spell_ids = {1082} if class_key.lower() == 'druid' and level == 20 else set()
        native_executor = None
        if native_source_spell_ids:
            from tools.wf_p1_native_effects import (
                DRUID_CLAW_RANK1, VERIFIED_EFFECT,
                build_druid_cat_action_request, run_native,
            )
            engine_root = root / 'integrations' / 'mythicsim-rust' / 'engine'
            binary = Path(
                os.environ.get('FOREVER_ENGINE_BINARY')
                or os.environ.get('FOREVER_MYTHICSIM_RUST_BIN')
                or str(engine_root / 'target' / 'debug' / 'forever-engine')
            )

            def native_executor(_ir, action, row):
                spell_id = int(row['spell_id'])
                if spell_id != DRUID_CLAW_RANK1 or action.id != 'claw:20':
                    return {
                        'status':'INVALID', 'native_status':'INVALID',
                        'reason':'P1_NATIVE_CLAW_SELECTOR_MISMATCH',
                        'effect_observed':False,
                    }
                request = build_druid_cat_action_request(engine_root, spell_id)
                result = run_native(
                    binary, request, class_key=class_key, level=level,
                    spell_id=spell_id, root=root, world_required=False,
                    scenario_label=f'p1-druid-l{level}-feral-claw-{spell_id}',
                )
                if result.get('status') == VERIFIED_EFFECT and result.get('effect_observed') is True:
                    return {
                        'status':'executed',
                        'native_status':result.get('status'),
                        'effect_observed':True,
                        'native_result':result,
                    }
                return {
                    'status':result.get('status','ERROR'),
                    'native_status':result.get('status','ERROR'),
                    'reason':result.get('reason') or result.get('stage'),
                    'effect_observed':False,
                    'native_result':result,
                }

        check=audit_inventory(rows,ir,parser=_source_spell_ids,
                  source_classifier=classify_indexed_ability,
                  policy_builder=from_source_rules,scratch_builder=scratch_policies,
                  executor=lambda i,a:_runtime_exercise(i,a,level),
                  effect_checker=effect_execution_kind,
                  native_source_spell_ids=native_source_spell_ids,
                  native_executor=native_executor,
                  scope_facts={**_load_spellbook_observed_scope_facts(root,
                      scope_meta.get('spellbook_file'),rows),
                      **_load_source_scope_facts(source_db,class_key)},
                  context_exclusions=scope_meta.get('scope_context_exclusions',{}),
                  scenario_nonimpact=nonimpact,scenario_id=scenario_id)
        report.update(check)
        report['reasons'] = [
            f"{issue['code']}:{issue['ability'] or ''}:{issue['detail'] or ''}"
            for issue in report['problems']
        ]
    except (ImportError,ModuleNotFoundError,AttributeError) as exc:
        report['reasons']=['PRODUCTION_BASELINE_IMPORT_FAILED:'+type(exc).__name__+':'+str(exc)]
    except (P1SetupError,sqlite3.Error,ValueError,RuntimeError,KeyError) as exc:
        report['reasons']=['P1_LIVE_SETUP_FAILED:'+type(exc).__name__+':'+str(exc)]
    finally:
        if sys.path and sys.path[0]==str(root):sys.path.pop(0)
    return report
