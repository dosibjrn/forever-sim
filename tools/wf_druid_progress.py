#!/usr/bin/env python3
"""Print a fail-closed L20/L30 × P1-P7 scoreboard from identical machine gate checks.

No hand-reviewed PASS and no unnecessary 30/300-second rerun. Cached evidence
must come from source/engine/scenario-identical executions; missing evidence FAILs.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
import sys

from wf_gate import main as gate_main, GATES, ROOT


def main(argv=None):
    a=argparse.ArgumentParser(description='Druid L20 and L30 P1-P7 repeatable gate scoreboard')
    a.add_argument('--evidence-dir', type=Path, default=ROOT/'gate_evidence')
    a.add_argument('--refresh-p2-source-audit',action='store_true')
    a.add_argument('--json',action='store_true',help='Print all detail as JSON')
    args=a.parse_args(argv)
    entries=[]
    for level in (20,30):
        cli=['--class','druid','--level',str(level),'--gate','all',
             '--evidence-dir',str(args.evidence_dir)]
        if args.refresh_p2_source_audit:
            cli.append('--refresh-p2-source-audit')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            ret=gate_main(cli)
        data=json.loads(out.getvalue())
        for item in data['results']:
            entries.append({'level':level,'gate':item['gate'], 'status':item['status'],
                            'reason':';'.join(item['reasons']),
                            'evidence_file':item.get('evidence_file')})
    status = 'PASS' if all(e['status']=='PASS' for e in entries) else 'FAIL'
    if args.json:
        print(json.dumps({'class':'druid','levels':[20,30],'status':status,
                          'results':entries},ensure_ascii=False,indent=2))
    else:
        print('Druid L20/L30 P1-P7 — machine-checked evidence')
        for e in entries:
            print(f"L{e['level']:02d} {e['gate']}: {e['status']} | {e['reason']}")
        print('Accepted: '+str(sum(all(x['status']=='PASS' for x in entries if x['level']==lv)
                                    for lv in (20,30)))+'/2; global unchanged 0/148')
    return 0 if status=='PASS' else 1

if __name__=='__main__':
    sys.exit(main())
