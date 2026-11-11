"""Persistent Rust options/prepare/evaluate adapter for the generic optimizer.

Only Rust decides whether a proposed build is executable. World damage, travel,
survival and full-resource recovery run through the existing causal gsim bridge.
No source/prepared JSON exchange files or Python Warcraft rules are involved.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from src.scenarios.leveling_targets import representative_hp
from tools.wf_warlock_native_source_frontier import (
    _backward_ancestor_variants, _native_apl_variants, _variants,
)
from tools.wf_warlock_native_candidate_scoring import (
    _exact_paid_cache_identity, score_native_chain,
)

BRIDGE = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust"
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    return _digest(path.read_bytes())


def _source_item_alternatives(source: dict, options: dict):
    """Mutate equipment solely from Rust-advertised item IDs.

    Unverified item options are NOT declared legal. Rust prepare can accept or
    refuse each proposal. Keep the untouched seed too, even if not advertised.
    """
    choices = options.get("items", [])
    if not isinstance(choices, list):
        return
    available = {row.get("item_id") for row in choices
                 if isinstance(row, dict) and type(row.get("item_id")) is int}
    actor = source["raid"]["parties"][0]["players"][0]
    equipped = actor.get("equipment", {}).get("items", [])
    if not isinstance(equipped, list):
        return
    missing = [n for n, row in enumerate(equipped)
               if isinstance(row, dict) and row.get("id") not in (None, 0)
               and row["id"] not in available]
    if missing:
        clean = copy.deepcopy(source)
        for index in missing:
            clean["raid"]["parties"][0]["players"][0]["equipment"]["items"][index] = {"id": 0}
        yield clean
        for index in missing[:2]:
            single = copy.deepcopy(source)
            single["raid"]["parties"][0]["players"][0]["equipment"]["items"][index] = {"id": 0}
            yield single


class NativeApiSession:
    """One pinned binary and one ordered NDJSON stream for all sampled levels."""

    def __init__(self, binary: Path):
        self.process = subprocess.Popen(
            [str(binary.resolve()), "api"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            env=dict(os.environ, FOREVER_GSIM_WORLD_BRIDGE="1"),
        )

    def request(self, payload: dict) -> dict:
        if self.process.poll() is not None:
            raise RuntimeError("RUST_NATIVE_API_PROCESS_EXITED")
        self.process.stdin.write(json.dumps(payload, sort_keys=True) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("RUST_NATIVE_API_NO_RESPONSE")
        response = json.loads(line)
        if response.get("ok") is not True:
            raise ValueError("RUST_NATIVE_API_REFUSAL:" + str(response.get("error"))[-1200:])
        if not isinstance(response.get("result"), dict):
            raise ValueError("RUST_NATIVE_API_RESULT_INVALID")
        return response["result"]

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()


class PersistentNativeEvaluator:
    """Callable native candidate evaluator shared by stride 20/10/5/1.

    The session and exact-compatible paid cache outlive individual levels.
    Every candidate consumes one Rust prepare attempt; failures stay visible.
    """

    def __init__(self, binary: Path, source: Path, artifact_dir: Path, *,
                 target_hp: float | None = None,
                 session_factory: Callable = NativeApiSession,
                 run_world: Callable | None = None):
        self.binary = binary
        self.template = json.loads(source.read_text())
        self.artifact_dir = artifact_dir
        self.target_hp = target_hp
        self.session = session_factory(binary)
        if run_world is None:
            from live_two_world_pulls import run as run_world
        self.run_world = run_world
        self.engine_sha = _file_digest(binary)
        self.options: dict[int, dict] = {}
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def close(self):
        self.session.close()

    def _options(self, level: int) -> dict:
        if level not in self.options:
            self.options[level] = self.session.request(
                {"op": "options", "class": "warlock", "level": level})
        return self.options[level]

    def _source(self, level: int, talents: str | None, *,
                apl_source: dict | None = None) -> dict:
        source = copy.deepcopy(apl_source if apl_source is not None else self.template)
        actor = source["raid"]["parties"][0]["players"][0]
        actor["level"] = level
        source["encounter"]["targets"][0]["level"] = level
        # The original L20 fixture has a 12s stationary smoke horizon.
        # Full level-scaled mobs at L40/L60 can require longer to die.
        # This is only a generous source-native fight timeout, never elapsed
        # charged time: Rust/gsim uses actual lethal ACK and recovery clocks.
        source["encounter"]["duration"] = max(
            180, int(source["encounter"].get("duration", 0)))
        if talents is not None:
            actor["talentsString"] = talents
        return source

    def _paid(self, source: dict, prepared: dict, *, level: int, mobs: int,
              target_hp: float, cid: str) -> tuple[dict, float, bool, Path]:
        native_sha = prepared["request_sha256"]
        # Cache includes the exact source-produced prepared actor, not a
        # raw-JSON SHA wrongly equated to Rust's protobuf request digest.
        prepared_digest = _digest(json.dumps(
            prepared, sort_keys=True, separators=(",", ":")).encode())
        identity = _exact_paid_cache_identity(
            self.binary, actor_level=level, mob_count=mobs, target_hp=target_hp)
        if identity is not None:
            identity = dict(identity, source_sha256=native_sha,
                            prepared_sha256=prepared_digest)
            key = _digest(json.dumps(identity, sort_keys=True).encode())
        else:
            key = _digest((native_sha + cid).encode())
        path = self.artifact_dir / (key + ".native.json")
        meta = self.artifact_dir / (key + ".native.cache.json")
        cached = False
        if identity is not None and path.is_file() and meta.is_file():
            try:
                record = json.loads(meta.read_text())
                if record == dict(identity, native_raw_receipt_sha256=_file_digest(path)):
                    receipt = json.loads(path.read_text())
                    elapsed, verdict = score_native_chain(
                        receipt, prepared, mob_count=mobs, expected_target_hp=target_hp)
                    if elapsed is not None and verdict == "MEASURED_NATIVE_FULLY_RECOVERED":
                        return receipt, elapsed, True, path
            except (ValueError, TypeError, OSError, KeyError):
                pass
        receipt = self.run_world(
            self.binary, None, target_count=mobs, mob_health=target_hp,
            rng_mode="balanced", recovery_policy="decisions",
            health_threshold=1.0, mana_threshold=1.0,
            api_process=self.session.process, prepared_payload=prepared,
            require_native_health_damage=False,
        )
        elapsed, verdict = score_native_chain(
            receipt, prepared, mob_count=mobs, expected_target_hp=target_hp)
        if elapsed is None or verdict != "MEASURED_NATIVE_FULLY_RECOVERED":
            raise ValueError("RUST_NATIVE_PAID_SCORE_REFUSED:" + verdict)
        # Keep actual original bytes and pin the digest. An inconsistent old
        # cache entry is never overwritten and never becomes a paid result.
        if not path.exists() and not meta.exists():
            path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
            if identity is not None:
                meta.write_text(json.dumps(
                    dict(identity, native_raw_receipt_sha256=_file_digest(path)),
                    sort_keys=True, indent=2) + "\n")
        elif path.exists():
            # A collision/tampered record cannot become a mismatched receipt.
            other = self.artifact_dir / (key + "-" + cid + ".native.json")
            other.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
            path = other
        return receipt, elapsed, cached, path

    def __call__(self, *, level: int, parent: dict | None, mob_count: int,
                 budget: int, rng_mode: str, iterations: int,
                 recover_to_full: bool, search_mode: str = "independent",
                 candidate_hints: list | None = None) -> list[dict]:
        if (parent is not None or search_mode != "independent"
                or rng_mode != "balanced" or iterations != 1
                or recover_to_full is not True or not 2 <= mob_count <= 100):
            raise ValueError("NATIVE_API_SUPPORTS_SAMPLED_INDEPENDENT_ROOTS_ONLY")
        if budget < 1:
            return []
        try:
            options = self._options(level)
            talents = options["talents"]
            trees = talents["trees"]
            points = talents["points_available"]
            if (talents["status"] != "ok" or options["level"] != level
                    or len(trees) != 3):
                raise ValueError("RUST_NATIVE_TALENT_OPTIONS_INCOMPLETE")
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            return [{"status": "NATIVE_OPTIONS_REFUSED", "level": level,
                     "native_refusal": str(exc)[-1200:]}]

        seed = self._source(level, None)
        seed_talents = seed["raid"]["parties"][0]["players"][0]["talentsString"]
        proposed_talents = []
        proposed_talents.extend(_backward_ancestor_variants(
            candidate_hints, points_available=points))
        from itertools import islice
        proposed_talents.extend(islice(
            _variants(seed_talents, trees, points_available=points),
            max(8, budget * 4)))
        native_family_talents = list(dict.fromkeys(proposed_talents))
        head = native_family_talents[:3]
        sources = []
        # The source Rust item list already excludes combat-rating gear. A
        # legacy L20 seed equipped with that gear must not spend the first
        # three native attempts on predictably rejected talent-only changes.
        # Pair *each* distinct native talent family with a gear-cleared
        # proposal before moving to the next family. Rust still decides
        # whether any source-produced candidate prepares or kills real mobs.
        for variant in head:
            proposal = self._source(level, variant)
            sources.append(proposal)
            sources.extend(islice(_source_item_alternatives(proposal, options), 1))
        if seed_talents not in head:
            sources.append(seed)
            sources.extend(islice(_source_item_alternatives(seed, options), 1))
        sources.extend(self._source(level, variant)
                       for variant in native_family_talents[3:]
                       if variant != seed_talents)
        seen: set[str] = set()
        results: list[dict] = []
        apl_expanded = False
        target_hp = (float(representative_hp(level))
                     if self.target_hp is None else self.target_hp)
        index = 0
        while index < len(sources) and len(results) < budget:
            source = sources[index]
            index += 1
            identity = json.dumps(source, sort_keys=True)
            if identity in seen:
                continue
            seen.add(identity)
            cid = f"L{level}_api_{len(results):03d}"
            try:
                prepared = self.session.request(
                    {"op": "prepare", "request": source, "actor_level": level})
                player = prepared["player"]
                if (player.get("class") != "ClassWarlock"
                        or player.get("level") != level
                        or not isinstance(prepared.get("request_sha256"), str)
                        or len(prepared["request_sha256"]) != 64):
                    raise ValueError("RUST_NATIVE_PREPARED_ACTOR_INVALID")
                if not apl_expanded:
                    apl_expanded = True
                    # Only prepared-native SpellFlagAPL actions may enter a
                    # changed rotation. The new candidate must prepare again.
                    # Do not starve alternative legal tree families
                    # before paying optional prepared-native APL mutations.
                    sources.extend(islice(_native_apl_variants(source, prepared), 2))
                receipt, elapsed, cached, raw_path = self._paid(
                    source, prepared, level=level, mobs=mob_count,
                    target_hp=target_hp, cid=cid)
                terminal = receipt["native_terminal_recovery"]
                actor = source["raid"]["parties"][0]["players"][0]
                cls_options = actor.get("warlock", {}).get(
                    "options", {}).get("classOptions", {})
                results.append({
                    "status": "MEASURED_NATIVE_FULLY_RECOVERED",
                    "candidate_id": cid, "level": level, "mob_count": mob_count,
                    "targets_killed": receipt["world_targets_killed"],
                    "rng_mode": rng_mode, "iterations": iterations,
                    "native_prepared": True,
                    "native_world_ack": receipt["actual_2d_ack"] is True,
                    "source_request_sha256": prepared["request_sha256"],
                    "engine_binary_sha256": self.engine_sha,
                    "native_full_recovery_paid": terminal.get("paid") is True
                        and terminal.get("native_clock_accounted") is True,
                    "recover_to_full": True,
                    "terminal_hp": terminal["health_after"],
                    "terminal_max_hp": terminal["max_health"],
                    "terminal_mana": terminal["mana_after"],
                    "terminal_max_mana": terminal["max_mana"],
                    "elapsed_seconds": elapsed,
                    "terminal_recovery_seconds":
                        (terminal["end_clock_ns"] - terminal["start_clock_ns"]) / 1e9,
                    "talents": actor["talentsString"],
                    "gear": actor.get("equipment"),
                    "apl": actor.get("rotation"),
                    "pet": cls_options.get("summon"),
                    "native_raw_receipt_file": str(raw_path),
                    "native_raw_receipt_sha256": _file_digest(raw_path),
                    "reused_exact_native_paid_receipt": cached,
                })
            except (KeyError, ValueError, TypeError, RuntimeError, AssertionError,
                    OSError, subprocess.SubprocessError) as exc:
                results.append({
                    "status": "NATIVE_API_CANDIDATE_REFUSED",
                    "candidate_id": cid, "level": level,
                    "native_prepared": False,
                    "native_refusal": str(exc)[-1500:],
                })
        return results
