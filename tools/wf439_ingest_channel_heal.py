"""Reproducible source-index-backed channel-heal semantic observation ingestion.

Spell/class identifiers are observation data, not executable adapter constants.
The source's after-tooltip and its hash must match the canonical index.
A timing/range or build bridge is never certified by this ingestion.
"""
from __future__ import annotations
import json,sqlite3,hashlib
from pathlib import Path


def ingest(db_path:Path,observations:Path):
    payload=json.loads(Path(observations).read_text())
    records=payload['records']; seen=set()
    with sqlite3.connect(db_path) as conn:
        for fact in records:
            key=(fact['class_key'],int(fact['spell_id']))
            if key in seen:raise ValueError('DUPLICATE_SOURCE_CHANNEL_RECORD')
            seen.add(key)
            row=conn.execute("SELECT name,level_hint,source_url,raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=? AND kind='abilities'",key).fetchone()
            if row is None:raise ValueError('SOURCE_CHANNEL_INDEX_MISSING')
            raw=json.loads(row[3]); tooltip=(raw.get('envChange') or {}).get('after') or {}
            raw_hash=hashlib.sha256(row[3].encode()).hexdigest()
            if (raw_hash!=fact['indexed_payload_sha256'] or
                    row[2]!=fact['source_url'] or row[0]!=fact['family_name'] or
                    row[1]!=fact['min_level'] or
                    tooltip.get('text')!=fact['observed_tooltip'] or
                    fact.get('source_build_verified') is not False or
                    fact.get('party_heal_supported') is not False or
                    fact.get('competing_threat_supported') is not False or
                    fact.get('gcd_assumed') is not True):
                raise ValueError('SOURCE_CHANNEL_OBSERVATION_MISMATCH_OR_UNCERTIFIED_CLAIM')
            known=conn.execute('SELECT semantic_type FROM ability_semantic_source_facts WHERE class_key=? AND spell_id=?',key).fetchone()
            if known and known[0]!='channeled_group_heal':raise ValueError('SOURCE_CHANNEL_CONFLICTING_SEMANTIC')
            conn.execute('''INSERT INTO ability_semantic_source_facts (
                class_key,spell_id,semantic_type,required_mode_id,gcd_s,tick_interval_s,
                spell_power_coefficient,source_url,mechanics_source_url,source_authority,
                capture_id,captured_at,caveats_json,periodic_power_coefficient_per_tick,positional_requirement)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(class_key,spell_id) DO UPDATE SET
                    semantic_type=excluded.semantic_type,
                    required_mode_id=excluded.required_mode_id,
                    gcd_s=excluded.gcd_s,
                    tick_interval_s=excluded.tick_interval_s,
                    spell_power_coefficient=excluded.spell_power_coefficient,
                    source_url=excluded.source_url,
                    mechanics_source_url=excluded.mechanics_source_url,
                    source_authority=excluded.source_authority,
                    capture_id=excluded.capture_id,captured_at=excluded.captured_at,
                    caveats_json=excluded.caveats_json,
                    periodic_power_coefficient_per_tick=excluded.periodic_power_coefficient_per_tick,
                    positional_requirement=excluded.positional_requirement''',(
                fact['class_key'],fact['spell_id'],'channeled_group_heal',fact['required_mode_id'],
                float(fact['gcd_s']),float(fact['tick_interval_s']),0.,fact['source_url'],
                fact['source_url'],'forever_wowhead_source_index_build_unverified',
                fact['capture_id'],fact['observed_at'],json.dumps([
                    {'semantic':'source_version','status':'unverified_for_70338'},
                    {'semantic':'party_healing','status':'player_only_not_party_executed'},
                    {'semantic':'competing_threat','status':'solo_no_threat_competition'},
                    {'semantic':'gcd','status':'assumed_source_bridge_not_verified'}]),0.,None))
        conn.commit()
    return len(records)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--observations',type=Path,required=True)
    a=p.parse_args();print({'ingested':ingest(a.db,a.observations)})
