"""Fast, synthetic verification of immutable L47-L60 raw evidence retention."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location(
    "actions_preserve_paid_receipts",
    Path(__file__).resolve().parents[2] / "tools/actions_preserve_paid_receipts.py",
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture_archive(tmp_path, *, skip=None, broken=None, no_request=None):
    output = tmp_path / "paid.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for level in range(47, 61):
            if level == skip:
                continue
            base = f"warlock-paid-range/L{level}/candidate/paid/native_l{level}/best_apl/"
            data = {
                "native_windows": [{}] * (99 if level == broken else 100),
                "world_kills": [{}] * 100,
                "world_targets_killed": 100,
                "continuous_native_actor": True,
                "actual_2d_ack": True,
                "paid_recovery": True,
                "source_sha256": f"{level:064x}",
            }
            out.writestr(base + "chain_native_world.json", json.dumps(data))
            if level != no_request:
                out.writestr(base + "source_request.json", "{}")
    return output, hashlib.sha256(output.read_bytes()).hexdigest()


def test_complete_original_paid_receipts_are_retained(tmp_path):
    path, digest = fixture_archive(tmp_path)
    result = module.validate_archive(path, digest)
    assert sorted(result) == list(range(47, 61))
    assert result[47] == f"{47:064x}"


def test_wrong_digest_fails_closed(tmp_path):
    path, _ = fixture_archive(tmp_path)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        module.validate_archive(path, "0" * 64)


@pytest.mark.parametrize("condition, level, message", [
    ("skip", 60, "missing=\\[60\\]"),
    ("broken", 49, "L49: expected complete"),
    ("no_request", 50, "L50: original paid source request missing"),
])
def test_incomplete_native_world_is_never_published(tmp_path, condition, level, message):
    path, digest = fixture_archive(tmp_path, **{condition: level})
    with pytest.raises(ValueError, match=message):
        module.validate_archive(path, digest)
