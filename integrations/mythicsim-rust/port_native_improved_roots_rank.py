#!/usr/bin/env python3
"""Port native Improved Roots rank intake and native Druid P2 witnesses.

The Forever Balance layout admits the three Roots ranks, but native
Talents::from_message previously discarded them. This preserves that rank and
adds selected-source preparation witnesses for two P2 effects already present
in Rust: Moonkin Form and Predatory Strikes. Roots damage/root-break behavior
and the P2 gate's native adapter remain unimplemented; these witnesses alone
do not award P1/P2 acceptance.
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

P2_NATIVE_TESTS = r"""
    #[test]
    fn native_improved_roots_rank_intake_predatory_strikes_behavior() {
        let fixture = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/classes/druid/prepare/cat.request.json");
        let original: serde_json::Value = serde_json::from_slice(
            &std::fs::read(fixture).expect("read Feral Cat request fixture"),
        )
        .expect("parse Feral Cat request fixture");

        let attack_power = |rank: i32| {
            // The first 15 points satisfy Predatory Strikes' tier requirement:
            // Ferocity 5 + Furor 5 + Feral Swiftness 2 + Feral Instinct 3.
            let build = format!("-5523000000{rank}-");
            let (message, extras) = talent_layout::fill(
                "proto.DruidTalents",
                "druid",
                &build,
                &super::super::FOREVER_TREES,
            )
            .expect("legal Forever Feral Predatory Strikes rank");
            assert_eq!(
                Talents::from_message(&message, &extras).predatory_strikes,
                rank
            );

            let mut request = original.clone();
            request["raid"]["parties"][0]["players"][0]["talentsString"] =
                serde_json::Value::String(build);
            let prepared = crate::prepare_json(
                &serde_json::to_vec(&request).expect("serialize Feral Cat request"),
                "native-p2-predatory-strikes",
            )
            .expect("selected Rust prepares the Feral Cat actor");
            prepared["player"]["stats"]["AttackPower"]
                .as_f64()
                .expect("native Feral Cat AttackPower")
        };

        let base = attack_power(0);
        for rank in 1..=3 {
            let actual = attack_power(rank);
            let expected = crate::prepare::spelldata::Ladder::talent(16972, 3)
                .effect_at(1)
                .fraction_at(rank)
                * f64::from(crate::prepare::character::constants::CHARACTER_LEVEL);
            assert!(expected > 0.0, "source-backed rank {rank} has a positive effect");
            assert!(
                (actual - base - expected).abs() < 1e-9,
                "Predatory Strikes rank {rank} must add its selected-source AP: base={base}, actual={actual}, expected_delta={expected}"
            );
        }
    }

    #[test]
    fn native_improved_roots_rank_intake_moonkin_form_behavior() {
        let fixture = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/classes/druid/prepare/balance.request.json");
        let original: serde_json::Value = serde_json::from_slice(
            &std::fs::read(fixture).expect("read Balance request fixture"),
        )
        .expect("parse Balance request fixture");

        let prepare = |rank: i32| {
            // 30 prior Balance points satisfy Moonkin Form's tier requirement;
            // the last digit is the Moonkin Form rank.
            let build = format!("553222311510000{rank}");
            let (message, extras) = talent_layout::fill(
                "proto.DruidTalents",
                "druid",
                &build,
                &super::super::FOREVER_TREES,
            )
            .expect("legal Forever Balance Moonkin Form rank");
            assert_eq!(
                Talents::from_message(&message, &extras).moonkin_form,
                rank == 1
            );

            let mut request = original.clone();
            request["raid"]["parties"][0]["players"][0]["talentsString"] =
                serde_json::Value::String(build);
            crate::prepare_json(
                &serde_json::to_vec(&request).expect("serialize Balance request"),
                "native-p2-moonkin-form",
            )
            .expect("selected Rust prepares the Balance actor")
        };

        let without = prepare(0);
        let with = prepare(1);
        let has_aura = |prepared: &serde_json::Value| {
            prepared["player"]["auras"]
                .as_array()
                .expect("native player auras")
                .iter()
                .any(|aura| aura["label"] == "Moonkin Form")
        };
        let has_spell = |prepared: &serde_json::Value| {
            prepared["player"]["spells"]
                .as_array()
                .expect("native player spellbook")
                .iter()
                .any(|spell| spell["action_id"]["spell_id"] == 24858)
        };
        assert!(!has_aura(&without), "rank 0 must not register Moonkin Form aura");
        assert!(has_aura(&with), "rank 1 must register Moonkin Form aura");
        assert!(!has_spell(&without), "rank 0 must not register Moonkin Form spell");
        assert!(has_spell(&with), "rank 1 must register Moonkin Form spell");
    }"""
RUST_TEST_EXTENDED = RUST_TEST.replace("\n}", P2_NATIVE_TESTS + "\n}", 1)


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
    if RUST_TEST_EXTENDED in source:
        return source
    if RUST_TEST in source:
        return source.replace(RUST_TEST, RUST_TEST_EXTENDED, 1)
    if "mod native_improved_roots_rank_tests" in source:
        raise ValueError("NATIVE_IMPROVED_ROOTS_TEST_SOURCE_DRIFT")
    return source.rstrip() + "\n\n" + RUST_TEST_EXTENDED + "\n"


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
