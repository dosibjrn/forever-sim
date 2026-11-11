#!/usr/bin/env python3
"""Score several Rust-prepared Warlock candidates with charged final recovery.

Forever owns request/result forwarding and ranking, not Warcraft rules. Existing
native engines only report between-kill recovery; those receipts cannot be
silently promoted to a full HP+mana terminally-recovered optimization score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Callable, Mapping


def _positive(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _nonnegative(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Only source files that define the paid native/world execution contract
# belong to the cache revision identity. Workflow, test, docs and unrelated
# optimizer edits must not repay an otherwise identical native observation.
_PAID_RUNTIME_GIT_PATHS = (
    "src/game",
    "src/scenarios",
    "integrations/mythicsim-rust/live_two_world_pulls.py",
    "tools/wf_warlock_native_candidate_scoring.py",
    "tools/wf_warlock_native_persistent_optimizer.py",
)


def _exact_paid_cache_identity(binary: Path, *, actor_level: int,
                               mob_count: int, target_hp: float) -> dict | None:
    """Fingerprint the clean paid runtime rather than an unrelated Git HEAD.

    Native receipts are keyed again by Rust-prepared request/content hashes,
    exact scenario and native binary, and verified through score_native_chain
    and the raw receipt digest before reuse. Runtime source changes do invalidate
    this schema-2 identity. Historical schema-1 receipts remain immutable and
    are deliberately not silently promoted across an unverifiable source diff.
    """
    if not binary.is_file():
        return None
    root = Path(__file__).resolve().parents[1]
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
            capture_output=True, text=True, check=True, timeout=10)
        objects = subprocess.run(
            ["git", "rev-parse", *(f"HEAD:{path}" for path in _PAID_RUNTIME_GIT_PATHS)],
            cwd=root, capture_output=True, text=True, check=True, timeout=10)
        shas = objects.stdout.splitlines()
        if (dirty.stdout.strip() or len(shas) != len(_PAID_RUNTIME_GIT_PATHS)
                or any(len(sha) != 40 or any(ch not in "0123456789abcdef"
                                              for ch in sha) for sha in shas)):
            return None
        fingerprint = hashlib.sha256(("\n".join(shas)).encode()).hexdigest()
        return {
            "cache_schema": 2,
            "forever_paid_runtime_sha256": fingerprint,
            "native_binary_sha256": _sha256(binary),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced",
            "iterations": 1, "recovery_policy": "decisions",
            "health_threshold": 1.0, "mana_threshold": 1.0,
            "require_native_health_damage": False,
        }
    except (OSError, subprocess.SubprocessError):
        return None



# A historical schema-1 receipt used the entire Forever commit as its key.
# Reuse it after a cache-identity-only code change only when the actual
# world/scenario/gsim sources still have identical Git objects. Prepared
# payload + engine + paid scenario + raw receipt are checked separately.
_LEGACY_PAID_WORLD_PATHS = (
    "src/game",
    "src/scenarios",
    "src/shared",
    "integrations/mythicsim-rust",
)


def _verified_legacy_paid_cache(metadata: dict, identity: dict) -> bool:
    """Admit a historical exact receipt without equating unrelated revisions.

    This function only matches provenance: callers must also verify the
    original receipt SHA256 and re-score it with the CURRENT strict native
    two-mob ACK and dual-resource terminal-recovery predicate.
    """
    if (metadata.get("cache_schema") != 1
            or identity.get("cache_schema") != 2):
        return False
    old_commit = metadata.get("forever_commit")
    if (not isinstance(old_commit, str) or len(old_commit) != 40
            or any(char not in "0123456789abcdef" for char in old_commit)):
        return False
    # Compare *every* scenario, native binary and prepared-actor field.
    # Only the cache schema and historical commit key may be different.
    if any(metadata.get(key) != value for key, value in identity.items()
           if key not in ("cache_schema", "forever_paid_runtime_sha256")):
        return False
    if not isinstance(metadata.get("native_raw_receipt_sha256"), str):
        return False
    root = Path(__file__).resolve().parents[1]
    try:
        def objects(revision: str) -> list[str]:
            result = subprocess.run(
                ["git", "rev-parse",
                 *(f"{revision}:{path}" for path in _LEGACY_PAID_WORLD_PATHS)],
                cwd=root, capture_output=True, text=True, check=True, timeout=10)
            values = result.stdout.splitlines()
            if (len(values) != len(_LEGACY_PAID_WORLD_PATHS)
                    or any(len(value) != 40 for value in values)):
                return []
            return values
        previous = objects(old_commit)
        return bool(previous) and previous == objects("HEAD")
    except (OSError, subprocess.SubprocessError):
        return False


def score_native_chain(receipt: dict, prepared: dict, *, mob_count: int,
                       expected_target_hp: float) -> tuple[float | None, str]:
    """Total source-ACK-clock elapsed time, or a precise unranked reason.

    A future source-native terminal_recovery receipt must belong to the same
    last-kill ACK clock, have real elapsed time and show both resources full.
    No external recovery timer, resource reset, or guessed Warcraft effect.
    """
    if (type(mob_count) is not int or not 2 <= mob_count <= 100
            or not _positive(expected_target_hp)):
        raise ValueError("INVALID_NATIVE_SCORING_SCENARIO")
    source = prepared.get("request_sha256")
    player = prepared.get("player")
    stats = player.get("stats", {}) if isinstance(player, dict) else {}
    if (not isinstance(source, str) or len(source) != 64
            or not _positive(stats.get("Health"))
            or not _positive(stats.get("Mana"))):
        return None, "INVALID_NATIVE_PREPARED_IDENTITY_OR_CAPACITY"
    windows = receipt.get("native_windows")
    mana = receipt.get("native_actor_mana_after_world_kills")
    if (receipt.get("source_sha256") != source
            or receipt.get("world_target_hp") != expected_target_hp
            or receipt.get("world_targets_killed") != mob_count
            or receipt.get("continuous_native_actor") is not True
            or receipt.get("actual_2d_ack") is not True
            or receipt.get("native_recovery_clock_accounted") is not True
            or receipt.get("native_recovery_mode") != "decisions_food_water"
            # Decisions may legitimately request no between-pull refill.
            # The gsim/native bridge has separately checked each native gap
            # and whether its clock is accounted for. A False *needed-rest*
            # flag is not an instant free resource refill.
            or type(receipt.get("paid_recovery")) is not bool
            or not isinstance(windows, list) or len(windows) != mob_count
            or not isinstance(mana, list) or len(mana) != mob_count):
        return None, "INCOMPLETE_NATIVE_WORLD_OR_BETWEEN_KILL_RECEIPT"
    # Original native incoming-damage telemetry must be present and internally
    # consistent, but taking damage is NOT a performance requirement: a valid
    # hostile run can avoid all player damage through pet tanking or control.
    # Never turn a missing port into an observed zero-damage receipt.
    incoming = receipt.get("native_health_damage")
    if (not isinstance(incoming, dict)
            or incoming.get("observed") is not True
            or not _nonnegative(incoming.get("damage_taken"))
            or type(incoming.get("damage_events")) is not int
            or incoming["damage_events"] < 0
            or (incoming["damage_taken"] > 0
                and incoming["damage_events"] == 0)):
        return None, "NATIVE_HEALTH_DAMAGE_RECEIPT_MISSING_OR_INVALID"
    last_clock = 0
    for index, (window, value) in enumerate(zip(windows, mana)):
        if (not isinstance(window, dict) or window.get("index") != index
                or type(window.get("native_kill_ns")) is not int
                or window["native_kill_ns"] <= last_clock
                or not _positive(window.get("actor_health"))
                or not _nonnegative(value)):
            return None, "INCOMPLETE_NATIVE_ACTOR_OR_ACK_CLOCK"
        last_clock = window["native_kill_ns"]
    elapsed = receipt.get("world_elapsed_seconds")
    if not _positive(elapsed) or not math.isclose(
            elapsed, last_clock / 1e9, abs_tol=1e-6):
        return None, "NATIVE_WORLD_ELAPSED_CLOCK_MISMATCH"
    terminal = receipt.get("native_terminal_recovery")
    if not isinstance(terminal, dict):
        return None, "NATIVE_TERMINAL_FULL_RECOVERY_NOT_RECORDED"
    if (terminal.get("paid") is not True
            or terminal.get("native_clock_accounted") is not True
            or type(terminal.get("start_clock_ns")) is not int
            or terminal["start_clock_ns"] != last_clock
            or type(terminal.get("end_clock_ns")) is not int
            or terminal["end_clock_ns"] < last_clock):
        return None, "NATIVE_TERMINAL_RECOVERY_CLOCK_NOT_PAID"
    # Buffs may change the live actor's maximum resources after prepare.
    # Only the selected Rust Fight reports authoritative end-of-world caps;
    # prepared base stats are not a substitute for these source-native values.
    max_health, max_mana = terminal.get("max_health"), terminal.get("max_mana")
    if (not _positive(max_health) or not _positive(max_mana)
            or not all(_nonnegative(terminal.get(key)) for key in (
                "health_before", "mana_before", "health_after", "mana_after"))
            or not math.isclose(terminal["health_before"],
                                windows[-1]["actor_health"], abs_tol=1e-6)
            or not math.isclose(terminal["mana_before"], mana[-1], abs_tol=1e-6)
            or not math.isclose(terminal["health_after"],
                                max_health, abs_tol=1e-6)
            or not math.isclose(terminal["mana_after"],
                                max_mana, abs_tol=1e-6)):
        return None, "NATIVE_TERMINAL_BOTH_RESOURCES_NOT_FULL"
    debt = (terminal["health_before"] < max_health - 1e-6
            or terminal["mana_before"] < max_mana - 1e-6)
    if debt and terminal["end_clock_ns"] == last_clock:
        return None, "NATIVE_TERMINAL_FREE_RESOURCE_RESET"
    return terminal["end_clock_ns"] / 1e9, "MEASURED_NATIVE_FULLY_RECOVERED"


def compare_prepared_candidates(*, binary: Path,
                                prepared_paths: Mapping[str, Path],
                                actor_level: int, mob_count: int,
                                target_hp: float,
                                run_native: Callable | None = None,
                                artifact_dir: Path | None = None,
                                paid_cache_dir: Path | None = None) -> dict:
    """Evaluate every source-prepared alternative, using balanced one-iteration.

    Work2 supplies the legal frontier and compatible receipt cache. The Rust
    prepare path remains the only game-legality authority; this function
    does not generate or hand-roll any talent/gear/APL/pet build.
    """
    if (type(actor_level) is not int or not 10 <= actor_level <= 60
            or type(mob_count) is not int or not 2 <= mob_count <= 100
            or not _positive(target_hp) or not prepared_paths):
        raise ValueError("INVALID_NATIVE_CANDIDATE_COMPARISON")
    if run_native is None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                               "integrations/mythicsim-rust"))
        from live_two_world_pulls import run as run_native
    rows = []
    # Two labels for the same source-prepared request are one alternative,
    # not independent search breadth. Deduplicate BEFORE paying native mobs.
    seen_source_requests: dict[str, tuple[str, str]] = {}
    if paid_cache_dir is not None and artifact_dir is None:
        raise ValueError("NATIVE_PAID_CACHE_REQUIRES_ARTIFACT_DIR")
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
    if paid_cache_dir is not None:
        paid_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_identity = (_exact_paid_cache_identity(
        binary, actor_level=actor_level, mob_count=mob_count,
        target_hp=float(target_hp)) if artifact_dir is not None else None)
    # Retain original paid receipts even if an optimizer assigns a different
    # label to the same native-prepared candidate on a later frontier pass.
    existing_cache_files = (sorted(artifact_dir.glob("*.native.cache.json"))
                            if cache_identity is not None else [])
    for candidate_id, path in prepared_paths.items():
        if (not isinstance(candidate_id, str) or not candidate_id
                or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                       for c in candidate_id)):
            raise ValueError("INVALID_NATIVE_CANDIDATE_ID")
        prepared = json.loads(path.read_text())
        player = prepared.get("player", {})
        if (player.get("class") != "ClassWarlock"
                or player.get("level") != actor_level):
            raise ValueError("NATIVE_PREPARED_ACTOR_LEVEL_OR_CLASS_MISMATCH")
        source_sha = prepared.get("request_sha256")
        prepared_sha = _sha256(path)
        row = {"candidate_id": candidate_id,
               "prepared_sha256": prepared_sha,
               "source_sha256": source_sha,
               "mob_count": mob_count, "rng_mode": "balanced", "iterations": 1}
        # The source request ID alone does not prove prepared-actor equivalence.
        # A source hash with different prepared bytes must not silently suppress
        # an alternative nor pay an unauthenticated source/actor conflict.
        if not isinstance(source_sha, str) or len(source_sha) != 64:
            row.update(status="INVALID_NATIVE_PREPARED_IDENTITY_OR_CAPACITY",
                       elapsed_seconds=None)
            rows.append(row)
            continue
        prior = seen_source_requests.get(source_sha)
        if prior is not None:
            earlier_id, earlier_prepared_sha = prior
            row.update(
                status=("DUPLICATE_NATIVE_PREPARED_SOURCE"
                        if earlier_prepared_sha == prepared_sha
                        else "CONFLICTING_NATIVE_PREPARED_SOURCE"),
                elapsed_seconds=None, duplicate_of=earlier_id)
            rows.append(row)
            continue
        seen_source_requests[source_sha] = (candidate_id, prepared_sha)
        try:
            native_receipt_path = (
                artifact_dir / f"{candidate_id}.native.json"
                if artifact_dir is not None else None)
            metadata_path = (
                artifact_dir / f"{candidate_id}.native.cache.json"
                if artifact_dir is not None else None)
            receipt = None
            reused = False
            paid_receipt_path = native_receipt_path
            # A separate, stable cache survives Work2's new output directory
            # on every frontier evaluation. The key excludes proposal labels
            # but includes the exact engine, source bytes and paid scenario.
            shared_receipt_path = shared_metadata_path = None
            if cache_identity is not None and paid_cache_dir is not None:
                key_parts = dict(cache_identity, prepared_sha256=prepared_sha,
                                 source_sha256=source_sha)
                cache_key = hashlib.sha256(json.dumps(
                    key_parts, sort_keys=True, allow_nan=False).encode()).hexdigest()
                shared_receipt_path = paid_cache_dir / f"{cache_key}.native.json"
                shared_metadata_path = paid_cache_dir / f"{cache_key}.native.cache.json"
            # Candidate labels can change between frontier passes. Reuse an
            # original source-native ACK under any label only after checking
            # the full engine/scenario/source identity, original byte digest
            # and unchanged terminal-recovery scoring predicate.
            if (cache_identity is not None and native_receipt_path is not None
                    and metadata_path is not None):
                cache_entries = (
                    [shared_metadata_path] if shared_metadata_path is not None
                    else [metadata_path] + [
                        p for p in existing_cache_files if p != metadata_path])
                for cached_metadata_path in cache_entries:
                    cached_receipt_path = cached_metadata_path.with_name(
                        cached_metadata_path.name.removesuffix(
                            ".native.cache.json") + ".native.json")
                    try:
                        metadata = json.loads(cached_metadata_path.read_text())
                        expected = dict(
                            cache_identity, prepared_sha256=prepared_sha,
                            source_sha256=source_sha,
                            native_raw_receipt_sha256=_sha256(cached_receipt_path))
                        if metadata != expected:
                            continue
                        old = json.loads(cached_receipt_path.read_text())
                        old_score, old_status = score_native_chain(
                            old, prepared, mob_count=mob_count,
                            expected_target_hp=target_hp)
                        if (old_score is not None
                                and old_status == "MEASURED_NATIVE_FULLY_RECOVERED"):
                            receipt, reused = old, True
                            paid_receipt_path = cached_receipt_path
                            break
                    except (OSError, ValueError, TypeError):
                        continue
            if receipt is None:
                receipt = run_native(binary, path, target_count=mob_count,
                                     mob_health=target_hp, rng_mode="balanced",
                                     recovery_policy="decisions",
                                     health_threshold=1.0, mana_threshold=1.0,
                                     require_native_health_damage=False)
                if native_receipt_path is not None:
                    native_receipt_path.write_text(
                        json.dumps(receipt, indent=2, allow_nan=False) + "\n")
            score, status = score_native_chain(receipt, prepared,
                                               mob_count=mob_count,
                                               expected_target_hp=target_hp)
            if (score is not None and not reused and cache_identity is not None
                    and native_receipt_path is not None and metadata_path is not None):
                metadata = dict(
                    cache_identity, prepared_sha256=prepared_sha,
                    source_sha256=source_sha,
                    native_raw_receipt_sha256=_sha256(native_receipt_path))
                metadata_text = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
                if shared_receipt_path is not None and shared_metadata_path is not None:
                    # Never overwrite an original paid artifact. A torn or
                    # tampered shared entry is untrusted: this invocation's
                    # fresh raw ACK is still scored from its own output.
                    if (not shared_receipt_path.exists()
                            and not shared_metadata_path.exists()):
                        try:
                            shared_receipt_path.write_bytes(native_receipt_path.read_bytes())
                            shared_metadata_path.write_text(metadata_text)
                            paid_receipt_path = shared_receipt_path
                        except OSError:
                            pass
                else:
                    metadata_path.write_text(metadata_text)
            row.update(status=status, elapsed_seconds=score,
                       acked_world_kills=receipt.get("world_targets_killed"))
            if score is not None:
                # Forward the same verified Rust/2D ACK receipt used for the
                # ranking. World elapsed includes kills, travel and any
                # between-pull rest; terminal time is additional, not free.
                terminal = receipt["native_terminal_recovery"]
                row.update(
                    reused_exact_native_paid_receipt=reused,
                    world_elapsed_before_terminal_seconds=receipt["world_elapsed_seconds"],
                    terminal_recovery_seconds=(
                        terminal["end_clock_ns"] - terminal["start_clock_ns"]) / 1e9,
                    terminal_health=terminal["health_after"],
                    terminal_max_health=terminal["max_health"],
                    terminal_mana=terminal["mana_after"],
                    terminal_max_mana=terminal["max_mana"],
                )
                if native_receipt_path is not None:
                    row.update(native_raw_receipt_file=str(paid_receipt_path),
                               native_raw_receipt_sha256=_sha256(paid_receipt_path))
        except (RuntimeError, AssertionError, ValueError, OSError,
                subprocess.SubprocessError) as exc:
            row.update(status="NATIVE_REFUSAL", elapsed_seconds=None,
                       refusal=str(exc)[-1500:])
        rows.append(row)
    measured = sorted((r for r in rows if r["elapsed_seconds"] is not None),
                      key=lambda r: (r["elapsed_seconds"], r["candidate_id"]))
    # One fully-scored candidate is still a baseline, not competitive search.
    # Allow it as a native-paid successor in Work2\'s competing parent beams.
    return {"kind": "native_warlock_comparable_candidate_screen_v1",
            "actor_level": actor_level, "mob_count": mob_count,
            "rng_mode": "balanced", "iterations": 1,
            "terminal_full_recovery_required": True,
            "candidates": rows, "comparable_candidates": len(measured),
            "winner_candidate_id": (measured[0]["candidate_id"]
                                    if len(measured) >= 2 else None),
            "winner_elapsed_seconds": (measured[0]["elapsed_seconds"]
                                       if len(measured) >= 2 else None),
            "status": ("MEASURED_BOUNDED_NATIVE_COMPARISON" if len(measured) >= 2
                       else "PROVISIONAL_NO_COMPETITIVE_FULL_RECOVERY")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--prepared", action="append", required=True,
                    help="Repeat CANDIDATE_ID=RUST_PREPARED_JSON (one or more)")
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--mob-count", type=int, default=3)
    ap.add_argument("--target-hp", type=float, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--paid-cache-dir", type=Path,
                    help="Stable exact-input native paid-receipt cache across frontier calls")
    args = ap.parse_args()
    candidates = {}
    for spec in args.prepared:
        candidate_id, sep, path = spec.partition("=")
        if not sep or candidate_id in candidates or not path:
            ap.error("each --prepared needs unique CANDIDATE_ID=PATH")
        candidates[candidate_id] = Path(path)
    result = compare_prepared_candidates(
        binary=args.binary, prepared_paths=candidates,
        actor_level=args.level, mob_count=args.mob_count,
        target_hp=args.target_hp, artifact_dir=args.out,
        paid_cache_dir=args.paid_cache_dir)
    (args.out / "comparison.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
