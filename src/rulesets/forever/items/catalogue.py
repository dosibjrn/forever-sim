from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Mapping


SCHEMA_VERSION = 2
_ITEM_ID_RE = re.compile(r"/item=(\d+)(?:/|$)")


class RequiredLevelOrigin(StrEnum):
    OBSERVED = "observed"
    INFERRED_MEDIAN = "inferred_median"
    INFERRED_INTERPOLATED = "inferred_interpolated"
    MISSING = "missing"
    SOURCE_CONFIRMED_NO_REQUIREMENT = "source_confirmed_no_requirement"


@dataclass(frozen=True)
class ItemRecord:
    item_id: int
    name: str
    slot: str
    item_level: int | None = None
    required_level: int | None = None
    required_level_origin: str = RequiredLevelOrigin.OBSERVED.value
    quality: int | None = None
    armor_type: str = ""
    weapon_type: str = ""
    weapon_hands: int = 0
    weapon_min_damage: float = 0.0
    weapon_max_damage: float = 0.0
    weapon_speed: float = 0.0
    weapon_dps: float = 0.0
    armor: float = 0.0
    bonus_armor: float = 0.0
    strength: float = 0.0
    agility: float = 0.0
    stamina: float = 0.0
    intellect: float = 0.0
    spirit: float = 0.0
    attack_power: float = 0.0
    spell_power: float = 0.0
    healing: float = 0.0
    mp5: float = 0.0
    hit: float = 0.0
    crit: float = 0.0
    defense: float = 0.0
    dodge: float = 0.0
    source_type: str = ""
    source_name: str = ""
    source_url: str = ""
    identity_origin: str = "wowhead_item"
    last_verified_at: str | None = None
    fetch_status: str = "legacy_cached"
    upstream_fingerprint: str = ""
    last_fetch_error: str = ""
    extra_stats: Mapping[str, float] = field(default_factory=dict)

    @property
    def sim_required_level(self) -> int | None:
        return self.required_level

    @property
    def damage_power(self) -> float:
        return float(self.spell_power)

    def as_dict(self) -> dict:
        return self.canonical_dict()

    def canonical_dict(self) -> dict:
        out = asdict(self)
        out["extra_stats"] = dict(sorted(self.extra_stats.items()))
        return out


def extract_wowhead_item_id(url: str) -> int | None:
    match = _ITEM_ID_RE.search(str(url or ""))
    return int(match.group(1)) if match else None


def legacy_item_id(*, name: str, source_url: str = "", namespace: str = "legacy") -> int:
    """Return a stable negative ID for pre-catalogue rows without a real item ID.

    Positive IDs are reserved for upstream item IDs.  A later refresh may replace
    the negative legacy identity with a verified positive item ID without ever
    pretending the synthetic identity came from Wowhead.
    """
    payload = f"{namespace}\0{name}\0{source_url}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    return -(value or 1)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalogue_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    item_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slot TEXT NOT NULL,
    item_level INTEGER,
    required_level INTEGER,
    required_level_origin TEXT NOT NULL,
    quality INTEGER,
    armor_type TEXT NOT NULL DEFAULT '',
    weapon_type TEXT NOT NULL DEFAULT '',
    weapon_hands INTEGER NOT NULL DEFAULT 0,
    weapon_min_damage REAL NOT NULL DEFAULT 0,
    weapon_max_damage REAL NOT NULL DEFAULT 0,
    weapon_speed REAL NOT NULL DEFAULT 0,
    weapon_dps REAL NOT NULL DEFAULT 0,
    armor REAL NOT NULL DEFAULT 0,
    bonus_armor REAL NOT NULL DEFAULT 0,
    strength REAL NOT NULL DEFAULT 0,
    agility REAL NOT NULL DEFAULT 0,
    stamina REAL NOT NULL DEFAULT 0,
    intellect REAL NOT NULL DEFAULT 0,
    spirit REAL NOT NULL DEFAULT 0,
    attack_power REAL NOT NULL DEFAULT 0,
    spell_power REAL NOT NULL DEFAULT 0,
    healing REAL NOT NULL DEFAULT 0,
    mp5 REAL NOT NULL DEFAULT 0,
    hit REAL NOT NULL DEFAULT 0,
    crit REAL NOT NULL DEFAULT 0,
    defense REAL NOT NULL DEFAULT 0,
    dodge REAL NOT NULL DEFAULT 0,
    source_type TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    identity_origin TEXT NOT NULL,
    last_verified_at TEXT,
    fetch_status TEXT NOT NULL DEFAULT 'legacy_cached',
    upstream_fingerprint TEXT NOT NULL DEFAULT '',
    last_fetch_error TEXT NOT NULL DEFAULT '',
    extra_stats_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS item_class_eligibility (
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL,
    provenance TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (item_id, class_id)
);
CREATE TABLE IF NOT EXISTS item_sources (
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (item_id, source_type, source_name, source_ref)
);
CREATE TABLE IF NOT EXISTS catalogue_refresh_runs (
    refresh_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    class_id INTEGER,
    band_url TEXT NOT NULL DEFAULT '',
    rows_seen INTEGER NOT NULL DEFAULT 0,
    rows_new INTEGER NOT NULL DEFAULT 0,
    rows_changed INTEGER NOT NULL DEFAULT 0,
    rows_unchanged INTEGER NOT NULL DEFAULT 0,
    fetch_failures INTEGER NOT NULL DEFAULT 0,
    cached_fallbacks INTEGER NOT NULL DEFAULT 0,
    catalogue_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ilvl_req_level_model (
    item_level INTEGER PRIMARY KEY,
    observed_sample_count INTEGER NOT NULL,
    median_required_level REAL NOT NULL,
    p25_required_level REAL,
    p75_required_level REAL,
    model_status TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    source_catalogue_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS availability_floor_model (
    model_id INTEGER PRIMARY KEY CHECK(model_id=1),
    degree INTEGER NOT NULL,
    quadratic_a REAL NOT NULL,
    linear_b REAL NOT NULL,
    intercept_c REAL NOT NULL,
    rmse REAL NOT NULL,
    lower_sigma REAL NOT NULL,
    observed_sample_count INTEGER NOT NULL,
    retained_sample_count INTEGER NOT NULL,
    excluded_low_outliers INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    source_catalogue_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_level_slot ON items(required_level, slot);
CREATE INDEX IF NOT EXISTS idx_items_ilvl ON items(item_level);
CREATE INDEX IF NOT EXISTS idx_items_fetch_status ON items(fetch_status);
"""


_ITEM_COLUMNS = [
    "item_id", "name", "slot", "item_level", "required_level", "required_level_origin",
    "quality", "armor_type", "weapon_type", "weapon_hands", "weapon_min_damage",
    "weapon_max_damage", "weapon_speed", "weapon_dps", "armor", "bonus_armor",
    "strength", "agility", "stamina", "intellect", "spirit", "attack_power",
    "spell_power", "healing", "mp5", "hit", "crit", "defense", "dodge",
    "source_type", "source_name", "source_url", "identity_origin", "last_verified_at",
    "fetch_status", "upstream_fingerprint", "last_fetch_error", "extra_stats_json",
]


class ItemCatalogue:
    def __init__(self, path: str | Path, *, readonly: bool = False):
        self.path = Path(path)
        self.readonly = bool(readonly)
        if self.readonly:
            # Runtime scorers must be pure consumers of the pinned catalogue.
            # ``mode=ro`` prevents constructor-time schema/meta maintenance from
            # mutating the authoritative SQLite snapshot or creating WAL state.
            uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.execute("PRAGMA foreign_keys=ON")
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(items)")}
        if "last_fetch_error" not in columns:
            self._conn.execute("ALTER TABLE items ADD COLUMN last_fetch_error TEXT NOT NULL DEFAULT ''")
        self._conn.execute(
            "INSERT OR REPLACE INTO catalogue_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ItemCatalogue":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def upsert_item(self, item: ItemRecord, *, commit: bool = True) -> None:
        data = item.canonical_dict()
        data["extra_stats_json"] = json.dumps(data.pop("extra_stats"), sort_keys=True, separators=(",", ":"))
        placeholders = ",".join("?" for _ in _ITEM_COLUMNS)
        updates = ",".join(f"{c}=excluded.{c}" for c in _ITEM_COLUMNS if c != "item_id")
        self._conn.execute(
            f"INSERT INTO items ({','.join(_ITEM_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(item_id) DO UPDATE SET {updates}",
            tuple(data[c] for c in _ITEM_COLUMNS),
        )
        if item.source_type or item.source_name or item.source_url:
            self._conn.execute(
                "INSERT OR REPLACE INTO item_sources(item_id,source_type,source_name,source_ref) VALUES(?,?,?,?)",
                (item.item_id, item.source_type, item.source_name, item.source_url),
            )
        if commit:
            self._conn.commit()

    def upsert_items(self, items: Iterable[ItemRecord]) -> None:
        with self._conn:
            for item in items:
                data = item.canonical_dict()
                data["extra_stats_json"] = json.dumps(data.pop("extra_stats"), sort_keys=True, separators=(",", ":"))
                placeholders = ",".join("?" for _ in _ITEM_COLUMNS)
                updates = ",".join(f"{c}=excluded.{c}" for c in _ITEM_COLUMNS if c != "item_id")
                self._conn.execute(
                    f"INSERT INTO items ({','.join(_ITEM_COLUMNS)}) VALUES ({placeholders}) "
                    f"ON CONFLICT(item_id) DO UPDATE SET {updates}",
                    tuple(data[c] for c in _ITEM_COLUMNS),
                )
                if item.source_type or item.source_name or item.source_url:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO item_sources(item_id,source_type,source_name,source_ref) VALUES(?,?,?,?)",
                        (item.item_id, item.source_type, item.source_name, item.source_url),
                    )

    def get_item(self, item_id: int) -> ItemRecord | None:
        row = self._conn.execute("SELECT * FROM items WHERE item_id=?", (int(item_id),)).fetchone()
        return self._row_to_item(row) if row is not None else None

    def list_items(self) -> list[ItemRecord]:
        return [self._row_to_item(row) for row in self._conn.execute("SELECT * FROM items ORDER BY item_id")]

    def add_class_eligibility(self, item_id: int, class_id: int, provenance: str = "", *, commit: bool = True) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO item_class_eligibility(item_id,class_id,provenance) VALUES(?,?,?)",
            (int(item_id), int(class_id), provenance),
        )
        if commit:
            self._conn.commit()

    def availability_floor_model(self):
        from .required_level_model import AvailabilityFloorModel
        row = self._conn.execute("SELECT * FROM availability_floor_model WHERE model_id=1").fetchone()
        return AvailabilityFloorModel(**dict(row)) if row is not None else None

    def replace_availability_floor_model(self, model) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM availability_floor_model")
            self._conn.execute(
                "INSERT INTO availability_floor_model(model_id,degree,quadratic_a,linear_b,intercept_c,rmse,lower_sigma,"
                "observed_sample_count,retained_sample_count,excluded_low_outliers,computed_at,source_catalogue_hash) "
                "VALUES(1,?,?,?,?,?,?,?,?,?,?,?)",
                (int(model.degree), float(model.quadratic_a), float(model.linear_b), float(model.intercept_c),
                 float(model.rmse), float(model.lower_sigma), int(model.observed_sample_count),
                 int(model.retained_sample_count), int(model.excluded_low_outliers), str(model.computed_at),
                 str(model.source_catalogue_hash)),
            )

    def effective_required_level(self, item: ItemRecord) -> int | None:
        req = item.required_level
        model = self.availability_floor_model()
        floor = model.floor_for_item_level(item.item_level) if model is not None and item.item_level is not None else None
        if req is None:
            return floor
        if floor is None:
            return int(req)
        return max(int(req), int(floor))

    def eligible_items(self, *, class_id: int, level: int, slot: str | None = None) -> list[ItemRecord]:
        sql = (
            "SELECT i.* FROM items i JOIN item_class_eligibility e ON e.item_id=i.item_id "
            "WHERE e.class_id=? AND i.required_level IS NOT NULL AND i.required_level<=?"
        )
        args: list[object] = [int(class_id), int(level)]
        # Optional source-backed acquisition floor, distinct from equip-level.
        # An item with no equip restriction may still require a level-30 quest.
        if self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='item_acquisition_min_level'").fetchone():
            sql += " AND NOT EXISTS (SELECT 1 FROM item_acquisition_min_level a WHERE a.item_id=i.item_id AND a.min_level>?)"
            args.append(int(level))
        if slot is not None:
            sql += " AND i.slot=?"
            args.append(slot)
        sql += " ORDER BY i.required_level, i.item_level, i.item_id"
        rows = [self._row_to_item(row) for row in self._conn.execute(sql, args)]
        # Availability is conservative: both the source reqlevel and the robust
        # ilvl-derived lower bound must be satisfied. Load the model once per
        # query rather than once per item; this path is hot during level scoring.
        model = self.availability_floor_model()
        def effective(item: ItemRecord) -> int:
            req = int(item.required_level) if item.required_level is not None else 10**9
            # A client-verified item with no equip-level requirement is not
            # overridden by the ilvl-derived *inference* floor. A quest may
            # award a high-ilvl item to a lower-level character.
            if item.required_level_origin == RequiredLevelOrigin.SOURCE_CONFIRMED_NO_REQUIREMENT.value:
                return req
            if model is None or item.item_level is None:
                return req
            return max(req, model.floor_for_item_level(item.item_level))
        return [item for item in rows if effective(item) <= int(level)]



    def clear_required_level_model(self) -> None:
        self._conn.execute("DELETE FROM ilvl_req_level_model")
        self._conn.commit()

    def replace_required_level_model(self, rows: Iterable[object]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM ilvl_req_level_model")
            self._conn.executemany(
                "INSERT INTO ilvl_req_level_model("
                "item_level,observed_sample_count,median_required_level,p25_required_level,"
                "p75_required_level,model_status,computed_at,source_catalogue_hash"
                ") VALUES(?,?,?,?,?,?,?,?)",
                [
                    (
                        int(row.item_level), int(row.observed_sample_count), float(row.median_required_level),
                        row.p25_required_level, row.p75_required_level, str(row.model_status),
                        str(row.computed_at), str(row.source_catalogue_hash),
                    )
                    for row in rows
                ],
            )

    def list_required_level_model(self) -> list[object]:
        # Local import avoids a catalogue <-> model import cycle at module load time.
        from .required_level_model import RequiredLevelModelRow
        return [
            RequiredLevelModelRow(**dict(row))
            for row in self._conn.execute(
                "SELECT * FROM ilvl_req_level_model ORDER BY item_level"
            )
        ]

    def set_inferred_required_level(self, item_id: int, required_level: int, *, origin: str) -> None:
        if origin not in {
            RequiredLevelOrigin.INFERRED_MEDIAN.value,
            RequiredLevelOrigin.INFERRED_INTERPOLATED.value,
        }:
            raise ValueError(f"invalid inferred required-level origin: {origin}")
        self._conn.execute(
            "UPDATE items SET required_level=?, required_level_origin=? "
            "WHERE item_id=? AND required_level IS NULL",
            (int(required_level), origin, int(item_id)),
        )
        self._conn.commit()

    def catalogue_hash(self) -> str:
        payload = [item.canonical_dict() for item in self.list_items()]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ItemRecord:
        return ItemRecord(
            **{c: row[c] for c in _ITEM_COLUMNS if c not in {"extra_stats_json"}},
            extra_stats=json.loads(row["extra_stats_json"] or "{}"),
        )
