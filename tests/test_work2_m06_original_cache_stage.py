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
