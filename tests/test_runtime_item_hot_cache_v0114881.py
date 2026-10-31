from types import SimpleNamespace

from src.rulesets.forever.items import runtime_selection as rs


class _CountingPath:
    def __init__(self, name, counters):
        self.name=name; self.counters=counters
    def __str__(self):
        return self.name
    def exists(self):
        self.counters['exists'] += 1
        return True


def test_effective_level_cache_hit_does_not_touch_filesystem(monkeypatch):
    counters={'exists':0,'opens':0}
    path=_CountingPath('/tmp/a.sqlite', counters)

    class FakeCatalogue:
        def __init__(self, p): counters['opens'] += 1
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def effective_required_level(self, item): return 17

    monkeypatch.setattr(rs, 'catalogue_path', lambda: path)
    monkeypatch.setattr(rs, 'ItemCatalogue', FakeCatalogue)
    rs.clear_runtime_item_cache()
    item=SimpleNamespace(item_id=12345, required_level=10)

    assert rs.effective_level(item) == 17
    first_exists=counters['exists']
    assert first_exists >= 1
    assert rs.effective_level(item) == 17
    assert counters['exists'] == first_exists
    assert counters['opens'] == 1


def test_item_vector_cache_is_invalidated_when_catalogue_path_changes(monkeypatch):
    counters={'exists':0}
    current=[_CountingPath('/tmp/a.sqlite', counters)]
    monkeypatch.setattr(rs, 'catalogue_path', lambda: current[0])
    rs.clear_runtime_item_cache()

    # available_items establishes the active catalogue identity; avoid SQLite.
    monkeypatch.setattr(rs, 'CLASS_IDS', {})
    rs.available_items('druid', 20)
    a=SimpleNamespace(item_id=7, strength=1, agility=0, stamina=0, intellect=0,
                      spirit=0, attack_power=0, spell_power=0, extra_stats={}, healing=0,
                      mp5=0, armor=0, bonus_armor=0, weapon_dps=0, weapon_type='')
    assert rs.item_vector(a)['strength'] == 1

    # Same item id under a different catalogue must not reuse the old vector.
    current[0]=_CountingPath('/tmp/b.sqlite', counters)
    rs.available_items('druid', 20)
    b=SimpleNamespace(**{**a.__dict__, 'strength': 9})
    assert rs.item_vector(b)['strength'] == 9
