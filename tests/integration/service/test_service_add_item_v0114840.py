from __future__ import annotations

import json
import shutil
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from src.rulesets.forever.items.catalogue import ItemCatalogue
from src.rulesets.forever.items.wowhead_detail import parse_wowhead_detail_page
from src.service import http_api
from src.service.http_api import OptimizerHTTPServer
from src.service.item_operations import add_item, parse_item_input
from src.service.store import QueueStore


HTML = '''<!doctype html><html><head><title>Acolyte's Silvered Chain Helm - Item - Forever - Wowhead</title></head><body>
<div>Item Level 25</div><div>Head Mail</div><div>163 Armor</div><div>+9 Stamina</div><div>Requires Level 20</div>
<div>Equip: Increases healing done by up to 20 and damage done by up to 6 for all magical spells and effects.</div>
</body></html>'''


def test_item_input_accepts_id_and_forever_url():
    assert parse_item_input('250531')[0] == 250531
    assert parse_item_input('https://www.wowhead.com/forever/item=250531/acolytes-silvered-chain-helm')[0] == 250531
    with pytest.raises(ValueError):
        parse_item_input('https://example.com/item=250531')


def test_detail_parser_reads_visible_tooltip_stats():
    item=parse_wowhead_detail_page(item_id=250531,raw_html=HTML)
    assert item.name == "Acolyte's Silvered Chain Helm"
    assert item.item_level == 25 and item.required_level == 20
    assert item.slot == 'head' and item.armor == 163
    assert item.stats['stamina'] == 9
    assert item.stats['healing'] == 20
    assert item.stats['spell_power'] == 6


def test_point_add_upserts_exact_item_and_selected_class(tmp_path: Path):
    src=Path('data/forever/catalogue/items_2026-09-29.sqlite')
    db=tmp_path/'items.sqlite'; shutil.copy2(src,db)
    result=add_item(
        'https://www.wowhead.com/forever/item=250531/acolytes-silvered-chain-helm',
        class_name='paladin', catalogue_file=db,
        html_fetcher=lambda item_id,url: HTML,
    )
    assert result.status == 'verified'
    assert result.item_id == 250531 and result.class_id == 2
    assert result.effective_required_level >= 20
    assert 'paladin' in result.eligible_classes
    assert result.affected_ranges['paladin'] == (result.effective_required_level, 60)
    assert result.affected_from_level == result.effective_required_level and result.affected_to_level == 60
    with ItemCatalogue(db) as c:
        item=c.get_item(250531)
        assert item is not None
        assert item.fetch_status == 'verified'
        assert item.source_type == 'wowhead_detail'
        assert item.healing == 20 and item.spell_power == 6
        assert c._conn.execute('select 1 from item_class_eligibility where item_id=? and class_id=2',(250531,)).fetchone()


def test_service_endpoint_is_item_operation_not_optimizer_job(monkeypatch, tmp_path: Path):
    class Fake:
        def as_dict(self): return {'item_id':250531,'name':'Acolyte','status':'verified'}
    monkeypatch.setattr(http_api,'add_item',lambda value,class_name=None: Fake())
    store=QueueStore(tmp_path/'q.sqlite3')
    srv=OptimizerHTTPServer(('127.0.0.1',0),store)
    t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
    try:
        conn=HTTPConnection('127.0.0.1',srv.server_address[1],timeout=3)
        raw=json.dumps({'item':'250531','class_name':'paladin'})
        conn.request('POST','/api/v1/items/add',body=raw,headers={'Content-Type':'application/json'})
        res=conn.getresponse(); payload=json.loads(res.read()); conn.close()
        assert res.status == 200 and payload['item_id'] == 250531
        assert store.list_jobs() == []
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)


def test_point_add_preserves_and_reports_all_known_class_eligibility(tmp_path: Path):
    src=Path('data/forever/catalogue/items_2026-09-29.sqlite')
    db=tmp_path/'items.sqlite'; shutil.copy2(src,db)
    with ItemCatalogue(db) as c:
        # Seed another known eligibility exactly as a prior bulk refresh would.
        if c.get_item(250531) is None:
            from src.rulesets.forever.items.catalogue import ItemRecord
            c.upsert_item(ItemRecord(item_id=250531,name='cached',slot='head',item_level=25,required_level=20))
        c.add_class_eligibility(250531,11,'bulk_refresh:test')
    result=add_item('250531',class_name='paladin',catalogue_file=db,html_fetcher=lambda *_: HTML)
    assert result.eligible_classes == ('druid','paladin')
    assert result.affected_ranges['druid'] == (result.effective_required_level,60)
    assert result.affected_ranges['paladin'] == (result.effective_required_level,60)


def test_point_add_rolls_back_item_and_eligibility_together(monkeypatch, tmp_path: Path):
    src=Path('data/forever/catalogue/items_2026-09-29.sqlite')
    db=tmp_path/'items.sqlite'; shutil.copy2(src,db)
    before=None
    with ItemCatalogue(db) as c:
        before=c.get_item(250531)
    original=ItemCatalogue.add_class_eligibility
    def boom(self,*args,**kwargs):
        raise RuntimeError('eligibility write failed')
    monkeypatch.setattr(ItemCatalogue,'add_class_eligibility',boom)
    with pytest.raises(RuntimeError,match='eligibility write failed'):
        add_item('250531',class_name='paladin',catalogue_file=db,html_fetcher=lambda *_: HTML)
    monkeypatch.setattr(ItemCatalogue,'add_class_eligibility',original)
    with ItemCatalogue(db) as c:
        after=c.get_item(250531)
        assert (after.canonical_dict() if after else None) == (before.canonical_dict() if before else None)
