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

def test_verified_historical_runtime_rekeys_paid_receipt_but_preserves_raw_bytes(
        tmp_path, monkeypatch):
    import tools.wf_m06_original_cache_stage as stage
    old = dict(RUNTIME, forever_paid_runtime_sha256="e" * 64)
    archive, raw = make_archive(tmp_path, identity=old)
    monkeypatch.setattr(stage, "_original_m06_runtime_compatible",
                        lambda record, expected: (
                            record["forever_paid_runtime_sha256"] == "e" * 64
                            and expected == RUNTIME))
    out = tmp_path / "cache"
    result = stage_original_paid_cache(archive, out, expected_identity=RUNTIME)
    assert result["migrated_original_runtime_pairs"] == 1
    assert result["imported_pairs"] == 1
    original = out / "original-runtime-provenance"
    with zipfile.ZipFile(archive) as zf:
        for suffix in (".native.json", ".native.cache.json"):
            assert (original / ("paid" + suffix)).read_bytes() == zf.read(
                "native-api-paid-cache/paid" + suffix)
    current = dict(RUNTIME, source_sha256="c" * 64,
                   prepared_sha256="d" * 64)
    current_key = hashlib.sha256(
        json.dumps(current, sort_keys=True).encode()).hexdigest()
    assert (out / f"{current_key}.native.json").read_bytes() == raw
    assert json.loads(
        (out / f"{current_key}.native.cache.json").read_text()) == dict(
            current, native_raw_receipt_sha256=hashlib.sha256(raw).hexdigest())
    assert sorted(p.name for p in out.glob("*.native.json")) == [
        f"{current_key}.native.json"]


def test_unverified_historical_runtime_cannot_be_staged(tmp_path, monkeypatch):
    import tools.wf_m06_original_cache_stage as stage
    archive, _ = make_archive(
        tmp_path, identity=dict(RUNTIME, forever_paid_runtime_sha256="e" * 64))
    monkeypatch.setattr(stage, "_original_m06_runtime_compatible",
                        lambda record, expected: False)
    out = tmp_path / "cache"
    with pytest.raises(ValueError, match="M06_NO_COMPATIBLE_ORIGINAL_PAID_CACHE"):
        stage_original_paid_cache(archive, out, expected_identity=RUNTIME)
    assert not out.exists()


def test_historical_runtime_requires_available_verified_git_objects(monkeypatch):
    import tools.wf_m06_original_cache_stage as stage
    def missing_historical_git(*args, **kwargs):
        raise OSError("original Git objects unavailable")
    monkeypatch.setattr(stage.subprocess, "run", missing_historical_git)
    assert not stage._original_m06_runtime_compatible(
        dict(RUNTIME, forever_paid_runtime_sha256="e" * 64), RUNTIME)

def test_nested_original_provenance_is_not_reimported_as_paid_cache(tmp_path):
    archive, raw = make_archive(tmp_path)
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr(
            "runs/native-api-paid-cache/original-runtime-provenance/"
            "paid.native.cache.json",
            '{"cache_schema":2,"forever_paid_runtime_sha256":"old"}')
        zf.writestr(
            "runs/native-api-paid-cache/original-runtime-provenance/"
            "paid.native.json", raw)
    out = tmp_path / "cache"
    result = stage_original_paid_cache(archive, out, expected_identity=RUNTIME)
    assert result["imported_pairs"] == 1
    assert result["migrated_original_runtime_pairs"] == 0
    assert (out / "paid.native.json").read_bytes() == raw
    assert len(list(out.glob("*.native.cache.json"))) == 1
