"""The legacy native-source compiler is not loaded by source-only imports.

The compiler stays runnable for actual verified sources until selected Rust
native APIs replace the remaining live GameIR consumers (#357/#359).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_native_source_provider_import_and_unsupported_level_are_gameir_free():
    code = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import native_source_provider as provider

assert provider.DEFAULT_DB is DEFAULT_DB
for module in ('src.game.data.forever.sqlite_talents', 'src.game.model.ir',
               'src.game.runtime.simulator'):
    assert module not in sys.modules, module

# The existing unqualified actor/level early return must stay cheap.
assert provider.build_source_slice('hunter', 9) is None
for module in ('src.game.data.forever.sqlite_talents', 'src.game.model.ir',
               'src.game.runtime.simulator'):
    assert module not in sys.modules, module

from src.game.data.forever.sqlite_talents import DEFAULT_DB as legacy_default
assert legacy_default is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_supported_native_source_provider_still_compiles_legacy_ir():
    from src.game.data.forever.native_source_provider import build_source_slice

    hunter = build_source_slice("hunter", 10)
    assert hunter is not None
    assert hunter.actor.metadata["class_key"] == "hunter"
    assert any(action.family_key == "arcane_shot" for action in hunter.actions)
