"""Fail-closed M0.6 original-paid cache archive staging contract (no native replay)."""
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from tools.wf_m06_original_cache_stage import stage_original_paid_cache


RUNTIME = {
    "cache_schema": 2,
    "forever_paid_runtime_sha256": "a" * 64,
    "native_binary_sha256": "b" * 64,
}


def make_archive(tmp_path, *, identity=None, digest_ok=True, filename_prefix="native-api-paid-cache/",
                 missing_raw=False, traversal=False):
    meta = dict(RUNTIME if identity is None else identity)
    raw = b'{"source_sha256":"sample","native_world_overlap_verified":false}\n'
    meta.update({
        "source_sha256": "c" * 64,
        "prepared_sha256": "d" * 64,
        "actor_level": 20, "mob_count": 2, "target_hp": 484.0,
        "native_raw_receipt_sha256":
            hashlib.sha256(raw).hexdigest() if digest_ok else "0" * 64,
    })
    archive = tmp_path / "original.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        prefix = "../" if traversal else filename_prefix
        zf.writestr(prefix + "paid.native.cache.json", json.dumps(meta))
        if not missing_raw:
            zf.writestr(prefix + "paid.native.json", raw)
        zf.writestr("m06-adaptive-original.json", "{}")
    return archive, raw


def test_original_cache_stage_preserves_exact_bytes_and_identity(tmp_path):
    archive, raw = make_archive(tmp_path)
    out = tmp_path / "cache"
    result = stage_original_paid_cache(archive, out, expected_identity=RUNTIME)
    assert result["status"] == "M06_COMPATIBLE_CACHE_STAGED"
    assert result["imported_pairs"] == 1
    assert result["excluded_incompatible_pairs"] == 0
    assert (out / "paid.native.json").read_bytes() == raw
    assert json.loads((out / "paid.native.cache.json").read_text())[
        "native_raw_receipt_sha256"] == hashlib.sha256(raw).hexdigest()
    assert len(list(out.iterdir())) == 2
    with pytest.raises(FileExistsError, match="M06_CACHE_DESTINATION_COLLISION"):
        stage_original_paid_cache(archive, out, expected_identity=RUNTIME)


@pytest.mark.parametrize("change,expected", [
    ({"native_binary_sha256": "f" * 64}, "M06_NO_COMPATIBLE_ORIGINAL_PAID_CACHE"),
    ({"forever_paid_runtime_sha256": "e" * 64}, "M06_NO_COMPATIBLE_ORIGINAL_PAID_CACHE"),
])
def test_changed_native_binary_or_runtime_never_replays_paid_receipts(
        tmp_path, change, expected):
    archive, _ = make_archive(tmp_path, identity=dict(RUNTIME, **change))
    out = tmp_path / "cache"
    with pytest.raises(ValueError, match=expected):
        stage_original_paid_cache(archive, out, expected_identity=RUNTIME)
    assert not out.exists()


def test_tampered_original_receipt_is_not_imported(tmp_path):
    archive, _ = make_archive(tmp_path, digest_ok=False)
    out = tmp_path / "cache"
    with pytest.raises(ValueError, match="M06_ORIGINAL_RAW_RECEIPT_DIGEST_MISMATCH"):
        stage_original_paid_cache(archive, out, expected_identity=RUNTIME)
    assert not out.exists()


def test_incomplete_or_path_traversal_original_archive_is_rejected(tmp_path):
    for kwargs, expected in [
        ({"missing_raw": True}, "M06_CACHE_PAIR_MISSING_RAW_RECEIPT"),
        ({"traversal": True}, "M06_UNSAFE_CACHE_ARCHIVE_ENTRY"),
    ]:
        archive, _ = make_archive(tmp_path, **kwargs)
        with pytest.raises(ValueError, match=expected):
            stage_original_paid_cache(
                archive, tmp_path / "cache", expected_identity=RUNTIME)
        assert not (tmp_path / "cache").exists()


def test_invalid_runtime_identity_fails_closed_before_import(tmp_path):
    archive, _ = make_archive(tmp_path)
    with pytest.raises(ValueError, match="M06_CURRENT_PAID_RUNTIME_NOT_VERIFIABLE"):
        stage_original_paid_cache(
            archive, tmp_path / "cache", expected_identity={
                "cache_schema": 2, "native_binary_sha256": "b" * 64})


def test_verified_runtime_migration_stages_original_bytes_not_rewritten(
        tmp_path, monkeypatch):
    import tools.wf_m06_original_cache_stage as stage
    old = dict(RUNTIME, forever_paid_runtime_sha256="e" * 64)
    archive, raw = make_archive(tmp_path, identity=old)
    predecessor = "c" * 40
    observed = []

    def verified(meta, current, revision):
        observed.append((meta["forever_paid_runtime_sha256"],
                         current["forever_paid_runtime_sha256"], revision))
        return revision == predecessor

    monkeypatch.setattr(stage, "_verified_schema2_paid_runtime_migration",
                        verified)
    out = tmp_path / "cache"
    result = stage.stage_original_paid_cache(
        archive, out, expected_identity=RUNTIME,
        predecessor_ref=predecessor)
    assert observed == [("e" * 64, "a" * 64, predecessor)]
    assert result["verified_runtime_migration_pairs"] == 1
    assert (out / "paid.native.json").read_bytes() == raw
    assert json.loads((out / "paid.native.cache.json").read_text())[
        "forever_paid_runtime_sha256"] == "e" * 64
    assert json.loads((out / "m06-runtime-migration.json").read_text())[
        "predecessor_ref"] == predecessor
    assert len(list(out.iterdir())) == 3


def test_historical_runtime_migration_rejects_changed_paid_world_code(
        monkeypatch):
    import types
    import tools.wf_warlock_native_candidate_scoring as scorer
    predecessor = "c" * 40
    old_objects = ["d" * 40] * len(scorer._PAID_RUNTIME_GIT_PATHS)
    historic = hashlib.sha256("\n".join(old_objects).encode()).hexdigest()
    old = dict(RUNTIME, forever_paid_runtime_sha256=historic)
    current = dict(RUNTIME, forever_paid_runtime_sha256="a" * 64)

    source_scorer = (
        "def score_native_chain():\n    return 1\n"
        "def _exact_paid_cache_identity():\n    return 2\n")
    source_persistent_old = (
        "def _native_world_policy():\n    return 1\n"
        "def _native_rolling_receipt_verified():\n    return True\n"
        "class PersistentNativeEvaluator:\n"
        "    def _source(self):\n        return 1\n"
        "    def _paid(self):\n        return 1\n")
    source_persistent_head = source_persistent_old.replace(
        "    def _paid(self):\n        return 1\n",
        "    def _paid(self):\n"
        "        if not fresh_world:\n"
        "            cache_name = 'm06-runtime-migration.json'\n"
        "        return 1\n")
    changed = ["tools/wf_warlock_native_persistent_optimizer.py"]
    mutate_paid = [False]

    def fake_git(argv, **kwargs):
        assert argv[0] == "git"
        if argv[1] == "rev-parse":
            value = "\n".join(old_objects)
        elif argv[1] == "diff":
            value = "\n".join(changed)
        elif argv[1] == "show":
            revision, path = argv[2].split(":", 1)
            if path.endswith("native_candidate_scoring.py"):
                value = source_scorer
            else:
                value = (source_persistent_old if revision != "HEAD"
                         else source_persistent_head.replace(
                             "        return 1\n", "        return 0\n")
                         if mutate_paid[0] else source_persistent_head)
        else:
            raise AssertionError(argv)
        return types.SimpleNamespace(stdout=value)

    monkeypatch.setattr(scorer.subprocess, "run", fake_git)
    assert scorer._verified_schema2_paid_runtime_migration(
        old, current, predecessor)
    changed.append("src/game/runtime/go_native_world_damage_ack.py")
    assert not scorer._verified_schema2_paid_runtime_migration(
        old, current, predecessor)
    changed.pop()
    mutate_paid[0] = True
    assert not scorer._verified_schema2_paid_runtime_migration(
        old, current, predecessor)


def test_original_refusals_are_excluded_only_with_original_native_context(
        tmp_path):
    archive, _ = make_archive(tmp_path)
    matching = {
        "level": 20, "native_status": "NATIVE_API_CANDIDATE_REFUSED",
        "native_prepared": True,
        "engine_binary_sha256": RUNTIME["native_binary_sha256"],
        "source_request_sha256": "c" * 64,
        "native_world_policy": {
            "pull_mode": "rolling", "rest_when_health_below": 1.0,
            "rest_when_mana_below": 1.0},
        "native_refusal_code": "native_rolling_two_live_targets_not_acked",
    }
    unrelated = dict(matching, level=40)
    original = {
        "native_engine_binary_sha256": RUNTIME["native_binary_sha256"],
        "mob_count": 2,
        "rejected_native_attempts": [matching, unrelated],
    }
    with zipfile.ZipFile(archive, "a") as zf:
        # An exact filename duplicate would itself be unsafe; use a fresh ZIP.
        replacement = tmp_path / "with-original-result.zip"
        with zipfile.ZipFile(replacement, "w") as output:
            for name in zf.namelist():
                if name == "m06-adaptive-original.json":
                    output.writestr(name, json.dumps(original))
                else:
                    output.writestr(name, zf.read(name))
    out = tmp_path / "cache"
    result = stage_original_paid_cache(
        replacement, out, expected_identity=RUNTIME)
    assert result["excluded_prior_native_refusals"] == 1
    refusal_ledger = json.loads(
        (out / "m06-original-refusals.json").read_text())
    assert refusal_ledger["native_binary_sha256"] == (
        RUNTIME["native_binary_sha256"])
    assert len(refusal_ledger["refused"]) == 1
    assert refusal_ledger["refused"][0]["target_hp"] == 484.0
    assert refusal_ledger["refused"][0]["native_refusal_code"] == (
        "native_rolling_two_live_targets_not_acked")
