#!/usr/bin/env python3
"""Import source-identified enemy melee-AP debuff observations into SQLite.

Run after WF470's available-observations ingestion; no SQLite binary is shipped.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from src.game.data.forever.source_enemy_melee_ap_debuff import ingest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,default=Path('data/forever/catalogue/forever_abilities.sqlite'))
    parser.add_argument('--observations',type=Path,default=Path('evidence/wf471_enemy_melee_ap_debuff_source.json'))
    args=parser.parse_args()
    ingest(args.db,args.observations)
    print('INGESTED sourced enemy melee AP facts from',args.observations)

if __name__=='__main__': main()
