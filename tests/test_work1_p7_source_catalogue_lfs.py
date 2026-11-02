"""Real-source P7 gear catalogues must be hydrated, not Git LFS pointers.

This is an I/O preflight. No fake item facts or gate-PASS evidence.
"""
from pathlib import Path
from types import SimpleNamespace
import sqlite3

import pytest

from tools import wf_gate_p7_4_live as p74
from tools import wf_gate_p7_5_live as p75
from tools.wf_gate_p7_2_live import _source_module

ROOT = Path(__file__).resolve().parents[1]


def _validator():
    return _source_module(
        ROOT / "integrations/mythicsim-rust/p74_gear_validation.py",
        "work1_source_item_validator",
    ).GearValidator


@pytest.mark.parametrize("content,reason", [
    (b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\n",
     "SOURCE_CATALOGUE_GIT_LFS_POINTER_NOT_HYDRATED"),
    (b"invalid SQLite source content", "SOURCE_CATALOGUE_NOT_SQLITE"),
])
def test_source_gear_validator_refuses_non_sqlite_before_open(tmp_path, content, reason):
    catalogue = tmp_path / "items.sqlite"
    catalogue.write_bytes(content)
    with pytest.raises(ValueError, match=reason):
        _validator().require_sqlite_catalogue(catalogue)


def test_real_sqlite_source_passes_header_preflight(tmp_path):
    catalogue = tmp_path / "items.sqlite"
    with sqlite3.connect(catalogue) as connection:
        connection.execute("CREATE TABLE items (item_id INTEGER)")
    _validator().require_sqlite_catalogue(catalogue)


@pytest.mark.parametrize(("module", "gate"), [(p74, "P7_4"), (p75, "P7_5")])
def test_unhydrated_source_cannot_reach_native_gear_scoring(tmp_path, monkeypatch,
                                                             module, gate):
    root = tmp_path / "project"
    catalogue = root / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("version https://git-lfs.github.com/spec/v1\n")
    engine = tmp_path / "upstream"
    for name in ("items.jsonl", "enchants.jsonl"):
        file = engine / "data" / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('{"id": 1, "name": "sample"}\n')
    binary = engine / "target/release/forever-engine"
    monkeypatch.setattr(module, "_pinned_source_runtime",
                        lambda *args: ({"raid": {"parties": []}}, {}, binary))
    monkeypatch.setattr(module, "_source_module",
                        lambda *args: SimpleNamespace(GearValidator=_validator()))
    result = module.run_live(root, "druid", 60, spec="balance")
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == [gate + "_SOURCE_CATALOGUE_GIT_LFS_POINTER_NOT_HYDRATED"]
