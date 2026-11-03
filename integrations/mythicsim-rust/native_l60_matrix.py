#!/usr/bin/env python3
"""Rust-only L60 28-profile diagnostic matrix (not PROCESS certification).

Uses the checkpoint registry, known pinned source requests and *only* the real
native Rust CLI for any reported score. The first breadth pass searches APL
only while gear/talent legality adapters remain unverified. This is labeled
PARTIAL_DIMENSIONS, never JOINT or P7 PASS.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from apl_mutation import mutate_apl
from native_matrix import enumerate_l60_profiles, search_native, next_budget
from native_executor import run

ROOT = Path(__file__).resolve().parents[2]
P = "fixtures/mage/prepared-v2/"
V = "validation/2026-10-06-multi-target-"
W = "validation/2026-10-05-multi-target-references/"
H = "validation/2026-10-04-hunter-preset-matrix/variants/"

# These paths have been inspected in the PINNED source tree. Each external
# fixture is a smoke candidate, NOT a saved MythicSim ranking reference.
SOURCES = {
    "druid/balance": ("gsim", "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"),
    "druid/feral_cat": ("engine", V+"paladin-druid-references/feral-druid-2-targets.request.json"),
    "druid/feral_bear": ("engine", V+"paladin-druid-references/feral-bear-druid-2-targets.request.json"),
    "druid/restoration": ("engine", "fixtures/healers/restoration-druid.request.json"),
    "mage/arcane": ("engine", P+"arcane-reference.request.json"),
    "mage/fire": ("engine", P+"fire-reference.request.json"),
    "mage/frost": ("engine", P+"frost-reference.request.json"),
    "hunter/beast_mastery": ("engine", H+"preset-bm-bm-launch.request.json"),
    "hunter/marksmanship": ("engine", H+"preset-mm-mm-launch.request.json"),
    "hunter/survival": ("engine", H+"preset-sv-sv-launch.request.json"),
    "shaman/elemental": ("engine", V+"warrior-shaman-references/elemental-shaman-2-targets.request.json"),
    "shaman/enhancement": ("engine", V+"warrior-shaman-references/enhancement-shaman-2-targets.request.json"),
    "shaman/restoration": ("engine", "fixtures/healers/restoration-shaman.request.json"),
    "warrior/arms": ("engine", V+"warrior-shaman-references/arms-warrior-2-targets.request.json"),
    "warrior/fury": ("engine", P+"fury-warrior-battlegear-of-might-sapper.request.json"),
    "warrior/protection": ("engine", V+"warrior-shaman-references/protection-warrior-2-targets.request.json"),
    "rogue/assassination": ("engine", W+"assassination-rogue-2-targets.request.json"),
    "rogue/combat": ("engine", W+"combat-rogue-2-targets.request.json"),
    "rogue/subtlety": ("engine", W+"subtlety-rogue-2-targets.request.json"),
    # The upstream HealerPriest spec exposes separate Disc and Holy presets.
    # Both rows use the pinned healer request/APL; Discipline replaces only its
    # talentsString with the source Disc preset below, never the DPS/Smite request.
    "priest/discipline": ("engine", "fixtures/healers/holy-priest.request.json"),
    "priest/holy": ("engine", "fixtures/healers/holy-priest.request.json"),
    "priest/shadow": ("engine", W+"shadow-priest-2-targets.request.json"),
    "warlock/affliction": ("engine", "validation/2026-10-06-mage-warlock-multi-target-references/affliction-warlock-2-targets.request.json"),
    "warlock/demonology": ("engine", "validation/2026-10-06-mage-warlock-multi-target-references/demonology-warlock-2-targets.request.json"),
    "warlock/destruction": ("engine", "validation/2026-10-06-mage-warlock-multi-target-references/destruction-warlock-2-targets.request.json"),
    "paladin/holy": ("engine", P+"holy-paladin-healing.request.json"),
    "paladin/protection": ("engine", V+"paladin-druid-references/protection-paladin-2-targets.request.json"),
    "paladin/retribution": ("engine", V+"paladin-druid-references/retribution-paladin-2-targets.request.json"),
}

# The 2026-10-06 engine smoke fixtures predate the current 1.60.1.70707
# talent-tree reshuffle. Keep their gear/encounter/APL, replacing only the
# talent string with a pinned upstream UI preset or native test build. These
# remain composed smoke fixtures, never saved ranking references.
CURRENT_CLIENT_BUILD = "1.60.1.70707"
CURRENT_ENGINE_PIN = "deb366e986dbc156e2242ddac3ac8c4ac854c107"
CURRENT_CLIENT_TALENT_OVERRIDES = {
    "druid/feral_cat": {
        "class_name": "ClassDruid",
        "talents_string": "050022-35200032123010125011-055",
        "preset_name": "Cat",
        "upstream_pr": 769,
        "source_commit": "43df34d7fb8145fab89199654cc49aba72f04f02",
        "source_path": "ui/specs/druid/feralcat/presets.ts",
        "source_blob_sha": "e69b4d64406b0a184f56971f3dd1c0fc34f80ee2",
    },
    "mage/arcane": {
        "class_name": "ClassMage",
        "talents_string": "050205223101311531-5500003-003",
        "preset_name": "Arcane",
        "upstream_pr": 769,
        "source_commit": "43df34d7fb8145fab89199654cc49aba72f04f02",
        "source_path": "ui/specs/mage/dps/presets.ts",
        "source_blob_sha": "ef20bfef2ab4dff32b6e387c946c016f5878f183",
    },
    "mage/fire": {
        "class_name": "ClassMage",
        "talents_string": "0502052001001-55500001230133031-003",
        "preset_name": "Fire",
        "upstream_pr": 769,
        "source_commit": "43df34d7fb8145fab89199654cc49aba72f04f02",
        "source_path": "ui/specs/mage/dps/presets.ts",
        "source_blob_sha": "ef20bfef2ab4dff32b6e387c946c016f5878f183",
    },
    "mage/frost": {
        "class_name": "ClassMage",
        "talents_string": "0502052011003--053500021100331251",
        "preset_name": "Frost",
        "upstream_pr": 769,
        "source_commit": "43df34d7fb8145fab89199654cc49aba72f04f02",
        "source_path": "ui/specs/mage/dps/presets.ts",
        "source_blob_sha": "ef20bfef2ab4dff32b6e387c946c016f5878f183",
    },
    "druid/feral_bear": {
        "class_name": "ClassDruid",
        "talents_string": "050022-2322030212310212501-055",
        "preset_name": "Bear",
        "upstream_pr": 774,
        "source_commit": "c96ec787be9529a934d19a1d9b8156524a176b5e",
        "source_path": "ui/specs/druid/feralbear/presets.ts",
        "source_blob_sha": "51e09cf57affbdced3a23cce0629ebaab836f8c6",
    },
    "paladin/holy": {
        "class_name": "ClassPaladin",
        "talents_string": "55320015022101251-503020005001",
        "preset_name": "StandardTalents (sim test)",
        "upstream_pr": 772,
        "source_commit": "d608072a6db0197d58a073df7e3153c90f20f46c",
        "source_path": "sim/paladin/holy/holy_test.go",
        "source_blob_sha": "bff116c8fe0727c96b51d51c97d637c4f189ba5c",
        "source_type": "PINNED_UPSTREAM_NATIVE_TEST_TALENT_FIXTURE",
        "scope": "TALENT_STRING_ONLY; upstream simulator StandardTalents test build; original smoke-fixture gear, encounter and APL retained",
    },
    "paladin/protection": {
        "class_name": "ClassPaladin",
        "talents_string": "050050002-05302102213301531-502",
        "preset_name": "Default",
        "upstream_pr": 772,
        "source_commit": "d608072a6db0197d58a073df7e3153c90f20f46c",
        "source_path": "ui/specs/paladin/protection/presets.ts",
        "source_blob_sha": "a59c83c7581d2aafb19f3265bfd10298722782bf",
    },
    "priest/discipline": {
        "class_name": "ClassPriest",
        "talents_string": "005025021330011531-335001030301",
        "preset_name": "Disc",
        "upstream_pr": None,
        "source_commit": "a0ab835726319b558318cce186c88c4bd3a855dd",
        "source_path": "ui/specs/priest/healer/presets.ts",
        "source_blob_sha": "87fe551e2150ead167dbb5c2418f332bed02549c",
        "scope": "TALENT_STRING_ONLY; upstream HealerPriest Disc preset applied to the pinned healer request; healerPriest oneof, gear, encounter and APL retained",
    },
    "paladin/retribution": {
        "class_name": "ClassPaladin",
        "talents_string": "050250002-501-05233011201301351",
        "preset_name": "Unsealed Wrath",
        "upstream_pr": 772,
        "source_commit": "d608072a6db0197d58a073df7e3153c90f20f46c",
        "source_path": "ui/specs/paladin/retribution/presets.ts",
        "source_blob_sha": "5b592addceab39c25d8a8d1af89b22c8df88b032",
    },
}


MAGE_ALTERNATE_CURRENT_CLIENT_TALENT_PRESETS = (
    {
        "preset_name": "Arcane Fire",
        "talents_string": "050205203100311531-525000012001-003",
    },
    {
        "preset_name": "FFB",
        "talents_string": "-5550000123011303-203501031",
    },
)
CURRENT_CLIENT_TALENT_DONOR_PRESETS = {
    "druid/feral_cat": (
        {
            "preset_name": "Hybrid",
            "talents_string": "050022-50220332123112125011-05",
        },
    ),
    "mage/arcane": MAGE_ALTERNATE_CURRENT_CLIENT_TALENT_PRESETS,
    "mage/fire": MAGE_ALTERNATE_CURRENT_CLIENT_TALENT_PRESETS,
    "mage/frost": MAGE_ALTERNATE_CURRENT_CLIENT_TALENT_PRESETS,
}

CURRENT_CLIENT_TALENT_DONOR_SOURCE_OVERRIDES = {
    "fixtures/mage/prepared-v2/holy-paladin-blessing-of-light-oom.request.json": {
        "profile_id": "paladin/holy",
        "original_talents_string": "05321013025131251-503210302",
    },
    "fixtures/mage/prepared-v2/holy-paladin-fused-bonus-healing.request.json": {
        "profile_id": "paladin/holy",
        "original_talents_string": "01021011005121251-503000301",
    },
    "fixtures/mage/prepared-v2/holy-paladin-healing.request.json": {
        "profile_id": "paladin/holy",
        "original_talents_string": "25320213225131051-50323",
    },
}

HEAL = {"druid/restoration", "shaman/restoration", "priest/discipline", "priest/holy", "paladin/holy"}
TANK = {"druid/feral_bear", "warrior/protection", "paladin/protection"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def player(request):
    return request["raid"]["parties"][0]["players"][0]


def apl_only_candidate_scope(reference: dict, candidate: dict) -> bool:
    """Limit this diagnostic to APL changes, not Warcraft action legality.

    Only the rotation priority list may change. Native MythicSim validates
    spell IDs, cast actions and other game semantics on the submitted request.
    """
    try:
        original = player(reference)["rotation"]["priorityList"]
        actions = player(candidate)["rotation"]["priorityList"]
        if not isinstance(original, list) or not original or not isinstance(actions, list) or not actions:
            return False
        masked = copy.deepcopy(candidate)
        player(masked)["rotation"]["priorityList"] = copy.deepcopy(original)
        return masked == reference
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False


def entry(profile, source_kind, source):
    kind = "PINNED_RANKING_REFERENCE" if source_kind == "gsim" else "SMOKE_FIXTURE_ONLY"
    return {
        "profile_id": profile,
        "source_type": kind,
        "source_path": source,
        "source_sha256": None,
        "status": "BLOCKED_REFERENCE_MISSING",
        "dimensions_searched": [],
        "dimensions_blocked": ["gear", "talents"],
        "native_paid": 0,
        "baseline": None,
        "best": None,
        "delta": None,
        "objective": "HPS" if profile in HEAL else ("TPS" if profile in TANK else "DPS"),
        "blocker": "Source file not loaded",
    }



def load_native_item_index(engine_src: Path) -> dict[int, dict]:
    """Index pinned Rust items.jsonl, never an older gsim/Wowhead catalogue.

    These are native item identities, NOT a proof of class equip legality.
    Scaling options and effects remain owned by the Rust engine.
    """
    path = engine_src / "data/items.jsonl"
    items: dict[int, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid native item JSON") from exc
            item_id = item.get("id")
            if not isinstance(item_id, int) or item_id <= 0:
                raise ValueError(f"{path}:{line_number}: invalid native item ID {item_id!r}")
            if item_id in items:
                raise ValueError(f"{path}:{line_number}: duplicate native item ID {item_id}")
            items[item_id] = {
                key: item.get(key)
                for key in ("name", "type", "armor_type", "weapon_type", "hand_type",
                            "ranged_weapon_type", "class_allowlist", "required_level",
                            "unique", "limit_category", "required_profession", "phase")
            }
    if not items:
        raise ValueError(f"Native item catalogue empty: {path}")
    return items


def describe_native_gear(equipment: dict, item_index: dict[int, dict]) -> tuple[list[dict], list[int]]:
    """Audit source gear against native item identities, without inventing rules."""
    details: list[dict] = []
    missing: set[int] = set()
    for slot_index, entry in enumerate(equipment.get("items", [])):
        item_id = entry.get("id", 0)
        if not isinstance(item_id, int) or item_id < 0:
            raise ValueError(f"Invalid fixture item ID at slot index {slot_index}: {item_id!r}")
        if item_id == 0:
            continue  # Native equipment permits empty positions.
        record = {"source_slot_index": slot_index, "id": item_id,
                  "native_db_present": item_id in item_index}
        if item_id in item_index:
            record.update(item_index[item_id])
        else:
            missing.add(item_id)
        details.append(record)
    return details, sorted(missing)



def apply_current_client_talent_override(profile: str, request: dict):
    """Compose a smoke request with an exact upstream current-client talent preset.

    Only talentsString changes. The original source fixture remains the source
    for gear, encounter and APL, so this is not a ranking reference.
    """
    override = CURRENT_CLIENT_TALENT_OVERRIDES.get(profile)
    if override is None:
        return request, None

    effective = copy.deepcopy(request)
    target = player(effective)
    if target.get("class") != override["class_name"]:
        raise ValueError(
            f"{profile}: current-client talent preset class mismatch: "
            f"{target.get('class')!r} != {override['class_name']!r}"
        )
    original = target.get("talentsString")
    if not isinstance(original, str) or not original:
        raise ValueError(f"{profile}: missing legacy source talentsString")
    replacement = override["talents_string"]
    if not isinstance(replacement, str) or not replacement:
        raise ValueError(f"{profile}: missing upstream current-client talent preset")
    if replacement == original:
        raise ValueError(f"{profile}: current-client preset unexpectedly equals legacy string")

    target["talentsString"] = replacement
    source_path = override["source_path"]
    source_commit = override["source_commit"]
    metadata = {
        "status": "APPLIED",
        "source_type": override.get(
            "source_type", "PINNED_UPSTREAM_CURRENT_CLIENT_TALENT_PRESET"
        ),
        "scope": override.get(
            "scope",
            "TALENT_PRESET_ONLY; original smoke-fixture gear, encounter and APL retained",
        ),
        "client_build": CURRENT_CLIENT_BUILD,
        "engine_pin": CURRENT_ENGINE_PIN,
        "source_repo": "wowsims/forever",
        "source_pull_request": override.get("upstream_pr"),
        "source_commit": source_commit,
        "source_path": source_path,
        "source_blob_sha": override["source_blob_sha"],
        "source_url": f"https://github.com/wowsims/forever/blob/{source_commit}/{source_path}",
        "preset_name": override["preset_name"],
        "original_talents_string": original,
        "replacement_talents_string": replacement,
    }
    return effective, metadata



def current_client_talent_donor_fixtures(inventory):
    """Compose alternate pinned upstream talent presets as native-only proposals.

    The original profile request supplies gear, encounter and APL. Only the
    talent string changes. This records source provenance; it does not assert
    that MythicSim accepts any proposed talent build.
    """
    requests = {
        row["profile_id"]: request
        for row, request in inventory
        if request is not None
    }
    donors = []
    for profile, presets in CURRENT_CLIENT_TALENT_DONOR_PRESETS.items():
        reference = requests.get(profile)
        if reference is None:
            continue
        source = CURRENT_CLIENT_TALENT_OVERRIDES[profile]
        base_player = player(reference)
        if base_player.get("class") != source["class_name"]:
            raise ValueError(f"{profile}: current-client donor class mismatch")
        if base_player.get("talentsString") != source["talents_string"]:
            raise ValueError(f"{profile}: current-client donor baseline preset mismatch")
        for preset in presets:
            replacement = preset["talents_string"]
            if not isinstance(replacement, str) or not replacement:
                raise ValueError(f"{profile}: missing pinned alternate talent preset")
            if replacement == base_player.get("talentsString"):
                continue
            composed = copy.deepcopy(reference)
            player(composed)["talentsString"] = replacement
            source_path = (
                f"upstream/wowsims/forever@{source['source_commit']}/"
                f"{source['source_path']}#{preset['preset_name']};"
                f"composed-over={profile}"
            )
            donors.append({
                "source_path": source_path,
                "source_sha256": fingerprint(composed),
                "class_name": source["class_name"],
                "item_count": len(player(composed)["equipment"]["items"]),
                "request": composed,
                "source_type": "PINNED_UPSTREAM_CURRENT_CLIENT_TALENT_PRESET_DONOR",
                "talent_source_repository": "wowsims/forever",
                "talent_source_pull_request": source["upstream_pr"],
                "talent_source_commit": source["source_commit"],
                "talent_source_path": source["source_path"],
                "talent_source_blob_sha": source["source_blob_sha"],
                "talent_source_url": (
                    f"https://github.com/wowsims/forever/blob/"
                    f"{source['source_commit']}/{source['source_path']}"
                ),
                "talent_preset_name": preset["preset_name"],
                "talent_string": replacement,
                "composed_over_profile": profile,
                "client_build": CURRENT_CLIENT_BUILD,
                "engine_pin": CURRENT_ENGINE_PIN,
            })
    return donors



def apply_current_client_talent_donor_source_overrides(fixtures: list[dict]) -> list[dict]:
    """Compose stale pinned donor fixtures with the exact current-client talent preset.

    Only talentsString changes. Source fixture gear, encounter and APL remain
    untouched; the original fixture hash and exact upstream preset provenance
    are retained in each composed donor record.
    """
    composed_fixtures = []
    for fixture in fixtures:
        spec = CURRENT_CLIENT_TALENT_DONOR_SOURCE_OVERRIDES.get(
            fixture.get("source_path")
        )
        if spec is None:
            composed_fixtures.append(fixture)
            continue

        request = fixture.get("request")
        if not isinstance(request, dict):
            raise ValueError(
                f"{fixture.get('source_path')}: donor source request is missing"
            )
        original = player(request).get("talentsString")
        if original != spec["original_talents_string"]:
            raise ValueError(
                f"{fixture['source_path']}: pinned source donor talent string "
                f"mismatch: {original!r} != {spec['original_talents_string']!r}"
            )

        profile = spec["profile_id"]
        effective, metadata = apply_current_client_talent_override(profile, request)
        if metadata is None or metadata.get("status") != "APPLIED":
            raise ValueError(
                f"{fixture['source_path']}: current-client donor preset was not applied"
            )

        composed = copy.deepcopy(fixture)
        composed["request"] = effective
        composed["source_type"] = "COMPOSED_SMOKE_FIXTURE_CURRENT_CLIENT_TALENT_PRESET"
        composed["talent_source_repository"] = metadata["source_repo"]
        composed["talent_source_pull_request"] = metadata["source_pull_request"]
        composed["talent_source_commit"] = metadata["source_commit"]
        composed["talent_source_path"] = metadata["source_path"]
        composed["talent_source_blob_sha"] = metadata["source_blob_sha"]
        composed["talent_source_url"] = metadata["source_url"]
        composed["talent_preset_name"] = metadata["preset_name"]
        composed["composed_over_profile"] = profile
        composed["original_talents_string"] = metadata["original_talents_string"]
        composed["replacement_talents_string"] = metadata["replacement_talents_string"]
        composed_fixtures.append(composed)

    return composed_fixtures

def create_inventory(registry_path, engine_src):
    # Do not parse items.jsonl or preflight item identities here. Source
    # equipment requests go to MythicSim; Rust owns identity and equip outcomes.
    if CURRENT_CLIENT_TALENT_OVERRIDES:
        try:
            engine_pin = subprocess.check_output(
                ["git", "-C", str(engine_src), "rev-parse", "HEAD"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError(
                "Cannot verify the selected Rust pin required by current-client talent presets"
            ) from exc
        if engine_pin != CURRENT_ENGINE_PIN:
            raise ValueError(
                "Current-client talent presets require Rust pin "
                f"{CURRENT_ENGINE_PIN}; selected engine is {engine_pin}"
            )
    registry = json.loads(registry_path.read_text())
    profiles = enumerate_l60_profiles(registry)
    if len(profiles) != 28 or len({cl for cl, _ in profiles}) != 9:
        raise ValueError("Invalid canonical fixed L60 registry (expected 28 / nine classes)")
    if set(SOURCES) != {cl+"/"+sp for cl, sp in profiles}:
        raise ValueError("Source map must cover every canonical profile once")
    rows = []
    for cl, sp in profiles:
        profile = cl+"/"+sp
        kind, relative = SOURCES[profile]
        path = (ROOT if kind == "gsim" else engine_src)/relative
        row = entry(profile,kind,relative)
        if not path.is_file():
            row["blocker"] = "NO_NATIVE_REQUEST: source does not exist: "+str(path)
            rows.append((row, None))
            continue
        try:
            request = json.loads(path.read_text())
            pl = player(request)
            if pl["class"] != "Class"+cl.capitalize():
                raise ValueError("Class identity mismatch: "+str(pl["class"]))
            if not pl.get("equipment",{}).get("items"):
                raise ValueError("Empty source equipment")
            if not pl.get("talentsString"):
                raise ValueError("Missing source talents")
            if not request.get("simOptions"):
                raise ValueError("Missing native simOptions")
            row["source_sha256"] = digest(path)
            row["source_fixture_sha256"] = row["source_sha256"]
            request, talent_override = apply_current_client_talent_override(profile, request)
            if talent_override is not None:
                row["source_type"] = "COMPOSED_SMOKE_FIXTURE_CURRENT_CLIENT_TALENT_PRESET"
                row["talent_override"] = talent_override
            row["effective_source_request_fingerprint"] = fingerprint(request)
            pl = player(request)
            row["item_count"] = len(pl["equipment"]["items"])
            row["native_oneofs"] = [k for k in pl if k.lower().endswith(("druid","warrior","mage","priest","shaman","hunter","rogue","warlock","paladin")) and k != "class"]
            row["status"] = "REFERENCE_READY" if kind == "gsim" else "SMOKE_FIXTURE_ONLY"
            row["blocker"] = None
            rows.append((row,request))
        except Exception as exc:
            row["status"] = "BLOCKED_REQUEST_PARSE"
            row["blocker"] = "REQUEST_PARSE: "+str(exc)
            rows.append((row,None))
    return rows


def execute_row(row, reference, *, binary, budget, iterations, seed, outdir):
    profile = row["profile_id"]
    if reference is None:
        return row
    if profile in HEAL or profile in TANK:
        row["status"] = "BLOCKED_OBJECTIVE"
        row["blocker"] = ("HPS" if profile in HEAL else "TPS")+" extractor/comparable native fixture not yet verified"
        return row
    actions = player(reference).get("rotation",{}).get("priorityList")
    if not isinstance(actions,list) or not actions:
        row["status"] = "BLOCKED_APL"
        row["blocker"] = "No nonempty source APL priorityList"
        return row
    safe_name = profile.replace("/","__")
    rowdir = outdir/"profiles"/safe_name
    rowdir.mkdir(parents=True,exist_ok=True)
    (rowdir/"source_request.json").write_text(json.dumps(reference,indent=2))
    base_seed = int(reference["simOptions"].get("randomSeed","42"))
    baseline_deadline = time.monotonic()+30
    try:
        baseline, _, latency, _ = run(binary,reference,iterations,base_seed,"stochastic",baseline_deadline)
        if not math.isfinite(baseline):
            raise ValueError("Non-finite native baseline")
        row["baseline"] = baseline
        row["baseline_duration_s"] = latency
    except Exception as exc:
        row["status"] = "BLOCKED_NATIVE_BASELINE"
        row["blocker"] = ("RUST_UNSUPPORTED_REQUEST: "+str(exc))[:700]
        return row

    errors = []
    failure_repros = []
    deadline = time.monotonic()+budget

    def propose(rng):
        req = copy.deepcopy(reference)
        player(req)["rotation"]["priorityList"] = mutate_apl(None,actions,rng,cold=True)
        return req

    def mutate(req,rng):
        out = copy.deepcopy(req)
        player(out)["rotation"]["priorityList"] = mutate_apl(
            player(out)["rotation"]["priorityList"],actions,rng
        )
        return out

    def legal(req):
        return apl_only_candidate_scope(reference, req)

    def evaluate(req, *, iterations, seed, rng_mode):
        try:
            metric,_,_,_ = run(binary,req,iterations,seed,rng_mode,deadline)
            return metric
        except (TimeoutError, subprocess.TimeoutExpired):
            raise  # ordinary strict-budget expiry; not a native engine failure
        except Exception as exc:
            errors.append(str(exc)[:900])
            # Preserve the exact native request that triggered a failure.
            # Without it a Rust panic cannot become a minimal regression.
            # Bound artifact growth for repeated stochastic failures.
            if len(failure_repros) < 3:
                path = rowdir / f"native_failure_{len(failure_repros):03}.request.json"
                path.write_text(json.dumps(req, indent=2))
                failure_repros.append({
                    "request_path": str(path.relative_to(outdir)),
                    "request_sha256": digest(path),
                    "error": str(exc)[:900],
                })
            raise

    result = search_native(
        profile_id=profile,reference=reference,propose=propose,mutate=mutate,
        legal=legal,evaluate=evaluate,seconds=budget,
        iterations=iterations,seed=seed,clock=time.monotonic
    )
    row["native_paid"] = result["paid_candidates"]
    row["engine_errors"] = result["engine_errors"]
    row["native_failure_repros"] = failure_repros
    row["rejected_legal"] = result["legal_rejections"]
    row["elapsed_search_s"] = result["elapsed_s"]
    row["best"] = result["best_score"]
    # Never compare a stochastic baseline directly with balanced-RNG search.
    # A stochastic rerank/holdout is a separate follow-on stage.
    row["delta"] = None
    row["baseline_rng_mode"] = "stochastic"
    row["search_rng_mode"] = "balanced"
    row["metric_comparison"] = "NOT_COMPARABLE_DIFFERENT_RNG_MODE"
    row["dimensions_searched"] = ["apl"]
    row["dimensions_blocked"] = ["gear","talents"]
    row["native_status"] = result["status"]
    row["stochastic_holdout"] = "NOT_RUN"
    row["promotable"] = False  # not certified JOINT; C gear/talent adapters still absent
    row["status"] = ("PARTIAL_DIMENSIONS" if result["status"] == "RAN" else result["status"])
    row["blocker"] = (
        "PARTIAL_DIMENSIONS: item legality/pools and class talent tree missing; APL_ONLY"
        if result["status"] == "RAN" else
        (errors[0] if errors else result["status"])
    )
    (rowdir/"result.json").write_text(json.dumps(row,indent=2))
    (rowdir/"native_errors.json").write_text(json.dumps(errors,indent=2))
    if result["best_candidate"] is not None:
        (rowdir/"best_request.json").write_text(json.dumps(result["best_candidate"],indent=2))
        row["best_request_sha256"] = digest(rowdir/"best_request.json")
    return row


def report(rows,outdir,*,binary,engine_src,budget,inventory_only):
    matrix = {
        "scope": "RUST_NATIVE_L60_DIAGNOSTIC_NOT_PROCESS_P7_PASS",
        "requested_search": "JOINT",
        "actual_search": "APL_ONLY where runnable; no gear/talent adapter yet",
        "budget_per_profile_s": budget,
        "inventory_only": inventory_only,
        "native_binary_sha256": digest(binary) if binary and binary.is_file() else None,
        "engine_items_sha256": digest(engine_src/"data/items.jsonl") if (engine_src/"data/items.jsonl").is_file() else None,
        "engine_enchants_sha256": digest(engine_src/"data/enchants.jsonl") if (engine_src/"data/enchants.jsonl").is_file() else None,
        "engine_spells_sha256": digest(engine_src/"data/spells.jsonl") if (engine_src/"data/spells.jsonl").is_file() else None,
        "rows": rows,
    }
    outdir.mkdir(parents=True,exist_ok=True)
    (outdir/"matrix.json").write_text(json.dumps(matrix,indent=2))
    columns = ["class/spec","source","searched","paid","baseline","best","delta","status/blocker"]
    lines=["# Native Rust L60 diagnostic matrix","",
           "**Not a JOINT/P7 PASS:** available profiles have APL-only native screening until source-legal class talent and Rust item adapters exist.","",
           "| "+" | ".join(columns)+" |","|"+"|".join(["---"]*len(columns))+"|"]
    for x in rows:
        def val(v):
            return "%.3f"%v if isinstance(v,float) else str(v if v is not None else "-")
        lines.append("| "+" | ".join([
            x["profile_id"],x["source_type"],",".join(x["dimensions_searched"]) or "-",
            str(x["native_paid"]),val(x["baseline"]),val(x["best"]),val(x["delta"]),
            x["status"]+": "+str(x.get("blocker") or "-").replace("|","/")[:95]
        ])+" |")
    counts=Counter(x["status"] for x in rows)
    lines.extend(["","Status counts: "+str(dict(counts)),"",
                  "This report includes every checkpoint L60 fixed profile, including BLOCKED rows."])
    (outdir/"matrix.md").write_text("\n".join(lines)+"\n")
    gaps = []
    for x in rows:
        if x.get("blocker"):
            gaps.append({"profile_id":x["profile_id"],"category":x["status"],
                         "reason":x["blocker"],"source":x["source_path"]})
    (outdir/"gaps.json").write_text(json.dumps(gaps,indent=2))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--engine-src",type=Path,required=True)
    ap.add_argument("--binary",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--budget",type=float,default=5.0)
    ap.add_argument("--screen-iterations",type=int,default=10)
    ap.add_argument("--seed",type=int,default=678)
    ap.add_argument("--only",action="append",help="Filter 'class/spec' (can repeat)")
    ap.add_argument("--inventory-only",action="store_true")
    args=ap.parse_args()
    if not args.inventory_only and (args.binary is None or not args.binary.is_file()):
        ap.error("--binary must be a real runnable native executable")
    records=create_inventory(ROOT/"config/validation/checkpoint_148.json",args.engine_src)
    rows=[]
    for idx,(row,request) in enumerate(records):
        if not args.inventory_only and (not args.only or row["profile_id"] in args.only):
            if request is not None:
                row=execute_row(row,request,binary=args.binary,budget=args.budget,
                                iterations=args.screen_iterations,seed=args.seed+idx,
                                outdir=args.out)
        elif args.only and row["profile_id"] not in args.only:
            row["status"]="SKIPPED_FILTER"
            row["blocker"]="Not selected in filtered smoke invocation"
        rows.append(row)
    report(rows,args.out,binary=args.binary,engine_src=args.engine_src,
           budget=args.budget,inventory_only=args.inventory_only)
    assert len(rows)==28 and len({r["profile_id"] for r in rows})==28
    print(json.dumps({"rows":len(rows),"status_counts":dict(Counter(x["status"] for x in rows)),
                      "actual_search":"APL_ONLY; no JOINT claim"},indent=2))


if __name__=="__main__":
    main()
