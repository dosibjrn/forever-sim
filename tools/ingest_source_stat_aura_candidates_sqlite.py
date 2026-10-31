#!/usr/bin/env python3
"""Batch type literal stat auras from all nine canonical source indexes."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.game.data.forever.source_stat_aura_candidates import ingest

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(ingest(args.db),sort_keys=True,indent=2))
