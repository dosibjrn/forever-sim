from types import SimpleNamespace

from src.rulesets.forever.items import runtime_selection as rs


def test_available_items_plain_dict_cache_avoids_reopening_sqlite(monkeypatch, tmp_path):
    db = tmp_path / "items.sqlite"
    db.write_bytes(b"stub")
    opens = {"n": 0}

    class FakeCatalogue:
        def __init__(self, path):
            opens["n"] += 1
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def eligible_items(self, *, class_id, level):
            return []

    monkeypatch.setattr(rs, "catalogue_path", lambda: db)
    monkeypatch.setattr(rs, "ItemCatalogue", FakeCatalogue)
    rs.clear_runtime_item_cache()

    assert rs.available_items("druid", 20) == ()
    assert rs.available_items("druid", 20) == ()
    assert opens["n"] == 1

    rs.clear_runtime_item_cache()
    assert rs.available_items("druid", 20) == ()
    assert opens["n"] == 2


def test_effective_level_plain_dict_cache_avoids_reopening_sqlite(monkeypatch, tmp_path):
    db = tmp_path / "items.sqlite"
    db.write_bytes(b"stub")
    opens = {"n": 0}

    class FakeCatalogue:
        def __init__(self, path):
            opens["n"] += 1
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def effective_required_level(self, item):
            return 17

    monkeypatch.setattr(rs, "catalogue_path", lambda: db)
    monkeypatch.setattr(rs, "ItemCatalogue", FakeCatalogue)
    rs.clear_runtime_item_cache()
    item = SimpleNamespace(item_id=12345, required_level=10)

    assert rs.effective_level(item) == 17
    assert rs.effective_level(item) == 17
    assert opens["n"] == 1

    rs.clear_runtime_item_cache()
    assert rs.effective_level(item) == 17
    assert opens["n"] == 2
