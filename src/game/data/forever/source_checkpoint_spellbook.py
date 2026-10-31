"""Versioned client-spellbook evidence for a checkpoint's learnable action universe.

The evidence JSON is data, never game rules in the optimizer. It records the
external source's learned-at-level table, not a claim of server possession or
raw HTML integrity. Internal effects/runes do not become learned abilities.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path


class SourceSpellbook:
    @staticmethod
    def _assert_exact_source_identity(exact_ids: dict, action: dict) -> None:
        key = (action['name'], int(action['learned_level']))
        bound_id = exact_ids.get(key)
        if bound_id is not None and bound_id != int(action['spell_id']):
            raise ValueError('SPELLBOOK_EXACT_SOURCE_ID_MISMATCH')

    def __init__(self, path: str | Path, *, class_key: str, level: int, use_runes: bool = False):
        data = Path(path).read_bytes()
        self.sha256 = sha256(data).hexdigest()
        self.data = json.loads(data)
        d = self.data
        if d.get('schema') != 'forever_spellbook_level_ranks_v1':
            raise ValueError('UNSUPPORTED_SPELLBOOK_EVIDENCE_SCHEMA')
        if d['class_key'] != class_key.lower() or not d['level_range_covered'][0] <= level <= d['level_range_covered'][1]:
            raise ValueError('SPELLBOOK_CLASS_OR_LEVEL_MISMATCH')
        if bool(d.get('runes_enabled')) != bool(use_runes):
            raise ValueError('SPELLBOOK_RUNE_POLICY_MISMATCH')
        if not str(d.get('build','')).startswith('1.60.1.') or not d.get('source_url','').startswith('https://'):
            raise ValueError('SPELLBOOK_SOURCE_BUILD_OR_URL_UNVERIFIED')
        if sum(map(len,d['learned_by_level'].values())) != d['expected_learned_rows']:
            raise ValueError('SPELLBOOK_SOURCE_ROW_COUNT_MISMATCH')
        # Optional source-per-proxy evidence for snapshots that carry
        # qualitative L0 opportunities. The checkpoint is not allowed to
        # turn an undocumented arbitrary positive number into a rankable
        # action. Older snapshots without this field retain their original
        # contract; new snapshots may opt into stronger provenance checking.
        proxy_urls=d.get('contextual_proxy_source_urls_by_name')
        if proxy_urls is not None:
            proxies=d.get('contextual_numeric_proxies_by_name',{})
            if set(proxy_urls)!=set(proxies) or any(
                not isinstance(url,str) or not url.startswith('https://')
                for url in proxy_urls.values()):
                raise ValueError('SOURCE_L0_CONTEXT_PROXY_MISSING_PROVENANCE')
        self.level = level
        self.learned = {}
        for rawlevel, names in d['learned_by_level'].items():
            learnlevel = int(rawlevel)
            if not isinstance(names,list) or len(set(names)) != len(names):
                raise ValueError('SPELLBOOK_DUPLICATE_OR_INVALID_LEVEL_ROWS')
            if learnlevel <= level:
                for name in names:
                    key = (str(name), learnlevel)
                    if key in self.learned:
                        raise ValueError('SPELLBOOK_DUPLICATE_LEARNED_RANK')
                    self.learned[key] = 'PASSIVE' if name in d['non_cast_passives'] else (
                        'CONDITIONAL' if any(x['name'] == name and int(x['learned_level']) == learnlevel
                                             for x in d['conditional_talent_actions']) else 'LEARNED')
        # Conditional rank families are data-proven talent dependencies, not engine spell constants.
        families=d.get('conditional_rank_families',[])
        self.conditional_families={str(x['name']):x for x in families}
        if len(self.conditional_families)!=len(families):
            raise ValueError('SPELLBOOK_DUPLICATE_CONDITIONAL_RANK_FAMILY')
        for family in families:
            if not any(g['name']==family['name'] and int(g['spell_id'])==int(family['talent_spell_id'])
                       for g in d['conditional_talent_actions']):
                raise ValueError('SPELLBOOK_CONDITIONAL_FAMILY_UNBOUND_TO_TALENT_GRANT')
        # Optional exact-ID bindings prevent a same-name/same-level alternate
        # client spell (e.g. a Season of Discovery rank) from being legalized.
        self.exact_learned_ids = {}
        for raw_level, names in d.get('learned_exact_spell_ids_by_level', {}).items():
            learn_level = int(raw_level)
            for name, sid in names.items():
                if name not in d['learned_by_level'].get(str(learn_level), []) or int(sid) <= 0:
                    raise ValueError('SPELLBOOK_EXACT_ID_WITHOUT_LEARNED_ROW')
                self.exact_learned_ids[(name, learn_level)] = int(sid)
        for action in (*d['conditional_talent_actions'],
                       *d.get('source_only_learned_actions', [])):
            self._assert_exact_source_identity(self.exact_learned_ids, action)
        self.obsolete = {int(k):v for k,v in d['obsolete_or_ungranted_exact_spell_ids'].items()}
        self.grants = [g for g in d['conditional_talent_actions'] if int(g['learned_level']) <= level]
        self.grant_by_id = {int(g['spell_id']): g for g in self.grants}
        if len(self.grant_by_id) != len(self.grants):
            raise ValueError('SPELLBOOK_DUPLICATE_TALENT_GRANT')
        self.source_only = []
        for action in d.get('source_only_learned_actions', []):
            key = (action['name'], int(action['learned_level']))
            if key not in self.learned:
                if int(action['learned_level']) > level and action['name'] in d['learned_by_level'].get(str(action['learned_level']), []):
                    continue
                raise ValueError('SOURCE_ONLY_ACTION_NOT_IN_LEARNED_SPELLBOOK')
            if self.learned[key] != 'LEARNED':
                raise ValueError('SOURCE_ONLY_ACTION_NOT_IN_LEARNED_SPELLBOOK')
            if (not isinstance(action.get('source_url'), str)
                or not action['source_url'].startswith('https://')
                or int(action['spell_id']) <= 0):
                raise ValueError('SOURCE_ONLY_ACTION_WITHOUT_EXACT_SOURCE_ID')
            if not action.get('contextual_zero') and not any(
                float(v) > 0 for v in action.get('l0_domains', {}).values()):
                raise ValueError('SOURCE_ONLY_ACTION_WITHOUT_CONTEXTUAL_L0')
            if action.get('contextual_zero') and action.get('l0_domains'):
                raise ValueError('SOURCE_ONLY_ACTION_CONTRADICTORY_CONTEXT_L0')
            self.source_only.append(action)
        if len({int(a['spell_id']) for a in self.source_only}) != len(self.source_only):
            raise ValueError('DUPLICATE_SOURCE_ONLY_ACTION_ID')
        if len({int(g['spell_id']) for g in self.grants}) != len(self.grants):
            raise ValueError('SPELLBOOK_DUPLICATE_TALENT_GRANT')

    @staticmethod
    def _grant_index_level_is_sourced(grant: dict, level_hint: int | None) -> bool:
        levels = {int(grant['learned_level'])}
        if grant.get('source_index_level_hint_override') is not None:
            levels.add(int(grant['source_index_level_hint_override']))
        return level_hint in levels

    def source_decision(self, row: dict) -> tuple[str,str] | None:
        sid=int(row['spell_id'])
        grant = self.grant_by_id.get(sid)
        if grant is not None:
            if row['name'] != grant['name']:
                raise ValueError('TALENT_GRANT_EXACT_ID_NAME_MISMATCH')
            if not self._grant_index_level_is_sourced(grant, row.get('source_level_hint')):
                return 'ILLEGAL', 'TALENT_GRANT_SOURCE_LEVEL_NOT_PROVEN'
            return 'CONDITIONAL', 'CLIENT_SPELLBOOK_EXACT_TALENT_GRANT_ID'
        if sid in self.obsolete:
            return 'ILLEGAL','EXACT_ID_OBSOLETE_OR_NOT_LEARNED_IN_CLIENT_SPELLBOOK'
        key=(row['name'],row.get('source_level_hint'))
        learned=self.learned.get(key)
        exact_id = self.exact_learned_ids.get(key)
        if learned is not None and exact_id is not None and sid != exact_id:
            return 'ILLEGAL', 'SAME_NAME_LEVEL_ALTERNATE_ID_NOT_CLIENT_SPELLBOOK'
        if learned=='LEARNED':
            if row['name'] in self.conditional_families:
                return 'CONDITIONAL','CLIENT_SPELLBOOK_RANK_REQUIRES_TALENT_FAMILY'
            return 'LEGAL','CLIENT_SPELLBOOK_EXACT_NAME_AND_LEARN_LEVEL'
        if learned=='PASSIVE':
            return 'PASSIVE','CLIENT_SPELLBOOK_AUTOMATIC_PASSIVE_NOT_PLAYER_CAST'
        if learned=='CONDITIONAL':
            # An old spell with the same name cannot impersonate a new talent
            # grant. Require the exact source grant ID.
            return 'UNRESOLVED','TALENT_GRANT_IDENTITY_MISMATCH'
        # A complete learned-rank spellbook provides negative evidence for
        # standalone action availability, but only within its build and level.
        # The spell may still exist as a triggered effect: P1 concerns casts.
        return 'ILLEGAL','NOT_A_LEARNED_STANDALONE_ACTION_IN_CLIENT_SPELLBOOK'

    def conditional_rank_requirement(self, row: dict) -> dict | None:
        """Expose a rank's sourced prerequisite without teaching the rank for free."""
        family=self.conditional_families.get(row['name'])
        if family is None or (row['name'],row.get('source_level_hint')) not in self.learned:
            return None
        return {'talent_spell_id':int(family['talent_spell_id']),
                'talent_name':family['name'], 'source_url':family['source_url']}

    def contextual_proxy(self, row: dict) -> tuple[dict[str,float],str | None]:
        name=row['name']
        numeric=dict(self.data['contextual_numeric_proxies_by_name'].get(name,{}))
        if (name,row.get('source_level_hint')) in self.learned and self.learned[(name,row.get('source_level_hint'))]=='PASSIVE':
            numeric.update(self.data.get('passive_numeric_by_name',{}).get(name,{}))
        observed=self.data.get('observed_rank_numeric_by_id',{}).get(str(row['spell_id']))
        if observed is not None:
            if (observed['name'],int(observed['learned_level'])) != (name,row.get('source_level_hint')):
                raise ValueError('SOURCE_NUMERIC_RANK_IDENTITY_MISMATCH')
            numeric.update({k:float(v) for k,v in observed['domains'].items()})
        return (numeric, self.data['contextual_zero_when_solo_land_mob_no_allies_or_debuffs'].get(name))

    def coverage(self, index_rows: list[dict]) -> dict:
        seen={(r['name'],r.get('source_level_hint')) for r in index_rows if 'name' in r}
        missing=[]
        source_only={(a['name'],int(a['learned_level'])) for a in self.source_only}
        for (name,level),role in sorted(self.learned.items(),key=lambda x:(x[0][1],x[0][0])):
            if role in ('PASSIVE','CONDITIONAL'):
                continue
            if (name,level) not in seen and (name,level) not in source_only:
                missing.append({'name':name,'learned_level':level,'role':role})
        return {'learned_rows_through_level':len(self.learned),
                'missing_learned_action_rows':missing,
                'conditional_grants':len(self.grants),
                'source_build':self.data['build'],
                'source_url':self.data['source_url'],
                'snapshot_sha256':self.sha256,
                'source_kind':self.data['source_kind']}
