from pathlib import Path

from src import master_optimizer as mo


def test_checkpoint_ref_supports_attempt_state_outside_project_root(tmp_path: Path):
    cp = tmp_path / "attempt" / "state" / "tracks" / "buy_water" / "checkpoints" / "x.pkl"
    cp.parent.mkdir(parents=True); cp.write_bytes(b"x")
    ref = mo._checkpoint_ref(cp)
    assert Path(ref).is_absolute()
    assert Path(ref) == cp.resolve()
    # Existing resolver contract remains valid for both absolute and legacy refs.
    assert mo.sm.ROOT / ref == cp.resolve()
