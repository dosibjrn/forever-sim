from __future__ import annotations

import hashlib
from pathlib import Path

from src import game_context
from src.engine_registry import get_engine, reset_engine_cache

# Temporary hard parity lock for the v0.10 architecture refactor.  The released
# v0.9.5 Classic Mage engine must remain byte-identical until the refactor is
# explicitly declared done; pre-existing mechanics fixes belong in BACKLOG.md.
V095_CLASSIC_ENGINE_SHA256 = "97ec2a664c5c1cb167d6f3a62b0524732d2e2793678a749411cc3ad22a01b5a4"


def test_classic_engine_is_byte_identical_to_v095_during_refactor():
    try:
        game_context.configure("classic", "mage")
        reset_engine_cache()
        path = Path(get_engine().__file__).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == V095_CLASSIC_ENGINE_SHA256
    finally:
        game_context.configure("classic", "mage")
        reset_engine_cache()


def test_classic_default_keeps_legacy_state_and_cache_paths(tmp_path):
    try:
        game_context.configure("classic", "mage")
        assert game_context.state_root(tmp_path) == tmp_path / "state"
        assert game_context.v2_state_root(tmp_path) == tmp_path / "state" / "v2"
    finally:
        game_context.configure("classic", "mage")
