"""Source hook pinning RED/GREEN; synthetic source is a patcher unit fixture."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "integrations/mythicsim-go/world_boundary/patch_native_spell_result.py"
spec = importlib.util.spec_from_file_location("pinned_go_damage_patcher_testonly", PATH)
assert spec and spec.loader
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


def test_reject_nonpinned_native_spell_result(tmp_path):
    file = tmp_path / "spell_result.go"
    file.write_bytes(patcher.ORIGINAL + b"\n}\n")
    before = file.read_bytes()
    with pytest.raises(ValueError, match="PINNED_NATIVE_SPELL_RESULT_BLOB_MISMATCH"):
        patcher.patch_native_spell_result(file)
    assert file.read_bytes() == before


def test_exact_blob_guard_and_one_source_damage_hook(monkeypatch, tmp_path):
    raw = patcher.ORIGINAL + b"\tspell.DisposeResult(result)\n}\n"
    file = tmp_path / "spell_result.go"
    file.write_bytes(raw)
    monkeypatch.setattr(patcher, "PINNED_BLOB_SHA", patcher.git_blob_sha(raw))
    patcher.patch_native_spell_result(file)
    after = file.read_bytes()
    assert after.count(b"recordWorldDamageForGsim(sim, spell, result, isPeriodic)") == 1
    assert b"spell.DisposeResult(result)" in after
    with pytest.raises(ValueError, match="PINNED_NATIVE_SPELL_RESULT_BLOB_MISMATCH"):
        patcher.patch_native_spell_result(file)
