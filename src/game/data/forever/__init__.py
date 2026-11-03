"""Compatibility export for the transitional Forever source IR builder.

Source-only package and submodule imports must not load the legacy GameIR
registry. Resolve the existing public builder only when a caller requests it;
the registry remains live until its production consumers move to native Rust.
"""

__all__ = ["build_game_ir_slice"]


def __getattr__(name: str):
    if name == "build_game_ir_slice":
        from .registry import build_game_ir_slice
        return build_game_ir_slice
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
