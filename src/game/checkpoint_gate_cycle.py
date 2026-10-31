"""Seven-gate RED -> GREEN -> REFACTOR evidence contract.

A workflow certificate is NOT a substitute for the actual P1..P7 validators.
It verifies that acceptance claims are backed by reproducible gate-level red,
green, genericity review, and post-refactor cross-context evidence. A green
unit test alone cannot promote a checkpoint. No game/class-specific logic.
"""
from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from collections.abc import Mapping

GATES = tuple(f"P{i}" for i in range(1, 8))
PHASES = ("PENDING", "RED", "GREEN", "REFACTOR", "COMPLETE")
HASH = re.compile(r"^[0-9a-f]{64}$")
DISPOSITIONS = frozenset(("GENERALIZED_ENGINE", "MOVED_TO_SOURCE_DATA", "REMOVED_DUPLICATE"))


class GateCycleError(ValueError):
    """Fail-closed evidence validation error."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise GateCycleError(reason)


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(HASH.fullmatch(value))


def _valid_test(record: object, *, outcome: str, criterion: str, prefix: str) -> None:
    _require(isinstance(record, Mapping), f"{prefix}_MISSING")
    _require(record.get("outcome") == outcome, f"{prefix}_OUTCOME_MISMATCH")
    _require(record.get("criterion_id") == criterion, f"{prefix}_CRITERION_MISMATCH")
    _require(isinstance(record.get("test_id"), str) and bool(record["test_id"].strip()),
             f"{prefix}_TEST_ID_MISSING")
    _require(_sha(record.get("evidence_sha256")), f"{prefix}_EVIDENCE_SHA_MISSING")


def validate_cycle(record: Mapping, *, checkpoint: str, source_sha256: str) -> str:
    """Validate one gate's TDD lifecycle; return its evidence phase.

    Red and green must exercise the same named acceptance criterion, while the
    refactor rerun must pass the SAME gate and cross-check another context.
    Unresolved class-specific engine code is a blocker, not an exemption.
    """
    _require(isinstance(record, Mapping), "GATE_RECORD_NOT_OBJECT")
    gate = record.get("gate")
    _require(gate in GATES, "UNKNOWN_GATE")
    phase = record.get("phase")
    _require(phase in PHASES, f"{gate}_INVALID_PHASE")
    _require(record.get("checkpoint") == checkpoint, f"{gate}_CHECKPOINT_MISMATCH")
    _require(record.get("source_sha256") == source_sha256, f"{gate}_SOURCE_CHANGED")
    criterion = record.get("criterion_id")
    _require(isinstance(criterion, str) and criterion.startswith(gate + "_"),
             f"{gate}_MISSING_GATE_CRITERION")
    if phase == "PENDING":
        _require(not any(record.get(k) for k in ("red", "green", "refactor")),
                 f"{gate}_PENDING_HAS_EVIDENCE")
        return phase

    _valid_test(record.get("red"), outcome="FAIL", criterion=criterion,
                prefix=f"{gate}_RED")
    if phase == "RED":
        _require(not record.get("green") and not record.get("refactor"),
                 f"{gate}_RED_PREMATURE_PROMOTION")
        return phase

    green = record.get("green")
    _valid_test(green, outcome="PASS", criterion=criterion, prefix=f"{gate}_GREEN")
    _require(green.get("test_id") == record["red"]["test_id"],
             f"{gate}_RED_GREEN_DIFFERENT_ACCEPTANCE_TEST")
    _require(isinstance(green.get("gate_certificate_ref"), str)
             and bool(green["gate_certificate_ref"].strip()),
             f"{gate}_GREEN_MISSING_GATE_VALIDATOR_CERTIFICATE")
    if phase == "GREEN":
        _require(not record.get("refactor"), f"{gate}_GREEN_PREMATURE_REFACTOR")
        return phase

    refactor = record.get("refactor")
    _require(isinstance(refactor, Mapping), f"{gate}_REFACTOR_REVIEW_MISSING")
    _require(refactor.get("genericity_reviewed") is True,
             f"{gate}_REFACTOR_NOT_REVIEWED")
    changes = refactor.get("class_specific_changes")
    _require(isinstance(changes, list), f"{gate}_MISSING_CLASS_SPECIFIC_AUDIT")
    for change in changes:
        _require(isinstance(change, Mapping) and bool(change.get("file")),
                 f"{gate}_UNTRACKED_CLASS_SPECIFIC_CHANGE")
        _require(change.get("disposition") in DISPOSITIONS,
                 f"{gate}_UNRESOLVED_CLASS_SPECIFIC_ENGINE_LOGIC")
        _require(isinstance(change.get("rationale"), str) and bool(change["rationale"].strip()),
                 f"{gate}_MISSING_GENERICITY_RATIONALE")
    if phase == "REFACTOR":
        return phase

    _require(refactor.get("post_refactor_gate_status") == "PASS",
             f"{gate}_POST_REFACTOR_GATE_NOT_PASS")
    _require(refactor.get("criterion_id") == criterion,
             f"{gate}_REFACTOR_CHANGED_ACCEPTANCE_CRITERION")
    _require(_sha(refactor.get("post_refactor_evidence_sha256")),
             f"{gate}_POST_REFACTOR_EVIDENCE_MISSING")
    cross = refactor.get("cross_context_regressions")
    _require(isinstance(cross, list) and len(cross) > 0,
             f"{gate}_NO_CROSS_CONTEXT_REGRESSIONS")
    for witness in cross:
        _require(isinstance(witness, Mapping) and witness.get("checkpoint") != checkpoint
                 and bool(witness.get("checkpoint")),
                 f"{gate}_INVALID_CROSS_CONTEXT")
        _require(witness.get("status") == "PASS"
                 and _sha(witness.get("evidence_sha256")),
                 f"{gate}_CROSS_CONTEXT_REGRESSION_UNPROVEN")
    return phase


def validate_gate_ledger(ledger: Mapping, *, project_root: Path | None = None) -> dict:
    """Audit completeness of gate process, not gameplay truth.

    Even 7/7 COMPLETE does not imply actual checkpoint acceptance: each gate's
    own semantic verifier, source-catalogue authority and runtime parity must
    separately establish that. No gate or evidence may disappear silently.
    """
    _require(isinstance(ledger, Mapping), "LEDGER_NOT_OBJECT")
    checkpoint = ledger.get("checkpoint")
    source = ledger.get("source_sha256")
    _require(isinstance(checkpoint, str) and checkpoint.count(":") >= 2,
             "INVALID_CHECKPOINT_IDENTITY")
    _require(_sha(source), "INVALID_SOURCE_SHA256")
    records = ledger.get("gates")
    _require(isinstance(records, list), "GATES_NOT_ARRAY")
    by_gate: dict[str, str] = {}
    for record in records:
        gate = record.get("gate") if isinstance(record, Mapping) else None
        _require(gate not in by_gate, "DUPLICATE_GATE")
        phase = validate_cycle(record, checkpoint=checkpoint, source_sha256=source)
        by_gate[gate] = phase
    missing = [gate for gate in GATES if gate not in by_gate]
    incomplete = [gate for gate in GATES if by_gate.get(gate) != "COMPLETE"]
    integrity = _verify_ledger_files(records, Path(project_root)) if project_root is not None else False
    return {
        "checkpoint": checkpoint,
        "evidence_sha256_verified": integrity,
        "cycle_structure_complete": not incomplete,
        "process_contract": "P1_P7_GATE_LEVEL_RED_GREEN_REFACTOR_V1",
        "gate_phases": {gate: by_gate.get(gate, "MISSING") for gate in GATES},
        "missing_gates": missing,
        "incomplete_gates": incomplete,
        "process_evidence_complete": not incomplete and integrity,
        "checkpoint_accepted": False,
        "acceptance_requires": "SEPARATE_P1_P7_SEMANTIC_CERTIFICATES",
    }


def _verify_ledger_files(records: list, project_root: Path) -> bool:
    """Hash the actual referenced evidence files; no fabricated SHA certificates.

    All started gates require on-disk RED logs. Finished GREEN and REFACTOR
    stages also require on-disk witness files. Paths must remain under root.
    """
    root = project_root.resolve()

    def check(record: Mapping, *, file_key: str, digest_key: str, gate: str) -> None:
        rel = record.get(file_key)
        _require(isinstance(rel, str) and bool(rel.strip()), f"{gate}_EVIDENCE_FILE_MISSING")
        path = (root / rel).resolve()
        _require(path.is_relative_to(root), f"{gate}_EVIDENCE_PATH_ESCAPES_PROJECT")
        _require(path.is_file(), f"{gate}_EVIDENCE_FILE_NOT_FOUND")
        actual=sha256(path.read_bytes()).hexdigest()
        _require(actual == record.get(digest_key), f"{gate}_EVIDENCE_BYTES_SHA_MISMATCH")

    for cycle in records:
        phase = cycle["phase"]
        gate = cycle["gate"]
        if phase == "PENDING": continue
        check(cycle["red"], file_key="evidence_file", digest_key="evidence_sha256",gate=f"{gate}_RED")
        if phase == "RED": continue
        check(cycle["green"], file_key="evidence_file", digest_key="evidence_sha256",gate=f"{gate}_GREEN")
        if phase != "COMPLETE": continue
        review = cycle["refactor"]
        check(review, file_key="post_refactor_evidence_file",digest_key="post_refactor_evidence_sha256",gate=f"{gate}_REFACTOR")
        for witness in review["cross_context_regressions"]:
            check(witness,file_key="evidence_file",digest_key="evidence_sha256",gate=f"{gate}_CROSS_CONTEXT")
    return True
