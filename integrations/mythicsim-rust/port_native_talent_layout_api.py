#!/usr/bin/env python3
"""Port a versioned native Druid talent-layout metadata API.

The API exposes the selected Rust layout for wire serialization only. It does
not return a legality verdict or duplicate any Warcraft rule in Forever.
"""
from __future__ import annotations

from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(new) == 1:
        return source
    if source.count(old) != 1 or new in source:
        raise ValueError("NATIVE_TALENT_LAYOUT_" + label + "_SOURCE_DRIFT")
    return source.replace(old, new, 1)


PREP_OLD = """pub(crate) const FOREVER_TREES: [&[LayoutTalent]; 3] =
    [FOREVER_BALANCE, FOREVER_FERAL_COMBAT, FOREVER_RESTORATION];"""
PREP_NEW = PREP_OLD + """

/// Versioned metadata for clients that must serialize the native Forever tree
/// layout. This is not a candidate-legality or rank-validation API.
pub(crate) fn forever_talent_layout_json() -> serde_json::Value {
    let names = ["balance", "feral", "restoration"];
    let trees = names
        .iter()
        .zip(FOREVER_TREES.iter())
        .map(|(key, talents)| {
            let entries = talents
                .iter()
                .map(|talent| {
                    serde_json::json!({
                        "field": talent.field,
                        "name": talent.name,
                        "max_ranks": talent.max_ranks,
                        "in_proto": talent.in_proto,
                    })
                })
                .collect::<Vec<_>>();
            serde_json::json!({"key": key, "talents": entries})
        })
        .collect::<Vec<_>>();
    serde_json::json!({
        "schema_version": 1,
        "class": "druid",
        "ruleset": "forever",
        "trees": trees,
    })
}
"""

LIB_OLD = 'pub const SOURCE_REVISION: &str = env!("FOREVER_REFERENCE_REVISION");'
LIB_NEW = LIB_OLD + """

/// Return native Druid talent-layout metadata for wire serialization only.
pub fn forever_druid_talent_layout() -> serde_json::Value {
    classes::druid::prepare::forever_talent_layout_json()
}

#[cfg(test)]
mod druid_talent_layout_api_tests {
    #[test]
    fn exports_a_lossless_versioned_layout_projection() {
        let value = crate::forever_druid_talent_layout();
        assert_eq!(value["schema_version"].as_u64(), Some(1));
        assert_eq!(value["class"].as_str(), Some("druid"));
        assert_eq!(value["ruleset"].as_str(), Some("forever"));

        let trees = value["trees"].as_array().expect("layout trees");
        assert_eq!(trees.len(), crate::classes::druid::prepare::FOREVER_TREES.len());
        let keys = trees
            .iter()
            .map(|tree| tree["key"].as_str().expect("tree key"))
            .collect::<Vec<_>>();
        assert_eq!(keys, vec!["balance", "feral", "restoration"]);

        for (tree, source_tree) in trees
            .iter()
            .zip(crate::classes::druid::prepare::FOREVER_TREES.iter())
        {
            let entries = tree["talents"].as_array().expect("talent metadata");
            assert_eq!(entries.len(), source_tree.len());
            for (entry, source) in entries.iter().zip(source_tree.iter()) {
                assert_eq!(entry["field"].as_str(), Some(source.field));
                assert_eq!(entry["name"].as_str(), Some(source.name));
                assert_eq!(entry["max_ranks"].as_u64(), Some(u64::from(source.max_ranks)));
                assert_eq!(entry["in_proto"].as_bool(), Some(source.in_proto));
            }
        }
    }
}
"""

MAIN_IMPORT_OLD = "contracts::prepared_v2::PreparedV2, native_two_pull_windows,"
MAIN_IMPORT_NEW = "contracts::prepared_v2::PreparedV2, forever_druid_talent_layout, native_two_pull_windows,"
MAIN_DISPATCH_OLD = '    if args.is_empty() || args == ["--help"] {'
MAIN_DISPATCH_NEW = '''    if args.first().is_some_and(|arg| arg == "talent-layout") {
        if args == ["talent-layout", "--class", "druid"] {
            println!("{}", forever_druid_talent_layout());
            return Ok(());
        }
        return Err("talent-layout requires exactly --class druid".into());
    }
    if args.is_empty() || args == ["--help"] {'''
MAIN_HELP_OLD = 'forever-engine version");'
MAIN_HELP_NEW = 'forever-engine talent-layout --class druid\\nforever-engine version");'

PREP_PATCHES = [(PREP_OLD, PREP_NEW, "PREP_EXPORT")]
LIB_PATCHES = [(LIB_OLD, LIB_NEW, "LIB_EXPORT")]
MAIN_PATCHES = [
    (MAIN_IMPORT_OLD, MAIN_IMPORT_NEW, "MAIN_IMPORT"),
    (MAIN_DISPATCH_OLD, MAIN_DISPATCH_NEW, "MAIN_DISPATCH"),
    (MAIN_HELP_OLD, MAIN_HELP_NEW, "MAIN_HELP"),
]
PATH_PATCHES = {
    "src/classes/druid/prepare.rs": PREP_PATCHES,
    "src/lib.rs": LIB_PATCHES,
    "src/main.rs": MAIN_PATCHES,
}
PATHS = tuple(PATH_PATCHES)


def port_text(path: str, source: str) -> str:
    patches = PATH_PATCHES.get(path)
    if patches is None:
        raise ValueError("NATIVE_TALENT_LAYOUT_UNKNOWN_PATH:" + path)
    for old, new, label in patches:
        source = replace_once(source, old, new, label)
    return source


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: port_native_talent_layout_api.py ENGINE_ROOT", file=sys.stderr)
        return 2
    root = Path(args[0])
    changed = []
    for relative in PATHS:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError("NATIVE_TALENT_LAYOUT_SOURCE_MISSING:" + str(path))
        before = path.read_text(encoding="utf-8")
        after = port_text(relative, before)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed.append(relative)
    suffix = ",".join(changed) if changed else "already-present"
    print("NATIVE_TALENT_LAYOUT_API_PORT_OK:" + suffix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
