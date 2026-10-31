"""Versioned, idempotent source fact for an official Forever talent scope clarification.

This is an ingestion input, not an engine or optimizer talent whitelist.
The rank values themselves are already present in talent_rank_source_facts.
"""
from pathlib import Path
import sqlite3

DB = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'
SOURCE_URL = 'https://worldofwarcraft.blizzard.com/en-us/news/24301515/world-of-warcraft-forever-class-deep-dives-hunter-and-druid'

def ingest(db_path=DB):
    with sqlite3.connect(db_path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS talent_effect_scope_source_facts (
          class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
          scope_kind TEXT NOT NULL, scope_filter TEXT NOT NULL,
          authority TEXT NOT NULL, source_url TEXT NOT NULL,
          evidence_text TEXT NOT NULL, capture_id TEXT NOT NULL,
          PRIMARY KEY(class_key,spell_id,scope_kind))''')
        # Official dated class deep dive explicitly says this talent's hit bonus
        # applies to all damaging spells, not only a guessed school whitelist.
        conn.execute('''INSERT OR REPLACE INTO talent_effect_scope_source_facts
          (class_key,spell_id,scope_kind,scope_filter,authority,source_url,evidence_text,capture_id)
          VALUES(?,?,?,?,?,?,?,?)''', (
          'druid',16819,'spell_hit_bonus','damage_spell',
          'blizzard_dated_forever_class_deep_dive',SOURCE_URL,
          "Nature's Reach now also grants increased hit chance and applies to all your damaging spells.",
          'wf249_official_deep_dive_20261011'))
        conn.commit()

if __name__ == '__main__':
    ingest()
