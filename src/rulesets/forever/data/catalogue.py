from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Iterable

from .provenance import file_sha256, stable_json_fingerprint, wowhead_id_from_url
from .schema import PARSER_VERSION, SCHEMA_VERSION, SpellRankRecord, TalentRecord


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SNAPSHOT_ID = "forever_2026_09_26"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


class SourceCatalogueError(ValueError):
    pass


@dataclass(frozen=True)
class UnresolvedEntity:
    class_key: str
    entity_kind: str
    local_key: str
    name: str
    reason: str
    details: dict[str, Any]


class ForeverSourceCatalogue:
    """Offline loader for one pinned Forever source snapshot.

    The catalogue owns identity/provenance only.  It intentionally does not
    interpret arbitrary source effects into simulator behavior (M43).
    """

    def __init__(self, snapshot_id: str = DEFAULT_SNAPSHOT_ID, fixture_root: Path | None = None):
        self.snapshot_id = str(snapshot_id)
        self.fixture_root = Path(fixture_root or FIXTURE_ROOT)
        self.path = self.fixture_root / self.snapshot_id
        if not self.path.is_dir():
            raise SourceCatalogueError(f"unknown Forever source snapshot: {self.snapshot_id}")
        self.manifest = self._read_json(self.path / "manifest.json")
        self._validate_manifest()
        self._spells: dict[str, dict[str, tuple[SpellRankRecord, ...]]] = {}
        self._talents: dict[str, dict[str, TalentRecord]] = {}
        self._unresolved: dict[str, tuple[UnresolvedEntity, ...]] = {}
        self._source_entities: dict[tuple[str, int], dict[str, Any]] = {}
        self._class_level_stats: dict[str, dict[int, dict[str, Any]]] = {}
        self._class_level_stats_meta: dict[str, Any] = {}
        self._load()
        self._validate_identity_graph()

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate_manifest(self) -> None:
        if int(self.manifest.get("schema_version", -1)) != SCHEMA_VERSION:
            raise SourceCatalogueError("source snapshot schema version mismatch")
        if str(self.manifest.get("parser_version")) != PARSER_VERSION:
            raise SourceCatalogueError("source snapshot parser version mismatch")
        if str(self.manifest.get("snapshot_id")) != self.snapshot_id:
            raise SourceCatalogueError("source snapshot id mismatch")
        expected = dict(self.manifest.get("file_sha256") or {})
        for rel, digest in expected.items():
            actual = file_sha256(self.path / rel)
            if actual != digest:
                raise SourceCatalogueError(f"source snapshot fingerprint mismatch: {rel}")

    def _load(self) -> None:
        for class_key in self.manifest.get("classes") or ():
            cpath = self.path / str(class_key)
            spell_rows = self._read_json(cpath / "spells.json")
            talent_rows = self._read_json(cpath / "talents.json")
            unresolved_rows = self._read_json(cpath / "unresolved.json")

            families: dict[str, list[SpellRankRecord]] = {}
            for raw in spell_rows:
                row = SpellRankRecord.from_dict(raw)
                if row.class_key != class_key:
                    raise SourceCatalogueError(f"spell class mismatch: {row.family_key}")
                families.setdefault(row.family_key, []).append(row)
            self._spells[class_key] = {
                key: tuple(sorted(rows, key=lambda r: ((r.required_level if r.required_level is not None else -1), r.spell_id)))
                for key, rows in families.items()
            }

            talents: dict[str, TalentRecord] = {}
            for raw in talent_rows:
                row = TalentRecord.from_dict(raw)
                if row.class_key != class_key:
                    raise SourceCatalogueError(f"talent class mismatch: {row.local_key}")
                if row.local_key in talents:
                    raise SourceCatalogueError(f"duplicate talent local key: {class_key}:{row.local_key}")
                talents[row.local_key] = row
                for alias in row.aliases:
                    if alias in talents:
                        raise SourceCatalogueError(f"duplicate talent alias: {class_key}:{alias}")
                    talents[alias] = row
            self._talents[class_key] = talents

            self._unresolved[class_key] = tuple(
                UnresolvedEntity(
                    class_key=class_key,
                    entity_kind=str(raw["entity_kind"]),
                    local_key=str(raw["local_key"]),
                    name=str(raw.get("name") or raw["local_key"]),
                    reason=str(raw["reason"]),
                    details=dict(raw.get("details") or {}),
                )
                for raw in unresolved_rows
            )

        stats_path = self.path / "shared" / "class_level_stats.json"
        if stats_path.is_file():
            payload = self._read_json(stats_path)
            self._class_level_stats_meta = {k: v for k, v in payload.items() if k != "classes"}
            for class_key, raw in (payload.get("classes") or {}).items():
                by_level: dict[int, dict[str, Any]] = {}
                for row in raw.get("rows") or ():
                    level = int(row["level"])
                    if level in by_level:
                        raise SourceCatalogueError(f"duplicate class-level stat row: {class_key}:{level}")
                    by_level[level] = dict(row)
                self._class_level_stats[str(class_key).lower()] = by_level

    def _claim(self, *, class_key: str, name: str, provider: str, entity_id: int, url: str, role: str) -> None:
        if provider != "wowhead":
            return
        url_id = wowhead_id_from_url(url)
        if url_id != entity_id:
            raise SourceCatalogueError(f"Wowhead URL/id mismatch for {class_key}:{name}: {url_id} != {entity_id}")
        key = (provider, int(entity_id))
        prior = self._source_entities.get(key)
        claim = {"class_key": class_key, "name": name, "role": role, "url": url}
        if prior is not None and (prior["class_key"], prior["name"]) != (class_key, name):
            raise SourceCatalogueError(
                f"conflicting canonical ownership for {provider}:{entity_id}: "
                f"{prior['class_key']}:{prior['name']} vs {class_key}:{name}"
            )
        self._source_entities[key] = prior or claim

    def _validate_identity_graph(self) -> None:
        for class_key, families in self._spells.items():
            for family, rows in families.items():
                levels = [r.required_level for r in rows if r.required_level is not None]
                if levels != sorted(levels) or len(levels) != len(set(levels)):
                    raise SourceCatalogueError(f"non-monotonic/duplicate rank levels: {class_key}:{family}")
                ids = [r.spell_id for r in rows]
                if len(ids) != len(set(ids)):
                    raise SourceCatalogueError(f"duplicate spell rank id within family: {class_key}:{family}")
                for row in rows:
                    self._claim(
                        class_key=class_key,
                        name=row.name,
                        provider=row.source_ref.provider,
                        entity_id=int(row.source_ref.entity_id),
                        url=row.source_ref.url,
                        role=row.entity_role,
                    )
        seen_talents: set[tuple[str, str]] = set()
        for class_key, talents in self._talents.items():
            for key, row in talents.items():
                canonical = (class_key, row.local_key)
                if canonical in seen_talents:
                    continue
                seen_talents.add(canonical)
                for ref in row.source_refs:
                    if ref.provider == "wowhead" and isinstance(ref.entity_id, int):
                        self._claim(
                            class_key=class_key,
                            name=row.name,
                            provider=ref.provider,
                            entity_id=int(ref.entity_id),
                            url=ref.url,
                            role="talent",
                        )

    def spell_family(self, class_key: str, family_key: str) -> tuple[SpellRankRecord, ...]:
        try:
            return self._spells[str(class_key).lower()][str(family_key)]
        except KeyError as exc:
            raise KeyError(f"unknown canonical spell family: {class_key}:{family_key}") from exc

    def spell_rank(self, class_key: str, family_key: str, *, level: int | None = None, spell_id: int | None = None) -> SpellRankRecord:
        rows = self.spell_family(class_key, family_key)
        if spell_id is not None:
            for row in rows:
                if row.spell_id == int(spell_id):
                    return row
            raise KeyError(f"unknown rank id {spell_id} in {class_key}:{family_key}")
        if level is None:
            if len(rows) != 1:
                raise KeyError(f"level is required for multi-rank family {class_key}:{family_key}")
            return rows[0]
        eligible = [r for r in rows if r.required_level is not None and r.required_level <= int(level)]
        if not eligible:
            raise KeyError(f"no canonical rank for {class_key}:{family_key} at level {level}")
        return eligible[-1]

    def talent(self, class_key: str, local_key: str) -> TalentRecord:
        try:
            return self._talents[str(class_key).lower()][str(local_key)]
        except KeyError as exc:
            raise KeyError(f"unknown canonical talent: {class_key}:{local_key}") from exc

    def class_level_stat(self, class_key: str, level: int) -> dict[str, Any]:
        key = str(class_key).lower()
        lvl = int(level)
        try:
            return dict(self._class_level_stats[key][lvl])
        except KeyError as exc:
            raise KeyError(f"unknown class-level stat row: {key}:{lvl}") from exc

    def class_level_stats_source(self) -> dict[str, Any]:
        return dict(self._class_level_stats_meta)

    def unresolved(self, class_key: str | None = None) -> tuple[UnresolvedEntity, ...]:
        if class_key is not None:
            return self._unresolved.get(str(class_key).lower(), ())
        return tuple(x for rows in self._unresolved.values() for x in rows)

    def source_entity(self, entity_id: int, *, provider: str = "wowhead") -> dict[str, Any]:
        try:
            return dict(self._source_entities[(provider, int(entity_id))])
        except KeyError as exc:
            raise KeyError(f"unknown canonical source entity: {provider}:{entity_id}") from exc

    def classes(self) -> tuple[str, ...]:
        return tuple(self.manifest.get("classes") or ())

    def summary(self) -> dict[str, Any]:
        talent_unique = {
            (class_key, row.local_key)
            for class_key, rows in self._talents.items()
            for row in rows.values()
        }
        return {
            "snapshot_id": self.snapshot_id,
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "classes": list(self.classes()),
            "spell_rank_records": sum(len(v) for fam in self._spells.values() for v in fam.values()),
            "spell_families": sum(len(v) for v in self._spells.values()),
            "talent_records": len(talent_unique),
            "unresolved_records": sum(len(v) for v in self._unresolved.values()),
            "class_level_stat_rows": sum(len(v) for v in self._class_level_stats.values()),
            "class_level_stats_provider": self._class_level_stats_meta.get("provider"),
            "normalized_fingerprint": self.manifest.get("normalized_fingerprint"),
        }


@lru_cache(maxsize=4)
def default_catalogue(snapshot_id: str = DEFAULT_SNAPSHOT_ID) -> ForeverSourceCatalogue:
    return ForeverSourceCatalogue(snapshot_id=snapshot_id)
