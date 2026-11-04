#!/usr/bin/env python3
"""Import queued-swing and control observations into the selected source DB."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from src.game.data.forever.source_queued_swing import ingest as ingest_queued
from tools.wf321_ingest_control_observations import ingest as ingest_control


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--db',required=True,type=Path)
    p.add_argument('--queued',action='append',default=[],type=Path)
    p.add_argument('--control',action='append',default=[],type=Path)
    a=p.parse_args()
    if not (a.queued or a.control):
        p.error('specify at least one queued or control observation file')
    if not a.db.is_file():p.error('--db does not exist')
    for src in a.queued:
        ingest_queued(a.db,src)
        print('INGESTED queued',src)
    for src in a.control:
        ingest_control(a.db,src)
        print('INGESTED control',src)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
