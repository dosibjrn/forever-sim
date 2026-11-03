"""Selected talent-tree row ingestion regression for optimizer source inputs."""
from pathlib import Path
import json
import sqlite3

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.ingest_talent_tree_rows_sqlite import ingest

SOURCE = Path(__file__).resolve().parents[1] / 'evidence/wf482_druid_tree_rows_20261017.json'

def test_all_eight_rows_are_canonical_sqlite_facts_after_ingest(tmp_path):
    output=tmp_path/'talents.sqlite'
    output.write_bytes(Path(DEFAULT_DB).read_bytes())
    with sqlite3.connect(output) as db:
        # Re-enact actual missing-row state, including on a reconstructed baseline.
        db.execute("DELETE FROM talent_tree_row_facts WHERE class_key='druid' AND spell_id IN (16958,16850,17123,5570,17007,24858,16972,16909)")
    first=ingest(output,SOURCE)
    assert first['imported']==8
    second=ingest(output,SOURCE)
    assert second['imported']==8
    with sqlite3.connect(output) as db:
        rows=db.execute("SELECT s.name,t.tree_row,t.tree_col,t.authority,t.source_url "
          "FROM talent_tree_row_facts t JOIN spell_index s ON s.spell_id=t.spell_id "
          "WHERE t.class_key='druid' AND s.class_key='druid' AND s.kind='talents' "
          "AND t.capture_id='wf482-druid-remaining-tree-rows-2026-10-17'").fetchall()
    assert len(rows)==8
    expected={x['name']:x['row'] for x in json.loads(SOURCE.read_text())['facts']}
    assert {name:row for name,row,*_ in rows}==expected
    assert all(col is None and authority=='secondary_provisional_row'
               and url=='https://talentsforever.com/druid/talents'
               for _,_,col,authority,url in rows)
