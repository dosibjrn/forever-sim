"""PROCESS v2.1 P1: source -> GameIR -> optimizer -> production runtime.

Class neutral. Never reads a user-written verdict/evidence JSON to award PASS.
This is a targeted, bounded *availability* smoke, not a P2 semantics test or P4 search.
This is a source-index effect diagnostic, not an acquisition proof. MythicSim
owns spell/rank legality; actual applicable effects must still be executed.
"""
from __future__ import annotations

import json
import hashlib
import os
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
                    scratch_builder, executor, higher_level_rows=(), max_errors=10000,
                    effect_checker=None, source_inactive_ids=None,
                    scope_facts=None, context_exclusions=None, scenario_nonimpact=None,
                    native_executor=None, scenario_id=P1_DEFAULT_SCENARIO):
    """PROCESS P1 gate: all source actions are traceable, legal, and offered.

    A recognized unmet conditional prerequisite is reported but cannot PASS
    without observed applicable execution (PROCESS v2.11). Unknown/no-op/broken
    effects and silent optimizer omissions are not accepted.
    """
    problems: list[dict[str,Any]] = []
    conditional: list[dict[str,str]] = []
    exercised: list[str] = []
    source_inactive_ids = source_inactive_ids or {}
    scope_facts = scope_facts or {}
    context_exclusions = context_exclusions or {}
    scenario_nonimpact = scenario_nonimpact or {}
    nonimpact: list[dict[str,Any]] = []
    native_probe_reports: list[dict[str,Any]] = []
    native_row_results: dict[int,dict[str,Any]] = {}
    native_outcomes: dict[str,dict[str,Any]] = {}
    def issue(code, row=None, detail=None):
        if len(problems) < max_errors:
            problems.append({'code':code, 'ability':_id_label(row) if row else None,
                             'detail':str(detail)[:240] if detail is not None else None})

    actions = tuple(a for a in ir.actions if a.owner_actor_id == ir.actor.id)
    indexed: dict[int,list] = {}
    for action in actions:
        if not isinstance(getattr(action,'effects',None),(list,tuple)):
            issue('INVALID_TYPED_ACTION', detail=action.id)
        for sid in _source_ids(action, parser):
            indexed.setdefault(sid,[]).append(action)
    if not actions:
        issue('EMPTY_GAME_IR')
    for row in higher_level_rows:
        if indexed.get(int(row['spell_id'])):
            issue('ILLEGAL_HIGH_LEVEL_ACTION_IN_GAME_IR',row)

    eligible: list[dict] = []
    ignored: list[dict] = []
    for row in source_rows:
        sid = int(row['spell_id'])
        if sid in source_inactive_ids:
            reason = source_inactive_ids[sid]
            ignored.append({'source_spell_id':sid,'role':'CONDITIONALLY_INACTIVE', 'reason':reason})
            if indexed.get(sid):
                issue('INACTIVE_SOURCE_ACTION_ENTERED_GAME_IR',row, reason)
            continue
        # Probe the selected source identity before asking whether GameIR can
        # represent it. Native INVALID/UNSUPPORTED remains authoritative.
        if native_executor is not None:
            try:
                native = native_executor(row, None)
            except Exception as exc:
                native = {
                    'outcome': {'status':'native_error','native_status':'ERROR',
                                'reason':f'{type(exc).__name__}:{exc}'},
                    'report': {'spell_id':sid,'status':'ERROR',
                               'reason':f'{type(exc).__name__}:{exc}',
                               'p1_certified':False},
                }
            if native is not None:
                if not isinstance(native, dict) or not isinstance(native.get('outcome'), dict):
                    issue('NATIVE_ACTION_PROBE_INVALID',row,'source identity probe')
                    native_row_results[sid] = {
                        'outcome': {'status':'native_error','native_status':'ERROR',
                                    'reason':'INVALID_NATIVE_ACTION_PROBE_RESULT'}}
                else:
                    native_row_results[sid] = native
                    summary = native.get('report')
                    if isinstance(summary, dict):
                        native_probe_reports.append(summary)
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
        if row.get('level_hint') is None:
            issue('UNRESOLVED_SOURCE_REQUIRED_LEVEL',row)
            continue
        eligible.append(row)

    # Rank reduction is an inventory optimisation, not proof of acquisition.
    highest = _highest_usable_ranks(eligible)
    checked = []
    for row in eligible:
        if row not in highest:
            ignored.append({'source_spell_id':int(row['spell_id']), 'role':'LOWER_LEARNED_RANK',
                            'reason':'P1_CHECKS_HIGHEST_USABLE_RANK_ONLY'})
    for row in highest:
        sid=int(row['spell_id'])
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
            native = native_row_results.get(sid)
            if native is not None:
                if not isinstance(native, dict) or not isinstance(native.get('outcome'), dict):
                    issue('NATIVE_ACTION_PROBE_INVALID', row, action.id)
                    native_outcomes[action.id] = {
                        'status':'native_error','native_status':'ERROR',
                        'reason':'INVALID_NATIVE_ACTION_PROBE_RESULT'}
                else:
                    native_outcomes[action.id] = native['outcome']
                # Native prepare/execute owns this action's validity and effects.
                # Keep only Forever's candidate/policy reachability check here.
                try:
                    p=policy_builder(ir,((action.id,()),))
                    if not any(rule.action_id==action.id for rule in p.rules):
                        issue('POLICY_DROPS_ACTION',row,action.id)
                except (TypeError,ValueError,KeyError) as exc:
                    issue('POLICY_CANNOT_REFER_TO_ACTION',row,
                          f'{action.id}:{type(exc).__name__}:{exc}')
                continue
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
            req_levels = [int(r['value']) for r in action.requirements
                          if hasattr(r, 'get') and r.get('kind')=='minimum_level' and r.get('value') is not None
                          and str(r['value']).isdigit()]
            if any(l > int(row['level_hint']) for l in req_levels):
                issue('WRONG_MINIMUM_LEVEL',row,f'{action.id}:{req_levels}')
            # Only an exact source-ID action is required to have this rank's
            # earliest level. A shared family action may legitimately map
            # multiple ranks and be promoted by the source rank overlay.
            if (action.id == f"source_spell:{int(row['spell_id'])}" and req_levels
                    and min(req_levels) < int(row['level_hint'])):
                issue('ACTION_AVAILABLE_BEFORE_SOURCE_LEVEL',row,f'{action.id}:{req_levels}')
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
        for action in indexed.get(int(row['spell_id']),()):
            try:
                outcome=native_outcomes.get(action.id)
                if outcome is None:
                    outcome=executor(ir,action)
            except Exception as exc:
                issue('COMBAT_RUNTIME_EXCEPTION',row,f'{action.id}:{type(exc).__name__}:{exc}')
                continue
            if outcome.get('status')=='executed' and outcome.get('effect_observed') is True:
                exercised.append(action.id)
            elif outcome.get('status') == 'native_refused':
                issue('NATIVE_ACTION_REFUSED',row,
                      f"{action.id}:{outcome.get('native_status')}:{outcome.get('reason')}")
            elif outcome.get('status') == 'native_no_effect':
                issue('NATIVE_ACTION_NO_EFFECT',row,
                      f"{action.id}:{outcome.get('reason')}")
            elif outcome.get('status') == 'native_error':
                issue('NATIVE_ACTION_EXECUTION_FAILED',row,
                      f"{action.id}:{outcome.get('native_status')}:{outcome.get('reason')}")
            elif (outcome.get('status')=='conditional' and
                  _legitimate_conditional(action, str(outcome.get('reason') or ''))):
                # A recognized prerequisite is a useful diagnostic, but it
                # does not demonstrate the ability's applicable effect.
                # PROCESS v2.11 requires a suitable triggered real-runtime
                # test before a source-legal conditional action can PASS P1.
                conditional.append({'action_id':action.id,'ability':_id_label(row),
                                    'reason':str(outcome['reason'])})
                issue('CONDITIONAL_EFFECT_NOT_EXECUTED',row,
                      f"{action.id}:{outcome['reason']}")
            else:
                issue('COMBAT_ACTION_NOT_EXECUTED',row,f'{action.id}:{outcome}')
    # PARTIAL diagnostic: numerator and denominator are the same real
    # source-eligible highest-rank ability units. Only a source action whose
    # observable effect executed in CombatRuntime contributes to the numerator.
    # No independent spell acquisition proof is required.
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
                p['code'] in ('UNRESOLVED_SOURCE_REQUIRED_LEVEL',
                              'P1_EFFECT_SCOPE_UNRESOLVED')
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
            'native_effect_probes':native_probe_reports,
            'native_effect_probe_count':len(native_probe_reports),
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


def _source_disabled_rune_ids(db_path: Path, class_key: str, level: int) -> dict[int,str]:
    """Mirror the production registry's default rune-off legality decision.

    Do not special-case a class or spell. Only recorded unverified rune grants
    without a level-legal, verified talent grant are conditionally inactive.
    """
    from src.game.data.forever.source_checkpoint_web_l0 import load_observations
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        db.row_factory = sqlite3.Row
        observations = load_observations(db, class_key)
        tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        talent_grants = set()
        if 'verified_talent_granted_action_facts' in tables:
            for sid, raw in db.execute('SELECT spell_id, action_json FROM verified_talent_granted_action_facts WHERE class_key=?', (class_key,)):
                required = json.loads(raw).get('required_level')
                if required is not None and int(required) <= level:
                    talent_grants.add(int(sid))
    return {int(sid):'rune_grant_unverified_default_off'
            for sid, obs in observations.items()
            if 'rune_grant_unverified' in obs.get('source_flags',())
            and int(sid) not in talent_grants}





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


def _native_p1_canary_probe(root: Path, spell_id: int) -> dict:
    """Run the one approved native P1 canary; source identity selects, Rust decides.

    This is deliberately limited to the Druid L60 Balance fixture already
    exercised by the selected-pin integration. It is not a spell-legality
    allowlist or a substitute for the remaining P1 denominator.
    """
    engine_root = root / 'integrations' / 'mythicsim-rust' / 'engine'
    fixture = engine_root / 'tests' / 'classes' / 'druid' / 'prepare' / 'balance.request.json'
    binary_value = (os.environ.get('FOREVER_MYTHICSIM_RUST_BIN')
                    or os.environ.get('FOREVER_ENGINE_BINARY'))
    if binary_value:
        binary = Path(binary_value)
    else:
        binary = engine_root / 'target' / 'release' / 'forever-engine'
        if not binary.is_file():
            binary = engine_root / 'target' / 'debug' / 'forever-engine'
    if not fixture.is_file():
        return {'status':'BLOCKED','stage':'request',
                'reason':'NATIVE_P1_CANARY_FIXTURE_MISSING',
                'native_executed':False,'effect_observed':False,
                'p1_certified':False}
    if not binary.is_file():
        return {'status':'BLOCKED','stage':'prepare',
                'reason':'SELECTED_RUST_BINARY_MISSING',
                'native_executed':False,'effect_observed':False,
                'p1_certified':False}
    try:
        request = json.loads(fixture.read_text(encoding='utf-8'))
        player = request['raid']['parties'][0]['players'][0]
        rows = player['rotation']['priorityList']
        fixture_spell_id = rows[0]['action']['castSpell']['spellId']['spellId']
        if (player.get('class') != 'ClassDruid' or len(rows) != 1
                or fixture_spell_id != spell_id):
            return {'status':'INVALID','stage':'request',
                    'reason':'NATIVE_P1_CANARY_FIXTURE_IDENTITY_MISMATCH',
                    'native_executed':False,'effect_observed':False,
                    'p1_certified':False}
        from src.engine_client.native_p1_effect_probe import run_native_p1_direct_effect_probe
        return run_native_p1_direct_effect_probe(
            binary=binary,
            engine_root=engine_root,
            request=request,
            spell_id=spell_id,
            timeout_seconds=120.0,
            iterations=10,
            seed=647003,
            target_count=2,
            world_mob_health=1200.0,
        )
    except Exception as exc:
        return {'status':'ERROR','stage':'native_adapter',
                'reason':f'{type(exc).__name__}:{exc}',
                'native_executed':False,'effect_observed':False,
                'p1_certified':False}


def _native_p1_probe_summary(report: dict, spell_id: int) -> dict:
    world = report.get('world_bridge')
    world = world if isinstance(world, dict) else {}
    return {
        'spell_id':spell_id,
        'status':report.get('status'),
        'stage':report.get('stage'),
        'reason':report.get('reason'),
        'executor':report.get('executor','msim-rust'),
        'native_executed':report.get('native_executed') is True,
        'effect_observed':report.get('effect_observed') is True,
        'controlled_behavior_assertion_passed':
            report.get('controlled_behavior_assertion_passed') is True,
        'engine_identity':report.get('engine_identity'),
        'dps_with_action':report.get('dps_with_action'),
        'dps_without_action':report.get('dps_without_action'),
        'dps_delta':report.get('dps_delta'),
        'world_targets_killed':world.get('world_targets_killed'),
        'native_damage_events':world.get('native_damage_events'),
        'actual_2d_ack':world.get('actual_2d_ack'),
        'p1_certified':False,
    }


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
        from src.game.runtime.effect_capabilities import effect_execution_kind
        source_db=Path(db_override or DEFAULT_DB)
        if not source_db.is_absolute():source_db=root/source_db
        if not source_db.is_file():raise P1SetupError('SOURCE_DB_NOT_FOUND:'+str(source_db))
        rows=_source_rows(source_db,class_key,level)
        inactive_ids=_source_disabled_rune_ids(source_db,class_key,level)
        excluded_high_level=[r for r in _source_rows(source_db,class_key,None)
                              if r["level_hint"] is not None and int(r["level_hint"])>level]
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
        native_probe_cache = {}
        def native_executor(row, action):
            sid = int(row['spell_id'])
            # The source ID is only a test selector. MythicSim prepare/execute
            # decides whether it is valid/supported and whether it has an effect.
            if not (class_key.strip().lower() == 'druid' and level == 60
                    and spec == 'balance' and scenario_id == P1_DEFAULT_SCENARIO
                    and sid == 9912):
                return None
            if sid not in native_probe_cache:
                native_report = _native_p1_canary_probe(root, sid)
                status = native_report.get('status')
                if (status == 'NATIVE_DIRECT_BEHAVIOR_VERIFIED'
                        and native_report.get('native_executed') is True
                        and native_report.get('effect_observed') is True
                        and native_report.get('controlled_behavior_assertion_passed') is True):
                    outcome = {'status':'executed','effect_observed':True,
                               'native_status':status}
                elif status in ('INVALID','UNSUPPORTED'):
                    outcome = {'status':'native_refused','native_status':status,
                               'reason':native_report.get('reason')}
                elif status == 'NO_DIRECT_EFFECT_OBSERVED':
                    outcome = {'status':'native_no_effect','native_status':status,
                               'reason':native_report.get('reason') or
                                         'NATIVE_DIRECT_EFFECT_NOT_OBSERVED'}
                else:
                    outcome = {'status':'native_error','native_status':status or 'ERROR',
                               'reason':native_report.get('reason')}
                native_probe_cache[sid] = {
                    'outcome':outcome,
                    'report':_native_p1_probe_summary(native_report,sid),
                }
            return native_probe_cache[sid]
        check=audit_inventory(rows,ir,parser=_source_spell_ids,
                  source_classifier=classify_indexed_ability,
                  policy_builder=from_source_rules,scratch_builder=scratch_policies,
                  executor=lambda i,a:_runtime_exercise(i,a,level),
                  higher_level_rows=excluded_high_level, effect_checker=effect_execution_kind,
                  source_inactive_ids=inactive_ids,
                  scope_facts={**_load_spellbook_observed_scope_facts(root,
                      scope_meta.get('spellbook_file'),rows),
                      **_load_source_scope_facts(source_db,class_key)},
                  context_exclusions=scope_meta.get('scope_context_exclusions',{}),
                  scenario_nonimpact=nonimpact,native_executor=native_executor,
                  scenario_id=scenario_id)
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
