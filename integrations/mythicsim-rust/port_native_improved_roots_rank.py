#!/usr/bin/env python3
"""Port native Improved Entangling Roots rank intake into selected Rust.

The Forever Balance layout admits the three Roots ranks, but native
Talents::from_message previously discarded them. This preserves the rank
wire intake needed by the native Roots implementation. Retired P1/P2-only
witness injection is not a bootstrap or gate dependency.
"""
from __future__ import annotations

from pathlib import Path
import sys

COMMENT_OLD = """/// The talents the Druid package reads, by the proto's field names. The ones Go leaves
/// unmodelled (Improved Entangling Roots, Overgrowth, Brutal Impact, Feral Charge, Nature's
/// Focus and the healing talents) have no field."""
COMMENT_NEW = """/// The talents the Druid package reads, by the proto's field names. The ones Go leaves
/// unmodelled (Overgrowth, Brutal Impact, Feral Charge, Nature's Focus and the healing
/// talents) have no field. Improved Entangling Roots ranks are parsed but the effect
/// remains unmodelled until native Roots/root-break behavior is implemented."""
FIELD_OLD = """    pub natures_reach: i32,
    pub natures_splendor: bool,"""
FIELD_NEW = """    pub natures_reach: i32,
    pub improved_entangling_roots: i32,
    pub natures_splendor: bool,"""
READ_OLD = """            natures_reach: m.i32("natures_reach"),
            natures_splendor: m.bool("natures_splendor"),"""
READ_NEW = """            natures_reach: m.i32("natures_reach"),
            improved_entangling_roots: m.i32("improved_entangling_roots"),
            natures_splendor: m.bool("natures_splendor"),"""


RUST_TEST = """#[cfg(test)]
mod native_improved_roots_rank_tests {
    use super::Talents;
    use crate::prepare::talent_layout;

    #[test]
    fn native_improved_roots_rank_intake() {
        for rank in 0..=3 {
            let build = format!("000000{rank}");
            let (message, extras) = talent_layout::fill(
                "proto.DruidTalents",
                "druid",
                &build,
                &super::super::FOREVER_TREES,
            )
            .expect("legal Forever Balance Improved Roots rank");
            assert_eq!(
                Talents::from_message(&message, &extras).improved_entangling_roots,
                rank
            );
        }
        assert!(talent_layout::fill(
            "proto.DruidTalents",
            "druid",
            "0000004",
            &super::super::FOREVER_TREES,
        )
        .is_err());
    }
}"""

def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(new) == 1 and source.count(old) == 0:
        return source
    if source.count(old) != 1 or new in source:
        raise ValueError("NATIVE_IMPROVED_ROOTS_" + label + "_SOURCE_DRIFT")
    return source.replace(old, new, 1)


def port_text(source: str) -> str:
    source = replace_once(source, COMMENT_OLD, COMMENT_NEW, "COMMENT")
    source = replace_once(source, FIELD_OLD, FIELD_NEW, "FIELD")
    source = replace_once(source, READ_OLD, READ_NEW, "READ")
    # A previous fork port may already contain the old, larger Rust test
    # module. Preserve that published source unchanged, but do not inject
    # retired P2-only Moonkin/Predatory Strikes witnesses on new ports.
    if "mod native_improved_roots_rank_tests" in source:
        return source
    return source.rstrip() + "\n\n" + RUST_TEST + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_improved_roots_rank.py RUST_ENGINE_ROOT")
    root = Path(argv[1])
    path = root / "src/classes/druid/prepare/talents.rs"
    before = path.read_text()
    after = port_text(before)
    if after != before:
        path.write_text(after)
    print("RUST_IMPROVED_ROOTS_RANK_INTAKE_PORTED" if after != before
          else "RUST_IMPROVED_ROOTS_RANK_INTAKE_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
