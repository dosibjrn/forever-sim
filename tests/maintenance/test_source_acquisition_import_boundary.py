"""Source acquisition state/HTML readers must not load legacy GameIR.

These transitional readers still validate source snapshots; this test only
protects their import boundary while #357/#359 migrate gameplay to native Rust.
"""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_acquisition_state_and_html_readers_remain_source_only():
    source = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import source_acquisition_events as events
from src.game.data.forever.source_acquisition_entities import TYPES, _typed_listview

assert events.DEFAULT_DB is DEFAULT_DB
for module in (
    'src.game.data.forever.sqlite_talents',
    'src.game.data.forever.source_indexed_action_coverage',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert module not in sys.modules, module

state = events.AcquisitionCharacterState(
    class_key='druid', level=20, zone_id=None, copper=42
)
assert state.level == 20 and state.learned_spell_ids == frozenset()
assert events.AcquisitionEvent(method='taught_by_npc', spell_id=101, source_entity_id=22).spell_id == 101

try:
    events.AcquisitionCharacterState(class_key='druid', level=20, zone_id=None, copper=-1)
except ValueError as exc:
    assert str(exc) == 'invalid character copper'
else:
    raise AssertionError('negative character currency accepted')

assert TYPES == {
    'taught_by_npc': ('npc', 'taught-by-npc'),
    'taught_by_item': ('item', 'taught-by-item'),
    'reward_from_quest': ('quest', 'reward-from-q'),
}
html = '<script>new Listview({id:"taught-by-npc",template:"npc",data:[{"id":22,"name":"Trainer"}]});</script>'
assert _typed_listview(html, 'taught-by-npc', 'npc') == [{'id':22,'name':'Trainer'}]
try:
    _typed_listview(html, 'taught-by-npc', 'quest')
except ValueError as exc:
    assert 'template mismatched' in str(exc)
else:
    raise AssertionError('mismatched source relation accepted')

for module in (
    'src.game.data.forever.sqlite_talents',
    'src.game.data.forever.source_indexed_action_coverage',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert module not in sys.modules, module

# Existing explicit consumers still obtain the identical canonical path.
from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DEFAULT_DB
assert LEGACY_DEFAULT_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"source acquisition import boundary failed: {result.stdout}\\n{result.stderr}"
    )
