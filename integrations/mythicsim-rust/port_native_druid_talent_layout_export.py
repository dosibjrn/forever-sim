#!/usr/bin/env python3
"""Port a read-only typed Druid talent-layout JSON export into MythicSim.

The export serializes the fork's existing FOREVER_TREES data. It does not
decide whether a talent rank or allocation is legal; native prepare remains
the sole authority for those decisions.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PREPARE_MARKER = "NATIVE_DRUID_TALENT_LAYOUT_EXPORT_V1"
LIB_MARKER = "NATIVE_DRUID_TALENT_LAYOUT_LIB_V1"
MAIN_MARKER = "NATIVE_DRUID_TALENT_LAYOUT_COMMAND_V1"


class PortError(RuntimeError):
    pass


def _read(path: Path) -> str:
    if not path.is_file():
        raise PortError(f"required Rust source file is missing: {path}")
    return path.read_text(encoding="utf-8")


def _insert_before(path: Path, anchor: str, block: str, marker: str) -> bool:
    text = _read(path)
    if marker in text:
        return False
    count = text.count(anchor)
    if count != 1:
        raise PortError(
            f"{path}: expected exactly one insertion anchor {anchor!r}; found {count}"
        )
    path.write_text(text.replace(anchor, block + anchor, 1), encoding="utf-8")
    return True


def _insert_after(path: Path, anchor: str, block: str, marker: str) -> bool:
    text = _read(path)
    if marker in text:
        return False
    count = text.count(anchor)
    if count != 1:
        raise PortError(
            f"{path}: expected exactly one insertion anchor {anchor!r}; found {count}"
        )
    path.write_text(text.replace(anchor, anchor + block, 1), encoding="utf-8")
    return True


def _replace_once(path: Path, anchor: str, replacement: str, marker: str) -> bool:
    text = _read(path)
    if marker in text or replacement in text:
        return False
    count = text.count(anchor)
    if count != 1:
        raise PortError(
            f"{path}: expected exactly one replacement anchor {anchor!r}; found {count}"
        )
    path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
    return True


def apply_port(repo_root: Path) -> bool:
    repo_root = Path(repo_root)
    prepare_path = repo_root / "src/classes/druid/prepare.rs"
    lib_path = repo_root / "src/lib.rs"
    main_path = repo_root / "src/main.rs"
    changed = False

    prepare_block = r'''
// NATIVE_DRUID_TALENT_LAYOUT_EXPORT_V1
/// Export the existing native Druid talent layout as read-only metadata.
///
/// This is a wire-layout description for candidate serialization only.
/// Native prepare remains authoritative for every rank and allocation decision.
pub(crate) fn native_talent_layout_json() -> serde_json::Value {
    const TREE_KEYS: [&str; 3] = ["balance", "feral", "restoration"];
    let trees = FOREVER_TREES
        .iter()
        .enumerate()
        .map(|(tree_index, talents)| {
            let entries = talents
                .iter()
                .enumerate()
                .map(|(position, talent)| {
                    serde_json::json!({
                        "position": position,
                        "field": talent.field,
                        "name": talent.name,
                        "max_ranks": talent.max_ranks,
                        "in_proto": talent.in_proto,
                    })
                })
                .collect::<Vec<_>>();
            serde_json::json!({
                "tree_index": tree_index,
                "tree_key": TREE_KEYS[tree_index],
                "talents": entries,
            })
        })
        .collect::<Vec<_>>();
    serde_json::json!({
        "schema_version": 1,
        "class": "druid",
        "trees": trees,
    })
}

'''
    changed |= _insert_before(
        prepare_path,
        "/// Which of Go's three registered Druid specs the player is.\n",
        prepare_block,
        PREPARE_MARKER,
    )

    lib_anchor = (
        "pub use prepare::{\n"
        "    prepare, prepare_json, prepare_json_with, PrepareError, Refusal as PrepareRefusal, Rules,\n"
        "};"
    )
    lib_block = r'''

// NATIVE_DRUID_TALENT_LAYOUT_LIB_V1
/// Return the native Druid talent wire layout and its engine identity.
///
/// This exports existing native metadata only; it does not expose a second
/// talent-legality implementation to callers.
pub fn druid_talent_layout_json() -> serde_json::Value {
    let mut layout = classes::druid::prepare::native_talent_layout_json();
    let object = layout
        .as_object_mut()
        .expect("native Druid talent layout export must be a JSON object");
    object.insert(
        "source_revision".to_string(),
        serde_json::json!(SOURCE_REVISION),
    );
    object.insert(
        "client_build".to_string(),
        serde_json::json!(CLIENT_BUILD),
    );
    layout
}
'''
    changed |= _insert_after(lib_path, lib_anchor, lib_block, LIB_MARKER)

    main_import_anchor = "    contracts::prepared_v2::PreparedV2,"
    main_import_replacement = (
        "    contracts::prepared_v2::PreparedV2,\n"
        "    druid_talent_layout_json,"
    )
    changed |= _replace_once(
        main_path,
        main_import_anchor,
        main_import_replacement,
        "druid_talent_layout_json,",
    )

    help_anchor = r"\nforever-engine version"
    help_replacement = (
        r"\nforever-engine talent-layout --class druid"
        r"\nforever-engine version"
    )
    changed |= _replace_once(
        main_path,
        help_anchor,
        help_replacement,
        "forever-engine talent-layout --class druid",
    )

    command_block = r'''
    // NATIVE_DRUID_TALENT_LAYOUT_COMMAND_V1
    if args[0] == "talent-layout" {
        if args.len() != 3 || args[1] != "--class" {
            return Err("talent-layout requires --class druid".into());
        }
        if args[2] != "druid" {
            return Err(format!("unsupported talent-layout class: {}", args[2]).into());
        }
        let layout = druid_talent_layout_json();
        println!(
            "{}",
            serde_json::to_string_pretty(&layout).map_err(|err| err.to_string())?
        );
        return Ok(());
    }

'''
    changed |= _insert_before(
        main_path,
        '    if args[0] == "native-world-pulls" {\n',
        command_block,
        MAIN_MARKER,
    )

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        changed = apply_port(args.repo_root)
    except PortError as exc:
        print(f"NATIVE_DRUID_TALENT_LAYOUT_PORT_ERROR:{exc}", file=sys.stderr)
        return 1
    print(
        "NATIVE_DRUID_TALENT_LAYOUT_EXPORT_APPLIED"
        if changed
        else "NATIVE_DRUID_TALENT_LAYOUT_EXPORT_ALREADY_PRESENT"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
