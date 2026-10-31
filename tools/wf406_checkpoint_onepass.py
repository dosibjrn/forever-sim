"""Cheap, fail-closed P1-P7 checkpoint preflight for one or all 148 identities.

This does NOT turn old evidence into gate success or run 30/300s discovery on
an unverified source universe. Run from the repository root with PYTHONPATH=.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from src.game.checkpoint_onepass import all_checkpoint_identities, run_preflight
from src.rulesets.forever.items.runtime_selection import _DEFAULT_DB


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    pick=ap.add_mutually_exclusive_group(required=True)
    pick.add_argument('--checkpoint')
    pick.add_argument('--all',action='store_true')
    ap.add_argument('--item-db',type=Path,default=_DEFAULT_DB)
    ap.add_argument('--certificate-dir',type=Path,default=Path('evidence/checkpoint_certificates'))
    ap.add_argument('--output',type=Path)
    a=ap.parse_args()
    names=all_checkpoint_identities() if a.all else (a.checkpoint,)
    results=[run_preflight(name,item_db=a.item_db,certificate_dir=a.certificate_dir/name.replace(':','__')) for name in names]
    output={'schema':'wf406-checkpoint-preflight-v1','total':len(results),
            'accepted_count':sum(x['accepted'] for x in results),
            'source_attested_count':sum(x['source_item_verified'] for x in results),
            'cases':results}
    s=json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(s)
    print(s)
    return 0 if all(x['accepted'] for x in results) else 2

if __name__=='__main__':
    raise SystemExit(main())
