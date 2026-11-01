"""Real canonical/staged SQLite acquisition-audit entrypoint regression."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.audit_source_acquisition_gate import audit

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "audit_source_acquisition_gate.py"


def test_direct_cli_executes_real_nine_class_source(tmp_path: Path) -> None:
    output = tmp_path / "acquisition.json"
    result = subprocess.run(
        [sys.executable, str(CLI), "--level", "20", "--db",
         str(DEFAULT_DB), "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert len(report["classes"]) == 9
    assert report["source_indexed_acquisition_rows"] > 0
    # An inventory is not a validated acquisition route.
    assert report["class_level_fully_validated_checkpoints"] == 0


def test_audit_uses_selected_staged_db_for_actual_game_ir(tmp_path: Path) -> None:
    staged = tmp_path / "acquisition-stage.sqlite"
    shutil.copyfile(DEFAULT_DB, staged)
    # Remove only staged source-index ability rows; canonical remains untouched.
    # The production source compiler must observe this changed inventory.
    with sqlite3.connect(staged) as db:
        deleted = db.execute(
            "DELETE FROM spell_index WHERE class_key='druid' AND kind='abilities'"
        ).rowcount
    assert deleted > 0
    canonical_ir = build_game_ir_slice(class_key="druid", level=20)
    staged_ir = build_game_ir_slice(
        class_key="druid", level=20, ability_db_path=staged)
    assert canonical_ir is not None and staged_ir is not None
    assert len(canonical_ir.actions) != len(staged_ir.actions)
    report = audit(level=20, db_path=staged)
    assert report["classes"]["druid"]["ir_actions"] == len(staged_ir.actions)


def test_missing_selected_source_db_does_not_create_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing-source.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        audit(level=20, db_path=missing)
    assert not missing.exists()
