#!/usr/bin/env python3
"""Batch materialize sourced, partial effect atoms in canonical-derivative stage.

Does not fetch, legalize, promote or execute any unsupported spell.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

# Direct CLI execution starts with tools/ on sys.path, not the repository root.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json

from src.game.data.forever.source_effect_atoms import ingest

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(ingest(a.db),sort_keys=True,indent=2))
