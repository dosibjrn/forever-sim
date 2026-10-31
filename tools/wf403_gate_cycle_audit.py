"""Audit gate-level red/green/refactor evidence without inventing gate PASS."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from src.game.checkpoint_gate_cycle import validate_gate_ledger, GateCycleError


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path, help="Gate-cycle JSON ledger")
    parser.add_argument("--output",type=Path,help="Optional machine-readable audit output")
    parser.add_argument("--project-root",type=Path,default=Path(__file__).resolve().parents[1],
                        help="Project root for SHA256-checking the referenced evidence bytes")
    args=parser.parse_args()
    try:
        result=validate_gate_ledger(json.loads(args.ledger.read_text(encoding="utf-8")),
                                   project_root=args.project_root)
    except (OSError, json.JSONDecodeError, GateCycleError) as exc:
        result={"status":"BLOCKED","error":str(exc),"checkpoint_accepted":False}
    else:
        result={"status":"PROCESS_COMPLETE" if result["process_evidence_complete"] else "WORK_IN_PROGRESS", **result}
    output=json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(output,encoding="utf-8")
    print(output,end="")
    return 2 if result["status"]=="BLOCKED" else 0


if __name__=="__main__":
    raise SystemExit(main())
