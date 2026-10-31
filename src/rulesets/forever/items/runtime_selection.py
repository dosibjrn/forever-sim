from __future__ import annotations

"""Runtime selection from the pinned Forever item catalogue.

This module is intentionally small and deterministic.  It never talks to the
network: service refresh/add-item operations update the pinned SQLite snapshot,
and the simulators consume that snapshot here.

Client raw stat columns (hit/crit/dodge) are retained here; they correspond
to displayed chance percentages at sourced fixed factors (10/14/12 raw points
per +1%), independently of level. Defense is a skill value. Conversion is in
source_checkpoint_p3_ratings rather than this catalogue reader.
"""

from dataclasses import dataclass
from pathlib import Path
import os
import json
from typing import Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from .catalogue import ItemCatalogue, ItemRecord
from .wowhead_queries import CANONICAL_CLASS_QUERIES

CLASS_IDS = {key: query.class_id for key, query in CANONICAL_CLASS_QUERIES.items()}
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DB = _REPO_ROOT / "data" / "forever" / "catalogue" / "items_2026-09-29.sqlite"

BODY_SLOTS = ("head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet")

# Classic/Forever proficiency envelope.  Class-eligibility from Wowhead is the
# first gate; these sets prevent list-view class filtering from admitting a
# weapon family the class cannot actually equip.
_WEAPONS = {
    "mage": {"dagger", "sword", "staff", "wand"},
    "hunter": {"axe", "two_hand_axe", "dagger", "fist", "polearm", "staff", "sword", "two_hand_sword", "bow", "crossbow", "gun"},
    "druid": {"dagger", "mace", "two_hand_mace", "staff", "fist"},
    "paladin": {"axe", "two_hand_axe", "mace", "two_hand_mace", "sword", "two_hand_sword", "polearm"},
}

_ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    "mage": {"intellect": 1.00, "spell_power": 1.18, "spirit": .34, "mp5": .55, "stamina": .05, "wand_dps": 1.0},
    "druid_feral": {"agility": 1.00, "strength": .95, "attack_power": .50, "stamina": .18, "armor": .0015, "weapon_dps": .35},
    "druid_bear": {"stamina": 1.00, "armor": .012, "agility": .35, "strength": .45, "attack_power": .20, "weapon_dps": .10},
    "druid_balance": {"spell_power": 1.20, "intellect": 1.00, "spirit": .35, "mp5": .70, "stamina": .08},
    "paladin_ret": {"weapon_dps": 5.0, "strength": 1.00, "attack_power": .50, "stamina": .20, "intellect": .25, "spell_power": .35, "mp5": .20},
    "paladin_tank": {"weapon_dps": 1.5, "stamina": 1.00, "armor": .010, "strength": .55, "intellect": .55, "spell_power": .55, "mp5": .65, "healing": .05},
    "hunter": {"agility": 1.00, "attack_power": .50, "intellect": .28, "spirit": .16, "mp5": .38, "stamina": .18, "armor": .001, "weapon_dps": 5.0},
}


_GEAR_OVERRIDES: ContextVar[dict[str, int] | None] = ContextVar("forever_gear_overrides", default=None)

@contextmanager
def gear_overrides(overrides: Mapping[str, int] | None):
    """Temporarily pin exact item ids to published equipment slots.

    The generic catalogue selector still optimizes every unpinned slot. Invalid
    or ineligible item ids fail closed instead of silently falling back.
    """
    normalized = None if not overrides else {str(k): int(v) for k, v in overrides.items()}
    token = _GEAR_OVERRIDES.set(normalized)
    try:
        yield
    finally:
        _GEAR_OVERRIDES.reset(token)


def _apply_gear_overrides(class_key: str, level: int, selected: dict[str, ItemRecord],
                          *, required_level_policy: str = "catalogue") -> dict[str, ItemRecord]:
    overrides = _GEAR_OVERRIDES.get()
    if not overrides:
        return selected
    legal = {int(x.item_id): x for x in available_items(class_key, level, required_level_policy=required_level_policy)}
    out = dict(selected)
    for slot, item_id in overrides.items():
        item = legal.get(int(item_id))
        if item is None:
            # A selected-level lock may refer to an item that is not yet legal in
            # earlier continuity/bootstrap levels. Keep optimizing that slot until
            # the item reaches its required level; once it should be legal, fail
            # closed for class/proficiency/source incompatibility.
            try:
                with ItemCatalogue(catalogue_path(), readonly=True) as cat:
                    future = cat.get_item(int(item_id))
            except Exception:
                future = None
            if future is not None and future.required_level is not None and int(level) < int(future.required_level):
                continue
            raise ValueError(f"gear override {slot}=#{item_id} is not legal/available for {class_key} at L{level}")
        # Slot compatibility: body slots are exact; virtual weapon/ring/trinket
        # slots are intentionally accepted because the selector publishes those.
        raw = str(item.slot or '')
        if slot in (*BODY_SLOTS, 'shirt', 'relic') and raw != slot:
            raise ValueError(f"gear override {slot}=#{item_id} has incompatible source slot {raw}")
        if slot.startswith('ring') and raw != 'finger':
            raise ValueError(f"gear override {slot}=#{item_id} is not a ring")
        if slot.startswith('trinket') and raw != 'trinket':
            raise ValueError(f"gear override {slot}=#{item_id} is not a trinket")
        if slot == 'ranged' and raw != 'ranged':
            raise ValueError(f"gear override ranged=#{item_id} is not ranged")
        if slot == 'wand' and not (raw == 'ranged' and item.weapon_type == 'wand'):
            raise ValueError(f"gear override wand=#{item_id} is not a wand")
        if slot == 'weapon' and raw not in {'one_hand','main_hand','two_hand'}:
            raise ValueError(f"gear override weapon=#{item_id} is not a main-hand weapon")
        if slot == 'offhand' and raw not in {'one_hand','off_hand'}:
            raise ValueError(f"gear override offhand=#{item_id} is not offhand-equippable")
        out[slot] = item
    # A selector's automatically chosen offhand is not a locked requirement.
    # A locked two-hand weapon must evict that implicit offhand; explicitly
    # locking both remains an illegal package and is rejected below.
    locked_twohand = ('weapon' in overrides and 'weapon' in out
                      and (out['weapon'].weapon_hands == 2
                           or out['weapon'].slot == 'two_hand'))
    if locked_twohand and 'offhand' not in overrides:
        out.pop('offhand', None)
    # Source-profile weapon legality is checked on the *combined* final
    # equipment, not one slot at a time. Never let an override construct an
    # impossible two-hand+offhand or duplicate weapon loadout.
    if 'weapon' in out and 'offhand' in out:
        if out['weapon'].weapon_hands == 2 or out['weapon'].slot == 'two_hand':
            raise ValueError('ILLEGAL_TWO_HAND_AND_OFFHAND_PACKAGE')
        if out['weapon'].item_id == out['offhand'].item_id:
            raise ValueError('DUPLICATE_MAIN_AND_OFFHAND_ITEM')
        profile=_source_class_profile(class_key)
        if profile:
            if out['offhand'].armor_type == 'shield':
                if level < int(profile.get('offhand_shield_min_level', 999)):
                    raise ValueError('SHIELD_NOT_YET_PROFICIENT')
            elif out['offhand'].weapon_type:
                if out['offhand'].slot != 'one_hand' or level < int(profile.get('dual_wield_min_level', 999)):
                    raise ValueError('DUAL_WIELD_NOT_YET_PROFICIENT')
    from .source_equipment_semantics import validate_equipped_item_ids
    validate_equipped_item_ids(x.item_id for x in out.values())
    return out


def catalogue_path() -> Path:
    return Path(os.environ.get("FOREVER_ITEM_CATALOGUE", _DEFAULT_DB))


@lru_cache(maxsize=8)
def _source_class_profile(class_key: str) -> dict | None:
    """Versioned *data* supplies new class proficiencies; no item membership inferred.

    A class profile cannot replace source item_class_eligibility rows.  That
    distinction prevents an apparently complete P3 from an empty class list.
    """
    p=_REPO_ROOT / 'data' / 'forever' / 'source_profiles' / f'{class_key}_70338.json'
    if not p.exists():
        return None
    obj=json.loads(p.read_text())
    if obj.get('schema')!='forever_source_class_equipment_profile_v1' or obj.get('class_key')!=class_key:
        raise ValueError('INVALID_SOURCE_CLASS_PROFILE')
    if not obj.get('sources') or not all(x.get('url','').startswith('https://') for x in obj['sources']):
        raise ValueError('UNSOURCED_CLASS_PROFILE')
    if int(obj.get('class_id',0))<=0:
        raise ValueError('INVALID_SOURCE_CLASS_ID')
    return obj


def _source_class_id(class_key: str) -> int | None:
    if class_key in CLASS_IDS:
        return CLASS_IDS[class_key]
    profile=_source_class_profile(class_key)
    return int(profile['class_id']) if profile else None


def source_class_item_membership_verified(class_key: str, db_path: Path) -> bool:
    """A source class proficiency is NOT a complete item membership proof.

    Explicit source-capture attestation binds the count and provenance in the
    staged SQLite. Provisional rows never certify a P3 denominator.
    """
    class_id = _source_class_id(class_key)
    if class_id is None:
        return False
    import sqlite3
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='class_source_attestation'").fetchone():
            return False
        columns={r[1] for r in db.execute('PRAGMA table_info(class_source_attestation)')}
        if 'membership_sha256' not in columns:
            return False
        rows=db.execute('SELECT source_kind,source_sha256,member_count,verified,membership_sha256 FROM class_source_attestation WHERE class_id=?',
            (int(class_id),)).fetchall()
        if len(rows)!=1 or rows[0][0] not in ('VERIFIED_CLASS_LISTVIEW_CAPTURE','VERIFIED_CLASS_LISTVIEW_EXPORT') or not rows[0][1] or not rows[0][3]:
            return False
        memberships=db.execute('SELECT item_id,provenance FROM item_class_eligibility WHERE class_id=? ORDER BY item_id,provenance',
            (int(class_id),)).fetchall()
    from hashlib import sha256
    membership_bytes=''.join(f'{iid}\t{p}\n' for iid,p in memberships).encode('utf-8')
    return (bool(memberships) and len(memberships)==int(rows[0][2])
            and sha256(membership_bytes).hexdigest()==rows[0][4] and all(
                p.startswith('https://www.wowhead.com/forever/items/')
                and (f"class:{class_id}" in p or f"class%3A{class_id}" in p)
                for _,p in memberships))


def _armor_allowed(class_key: str, level: int, item: ItemRecord) -> bool:
    if item.slot not in set(BODY_SLOTS):
        return True
    armor = str(item.armor_type or "")
    if armor in {"", "misc"}:
        return True
    profile=_source_class_profile(class_key)
    if profile:
        minimum=profile['armor_min_level'].get(armor)
        return minimum is not None and level>=int(minimum)
    if class_key == "mage":
        return armor == "cloth"
    if class_key == "druid":
        return armor in {"cloth", "leather"}
    if class_key == "hunter":
        return armor in ({"cloth", "leather", "mail"} if int(level) >= 40 else {"cloth", "leather"})
    if class_key == "paladin":
        return armor in ({"cloth", "leather", "mail", "plate"} if int(level) >= 40 else {"cloth", "leather", "mail"})
    return False


def _not_obvious_internal_item(item: ItemRecord) -> bool:
    name=str(item.name or "").strip().lower()
    if not name: return False
    bad=("dnt ","test copy","deprecated","unused","placeholder","qa test","[ph]","zzold")
    return not any(token in name for token in bad)


def _weapon_allowed(class_key: str, item: ItemRecord, level: int = 60) -> bool:
    if not item.weapon_type:
        return True
    profile=_source_class_profile(class_key)
    if profile:
        minimum=profile['weapon_min_level'].get(item.weapon_type)
        return minimum is not None and int(level)>=int(minimum)
    return item.weapon_type in _WEAPONS[class_key]


def catalogue_signature() -> tuple[str, int, int, int, int]:
    path=catalogue_path()
    if not path.exists():
        return (str(path),0,0,0,0)
    st=path.stat(); wal=Path(str(path)+"-wal")
    if wal.exists():
        wst=wal.stat(); wm,ws=int(wst.st_mtime_ns),int(wst.st_size)
    else:
        wm,ws=0,0
    return (str(path),int(st.st_mtime_ns),int(st.st_size),wm,ws)


_AVAILABLE_ITEMS_CACHE: dict[tuple[str, int, str, str], tuple[ItemRecord, ...]] = {}


def available_items(class_key: str, level: int, *, required_level_policy: str = "catalogue") -> tuple[ItemRecord, ...]:
    """Return legal rows, reading SQLite at most once per class/level/path.

    The optimizer is a long-lived process and the catalogue is immutable during
    a compute job.  A plain dict is intentional here: repeated gear/stat-weight
    probes should rank the same in-memory rows rather than reopen SQLite.
    Service-side catalogue mutations explicitly clear this cache.
    """
    if required_level_policy not in {"catalogue", "observed"}:
        raise ValueError("required_level_policy must be catalogue or observed")
    class_key=str(class_key).lower(); level=int(level); path=catalogue_path()
    _sync_catalogue_path(path)
    from .source_equipment_semantics import ledger_path
    sem_path=ledger_path();sem_stat=sem_path.stat()
    key=(class_key,level,str(path),required_level_policy,
         str(sem_path.resolve()),sem_stat.st_mtime_ns,sem_stat.st_size)
    if key not in _AVAILABLE_ITEMS_CACHE:
        if _source_class_id(class_key) is None or not path.exists():
            _AVAILABLE_ITEMS_CACHE[key]=()
        else:
            with ItemCatalogue(path, readonly=True) as cat:
                rows=cat.eligible_items(class_id=_source_class_id(class_key),level=level)
            # A source item can be labelled "Relic Idol" yet be a rune-teaching
            # consumable, not equippable.  The typed SQLite ledger (not a slot
            # blacklist or optimizer item-ID whitelist) resolves that ambiguity.
            from .source_equipment_semantics import semantic_for_item
            _AVAILABLE_ITEMS_CACHE[key]=tuple(
                x for x in rows
                if (semantic_for_item(x) is None or
                    semantic_for_item(x).equip_semantics != 'NON_EQUIPPABLE_RUNE_LEARNING_ITEM')
                and _not_obvious_internal_item(x)
                # A source-listed consumable with no equip slot is not gear.
                # Keep unknown nonempty slots visible to the P3 fail-closed
                # slot mapper rather than silently discarding legal equipment.
                and bool(str(x.slot or '').strip())
                and _armor_allowed(class_key,level,x)
                and _weapon_allowed(class_key,x,level)
                and (required_level_policy == "catalogue" or (
                    x.required_level_origin in ("observed", "source_confirmed_no_requirement")
                    and x.required_level is not None
                    and ((x.source_type == "foreverdb_client"
                          and x.fetch_status == "verified_detail"
                          and x.identity_origin == "foreverdb_client")
                         or (x.source_type == "wowhead_listview"
                          and x.fetch_status == "verified_listview"
                          and x.identity_origin == "wowhead_listview")
                         or (x.source_type == "wowhead_detail"
                             and x.fetch_status == "verified"
                             and x.identity_origin == "wowhead_item"))))
            )
    return _AVAILABLE_ITEMS_CACHE[key]


def damage_spell_power(item: ItemRecord) -> float:
    """Best source-backed generic damage-SP field currently available.

    Wowhead listview uses both ``splpwr`` and legacy ``spldmg``.  They are not
    blindly summed because the fields can overlap semantically.  Until the
    tooltip importer gives us a typed damage/healing split, use the larger
    explicit magnitude and preserve both raw fields in listener metadata.
    """
    return max(float(item.spell_power or 0.0), float(item.extra_stats.get("spldmg", 0.0) or 0.0))


_ITEM_VECTOR_CACHE: dict[int, dict[str, float]] = {}
_ITEM_SCORING_VECTOR_CACHE: dict[int, dict[str, float]] = {}
_ACTIVE_CATALOGUE_PATH_KEY: str | None = None

def _sync_catalogue_path(path: Path) -> None:
    """Keep process-local item caches tied to one catalogue snapshot path.

    Gear selection always enters through ``available_items`` first.  Detecting a
    path switch there lets innermost item-vector/effective-level lookups use an
    integer item id without repeated environment/path normalization.
    """
    global _ACTIVE_CATALOGUE_PATH_KEY
    key=str(path)
    if _ACTIVE_CATALOGUE_PATH_KEY is None:
        _ACTIVE_CATALOGUE_PATH_KEY=key
        return
    if key != _ACTIVE_CATALOGUE_PATH_KEY:
        _AVAILABLE_ITEMS_CACHE.clear()
        _EFFECTIVE_LEVEL_CACHE.clear()
        _ITEM_VECTOR_CACHE.clear()
        _ACTIVE_CATALOGUE_PATH_KEY=key

def item_vector(item: ItemRecord) -> dict[str, float]:
    key=int(item.item_id)
    cached=_ITEM_VECTOR_CACHE.get(key)
    if cached is not None:
        return cached
    value={
        "strength": float(item.strength), "agility": float(item.agility), "stamina": float(item.stamina),
        "intellect": float(item.intellect), "spirit": float(item.spirit), "attack_power": float(item.attack_power),
        "spell_power": damage_spell_power(item), "healing": float(item.healing), "mp5": float(item.mp5),
        "armor": float(item.armor) + float(item.bonus_armor), "weapon_dps": float(item.weapon_dps),
        "wand_dps": float(item.weapon_dps) if item.weapon_type == "wand" else 0.0,
    }
    _ITEM_VECTOR_CACHE[key]=value
    return value


def item_scoring_vector(item: ItemRecord) -> dict[str, float]:
    """Ordinary scored source stats; never imply support for item procs.

    Melee, wand and ranged DPS are separate alternatives. Raw listview chance
    fields remain in their SOURCE units; no invented rating conversion.
    Reuse the immutable per-catalogue item vector in the hot gear-search path.
    """
    cached = _ITEM_SCORING_VECTOR_CACHE.get(int(item.item_id))
    if cached is not None:
        return cached
    value = dict(item_vector(item))
    if str(item.weapon_type) == 'wand':
        value['weapon_dps'] = 0.0
    elif str(item.slot) in ('ranged','thrown'):
        value['ranged_weapon_dps'] = value.pop('weapon_dps', 0.0)
        value['wand_dps'] = 0.0
    else:
        value['wand_dps'] = 0.0
    if str(item.slot) in ('one_hand','main_hand','two_hand','off_hand'):
        value['mean_weapon_hit_damage'] = (
            float(item.weapon_min_damage or 0.) + float(item.weapon_max_damage or 0.)) / 2.
    for key in ('hit','crit','dodge','defense'):
        value[key] = float(getattr(item, key) or 0.)
    # Source raw rating and ranged AP are distinct inputs; do not invent
    # a conversion into avoidance chance or melee attack power.
    if float(item.extra_stats.get('parryrtng',0.) or 0.):
        value['parry'] = float(item.extra_stats['parryrtng'])
    if float(item.extra_stats.get('rgdatkpwr',0.) or 0.):
        value['ranged_attack_power'] = float(item.extra_stats['rgdatkpwr'])
    # Source mapping owns the meaning of healthrgn=HP5 (not plain health/sec).
    from .source_numeric_extras import modeled_source_numeric_extras
    for key, amount in modeled_source_numeric_extras(item).items():
        value[key] = value.get(key, 0.) + float(amount)
    _ITEM_SCORING_VECTOR_CACHE[int(item.item_id)] = value
    return value


def item_score(item: ItemRecord, weights: Mapping[str, float]) -> float:
    v = item_scoring_vector(item)
    return sum(float(weights.get(k, 0.0) or 0.0) * float(v.get(k, 0.0) or 0.0) for k in weights)


def _best(rows: Iterable[ItemRecord], weights: Mapping[str, float]) -> ItemRecord | None:
    rows = list(rows)
    if not rows:
        return None
    return max(rows, key=lambda x: (item_score(x, weights), int(x.required_level or 0), int(x.item_level or 0), -int(x.item_id)))


def _top_distinct(rows: Iterable[ItemRecord], weights: Mapping[str, float], count: int) -> list[ItemRecord]:
    ordered = sorted(rows, key=lambda x: (item_score(x, weights), int(x.required_level or 0), int(x.item_level or 0), -int(x.item_id)), reverse=True)
    return ordered[:count]


def _body_slots(rows: tuple[ItemRecord, ...], weights: Mapping[str, float]) -> dict[str, ItemRecord]:
    out: dict[str, ItemRecord] = {}
    # A source-verified relic or shirt is an actual equipment slot; never
    # silently omit it from a complete candidate merely because its effect
    # is passive rather than an additive item stat.
    for slot in (*BODY_SLOTS, 'shirt', 'relic'):
        best = _best((x for x in rows if x.slot == slot), weights)
        if best is not None:
            out[slot] = best
    rings = _top_distinct((x for x in rows if x.slot == "finger"), weights, 2)
    # Select the best *legal pair*, not the two best independent trinkets:
    # Forever has source-verified Unique-Equipped item groups that span IDs.
    from .source_equipment_semantics import validate_equipped_item_ids
    trinkets=[]
    for candidate in sorted((x for x in rows if x.slot=='trinket'),
            key=lambda x:(item_score(x,weights),int(x.required_level or 0),
                          int(x.item_level or 0),-int(x.item_id)),reverse=True):
        try:
            validate_equipped_item_ids([x.item_id for x in trinkets]+[candidate.item_id])
        except ValueError as exc:
            if ('BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP' not in str(exc)
                and 'DUPLICATE_EQUIPPED_ITEM' not in str(exc)):raise
            continue
        trinkets.append(candidate)
        if len(trinkets)==2:break
    for i, item in enumerate(rings, 1):
        out[f"ring{i}"] = item
    for i, item in enumerate(trinkets, 1):
        out[f"trinket{i}"] = item
    return out


def _weapon_rows(rows: tuple[ItemRecord, ...]) -> list[ItemRecord]:
    return [x for x in rows if x.slot in {"one_hand", "main_hand", "two_hand"} and x.weapon_type != "wand"]


@lru_cache(maxsize=128)
def _strict_source_effect_eligible_ids(class_key: str, level: int, required_level_policy: str,
                                      catalogue_key, semantic_key) -> frozenset[int]:
    from src.game.data.forever.source_checkpoint_p3 import source_item_l0
    return frozenset(int(x.item_id) for x in available_items(class_key,level,
        required_level_policy=required_level_policy) if source_item_l0(x)['l2_effect_fully_supported'])


def select_gear(class_key: str, level: int, role: str, *,
                weights: Mapping[str, float] | None = None,
                required_level_policy: str = "catalogue",
                exclude_unknown_item_effects: bool = False) -> dict[str, ItemRecord]:
    """Select one deterministic SQL-backed equipment set for a class/role."""
    class_key = str(class_key).lower(); level = int(level)
    rows = available_items(class_key, level, required_level_policy=required_level_policy)
    if exclude_unknown_item_effects:
        # Source-indexed item stats alone cannot prove on-equip proc semantics.
        # This restriction applies to FULL L2 candidate admission only, not
        # P3's complete proxy coverage of every legal catalogue item.
        from .source_equipment_semantics import ledger_path
        sem=ledger_path();sst=sem.stat()
        eligible=_strict_source_effect_eligible_ids(class_key,level,required_level_policy,
            catalogue_signature(),(str(sem.resolve()),sst.st_mtime_ns,sst.st_size))
        rows=tuple(x for x in rows if int(x.item_id) in eligible)
    profile = _source_class_profile(class_key)
    source_role = (profile or {}).get('gear_selection_roles', {}).get(role)
    if weights is not None:
        w = dict(weights)
    elif role in _ROLE_WEIGHTS:
        w = dict(_ROLE_WEIGHTS[role])
    elif source_role:
        # Search priors are explicitly heuristic, versioned data, not combat
        # coefficients or a substitute for the measured P3 stat weights.
        w = dict(source_role['proxy_weights'])
    else:
        raise ValueError(f'UNSUPPORTED_SOURCE_GEAR_ROLE:{class_key}:{role}')
    out = _body_slots(rows, w)

    if class_key == "mage":
        wand = _best((x for x in rows if x.slot == "ranged" and x.weapon_type == "wand"), w)
        if wand is not None:
            out["wand"] = wand
        weapons = _weapon_rows(rows)
        two = _best((x for x in weapons if x.weapon_hands == 2 or x.slot == "two_hand"), w)
        one = _best((x for x in weapons if x.weapon_hands != 2 and x.slot != "two_hand"), w)
        off = _best((x for x in rows if x.slot == "off_hand" and x.armor_type != "shield" and not x.weapon_type), w)
        packages: list[tuple[float, tuple[ItemRecord, ...]]] = []
        if two is not None:
            packages.append((item_score(two, w), (two,)))
        if one is not None:
            pack = (one,) + ((off,) if off is not None else ())
            packages.append((sum(item_score(x, w) for x in pack), pack))
        if packages:
            _, pack = max(packages, key=lambda p: (p[0], sum(int(x.item_level or 0) for x in p[1])))
            out["weapon"] = pack[0]
            if len(pack) > 1:
                out["offhand"] = pack[1]

    elif class_key == "druid":
        weapons = _weapon_rows(rows)
        if role == "druid_balance":
            two = _best((x for x in weapons if x.weapon_hands == 2 or x.slot == "two_hand"), w)
            one = _best((x for x in weapons if x.weapon_hands != 2 and x.slot != "two_hand"), w)
            off = _best((x for x in rows if x.slot == "off_hand" and x.armor_type != "shield" and not x.weapon_type), w)
            packages: list[tuple[float, tuple[ItemRecord, ...]]] = []
            if two is not None: packages.append((item_score(two, w), (two,)))
            if one is not None:
                pack = (one,) + ((off,) if off is not None else ())
                packages.append((sum(item_score(x, w) for x in pack), pack))
            if packages:
                _, pack = max(packages, key=lambda p: p[0])
                out["weapon"] = pack[0]
                if len(pack) > 1: out["offhand"] = pack[1]
        else:
            weapon = _best(weapons, w)
            if weapon is not None: out["weapon"] = weapon

    elif class_key == "paladin":
        weapons = _weapon_rows(rows)
        if role == "paladin_ret":
            weapon = _best((x for x in weapons if x.weapon_hands == 2 or x.slot == "two_hand"), w)
            if weapon is not None: out["weapon"] = weapon
        elif role == "paladin_tank":
            weapon = _best((x for x in weapons if x.weapon_hands != 2 and x.slot != "two_hand"), w)
            shield = _best((x for x in rows if x.slot == "off_hand" and x.armor_type == "shield"), w)
            if weapon is not None: out["weapon"] = weapon
            if shield is not None: out["offhand"] = shield

    elif class_key == "hunter":
        # Ranged weapon DPS is the primary weapon throughput input. Melee slots are
        # stat sticks only for this ranged leveling policy, so choose their package
        # without crediting melee weapon DPS.
        ranged = _best((x for x in rows if x.slot == "ranged" and x.weapon_type in {"bow", "crossbow", "gun"}), w)
        if ranged is not None:
            out["ranged"] = ranged
        statstick_w = dict(w); statstick_w["weapon_dps"] = 0.0
        weapons = _weapon_rows(rows)
        two = _best((x for x in weapons if x.weapon_hands == 2 or x.slot == "two_hand"), statstick_w)
        one = _best((x for x in weapons if x.weapon_hands != 2 and x.slot != "two_hand"), statstick_w)
        off = _best((x for x in rows if x.slot == "off_hand" and x.armor_type != "shield" and not x.weapon_type), statstick_w)
        packages: list[tuple[float, tuple[ItemRecord, ...]]] = []
        if two is not None:
            packages.append((item_score(two, statstick_w), (two,)))
        if one is not None:
            pack = (one,) + ((off,) if off is not None else ())
            packages.append((sum(item_score(x, statstick_w) for x in pack), pack))
        if packages:
            _, pack = max(packages, key=lambda p: (p[0], sum(int(x.item_level or 0) for x in p[1])))
            out["weapon"] = pack[0]
            if len(pack) > 1:
                out["offhand"] = pack[1]
    if source_role is not None:
        # Data-driven package selection for a class with a sourced equipment
        # proficiency profile. All candidates already passed SQLite class,
        # required-level, weapon-skill and armor-skill eligibility filtering.
        # Unrestricted discovery evaluates distinct role packages; this does
        # NOT lock the talent tree or infer that one role is optimal.
        strategy = source_role['weapon_package']
        melee = _weapon_rows(rows)
        two = _best((x for x in melee if x.weapon_hands == 2 or x.slot == 'two_hand'), w)
        one = _best((x for x in melee if x.weapon_hands != 2 and x.slot == 'one_hand'), w)
        if one is None:
            one = _best((x for x in melee if x.weapon_hands != 2 and x.slot == 'main_hand'), w)
        shield = _best((x for x in rows if x.slot == 'off_hand' and x.armor_type == 'shield'), w)
        off = _best((x for x in rows if x.slot == 'off_hand' and x.armor_type != 'shield' and not x.weapon_type), w)
        dual = _best((x for x in melee if x.slot == 'one_hand' and (one is None or x.item_id != one.item_id)), w)
        packages = []
        if two is not None and strategy in ('two_hand', 'best_package'):
            packages.append((two, None))
        if one is not None and strategy in ('one_hand_shield', 'best_package') and shield is not None:
            if int(level) >= int(profile.get('offhand_shield_min_level', 999)):
                packages.append((one, shield))
        if one is not None and strategy in ('dual_wield', 'best_package') and dual is not None:
            if int(level) >= int(profile.get('dual_wield_min_level', 999)):
                packages.append((one, dual))
        if one is not None and strategy == 'best_package':
            packages.append((one, off))
        if not packages:
            raise ValueError(f'NO_SOURCE_LEGAL_WEAPON_PACKAGE:{class_key}:{level}:{role}')
        weapon, secondary = max(packages, key=lambda p: (
            item_score(p[0], w) + (item_score(p[1], w) if p[1] else 0.),
            -int(p[0].item_id), -int(p[1].item_id) if p[1] else 0))
        out['weapon'] = weapon
        if secondary is not None:
            out['offhand'] = secondary
        ranged = _best((x for x in rows if x.slot in ('ranged', 'thrown')
                        and x.weapon_type in profile.get('ranged_weapon_types', ())), w)
        if ranged is not None:
            out['ranged'] = ranged
    from .source_equipment_semantics import validate_equipped_item_ids
    validate_equipped_item_ids(x.item_id for x in out.values())
    return _apply_gear_overrides(class_key, level, out, required_level_policy=required_level_policy)


def item_payload(item: ItemRecord, *, display_slot: str | None = None, effective_level: int | None = None) -> dict:
    v = item_vector(item)
    return {
        "item_id": int(item.item_id), "slot": str(display_slot or item.slot), "catalogue_slot": str(item.slot),
        "required_level_origin": item.required_level_origin,
        "name": item.name, "item_level": item.item_level, "required_level": item.required_level,
        "effective_level": effective_level, "quality": item.quality, "armor_type": item.armor_type,
        "weapon_type": item.weapon_type, "weapon_hands": item.weapon_hands,
        "weapon_dps": float(item.weapon_dps), "weapon_speed": float(item.weapon_speed),
        **v,
        "hit_rating": float(item.hit), "crit_rating": float(item.crit), "defense_rating": float(item.defense), "dodge_rating": float(item.dodge),
        "raw_spell_power": float(item.spell_power), "raw_spldmg": float(item.extra_stats.get("spldmg", 0.0) or 0.0),
        "source_type": item.source_type, "source": item.source_name, "source_url": item.source_url,
        "identity_origin": item.identity_origin, "fetch_status": item.fetch_status,
        "modeled": False, "model_kind": "canonical_sqlite_item",
    }


_EFFECTIVE_LEVEL_CACHE: dict[int, int | None] = {}


def effective_level(item: ItemRecord) -> int | None:
    """Return one item's availability floor, cached in process memory.

    Cache lookup deliberately happens before ``Path.exists()``.  This function
    is called from hot gear-ranking loops, and the previous ordering issued a
    filesystem stat for every lookup even after the item value was cached.
    """
    key = int(item.item_id)
    cached = _EFFECTIVE_LEVEL_CACHE.get(key, ...)
    if cached is not ...:
        return cached
    path = catalogue_path()
    _sync_catalogue_path(path)
    if not path.exists():
        value=item.required_level
    else:
        with ItemCatalogue(path, readonly=True) as cat:
            value=cat.effective_required_level(item)
    _EFFECTIVE_LEVEL_CACHE[key]=value
    return value


def clear_runtime_item_cache() -> None:
    """Invalidate process-local catalogue reads after a catalogue mutation."""
    global _ACTIVE_CATALOGUE_PATH_KEY
    _AVAILABLE_ITEMS_CACHE.clear()
    _EFFECTIVE_LEVEL_CACHE.clear()
    _ITEM_VECTOR_CACHE.clear()
    _strict_source_effect_eligible_ids.cache_clear()
    _ACTIVE_CATALOGUE_PATH_KEY=None
