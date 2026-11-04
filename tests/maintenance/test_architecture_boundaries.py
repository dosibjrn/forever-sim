import ast
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _imports(path):
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    tree=ast.parse(source.read_text(encoding='utf-8'))
    out=[]
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            base=n.module or ''
            out.append(base)
            out += [base+'.'+a.name for a in n.names if base]
    return out


def test_fast_compute_core_does_not_depend_on_legacy_persistent_mc_modules():
    forbidden=('src.state_manager','src.optimizer_core','src.pnp_cache')
    compute=[
        'src/v2/expected_engine.py', 'src/v2/analytic_scorer.py',
        'src/v2/local_search.py', 'src/v2/continuity.py', 'src/v2/path_dp.py',
    ]
    offenders={}
    for path in compute:
        bad=[x for x in _imports(path) if x.startswith(forbidden)]
        if bad: offenders[path]=bad
    assert offenders == {}



def _python_files(root):
    files = sorted((ROOT / root).rglob('*.py'))
    assert files, f"Missing or empty architecture boundary: {root}"
    return files


def test_generic_shared_layer_has_no_ruleset_or_class_engine_dependency():
    forbidden=('src.rulesets','src.engines','src.classic_mage_leveling_optimizer_v10')
    offenders={}
    for path in _python_files('src/shared'):
        bad=[x for x in _imports(path) if x.startswith(forbidden)]
        if bad: offenders[str(path)]=bad
    assert offenders == {}


def test_forever_shared_layer_has_no_class_dependency():
    offenders={}
    for path in _python_files('src/rulesets/forever/shared'):
        bad=[x for x in _imports(path) if x.startswith('src.rulesets.forever.classes')]
        if bad: offenders[str(path)]=bad
    assert offenders == {}


def test_forever_classes_do_not_import_sibling_class_backends():
    offenders={}
    base=ROOT / 'src/rulesets/forever/classes'
    for class_dir in (x for x in base.iterdir() if x.is_dir() and not x.name.startswith('__')):
        sibling_prefixes=tuple(
            f'src.rulesets.forever.classes.{other.name}'
            for other in base.iterdir()
            if other.is_dir() and other.name != class_dir.name and not other.name.startswith('__')
        )
        for path in _python_files(class_dir):
            bad=[x for x in _imports(path) if x.startswith(sibling_prefixes)] if sibling_prefixes else []
            if bad: offenders[str(path)]=bad
    assert offenders == {}


def test_architecture_scans_use_the_repository_not_process_cwd(monkeypatch, tmp_path):
    """Do not let an unrelated cwd silently return zero scanned modules."""
    monkeypatch.chdir(tmp_path)
    assert any(p.name == 'events.py' for p in _python_files('src/shared'))
    assert any(p.name == 'mobs.py' for p in _python_files('src/rulesets/forever/shared'))
    assert 'ast' in _imports('tests/maintenance/test_architecture_boundaries.py')


def test_engine_registry_points_at_ruleset_owned_packages_except_frozen_classic_legacy():
    import src.engine_registry as registry
    from src.class_registry import definitions

    # Registry entries are derived from the class definitions, not a second list.
    defined = {(d.ruleset, d.class_name): d.engine_module for d in definitions()}
    assert registry._ENGINE_MODULES == defined
    assert defined[('classic', 'mage')] == 'src.classic_mage_leveling_optimizer_v10'
    # The old ruleset-tree adapter is unused; Classic Mage remains registered
    # directly to its frozen canonical legacy engine module.
    assert not (ROOT / 'src/rulesets/classic').exists()

    for definition in definitions():
        key = (definition.ruleset, definition.class_name)
        if key == ('classic', 'mage'):
            continue
        if definition.engine_module.startswith('src.rulesets.'):
            continue

        # Non-UI generic source proofs have no legacy ruleset facade. These
        # are intentional source-backed proof modules, not hidden class engines.
        assert (
            definition.ruleset == 'forever'
            and definition.proof_only
            and not definition.ui_visible
            and definition.engine_module == f'src.game.data.forever.{definition.class_name}'
        ), f"Unexpected engine location for {definition.key}: {definition.engine_module}"

def test_fast_validator_targets_exist():
    """Fast-suite entries must survive responsibility-based test moves."""
    from tools.validate_fast import TESTS

    root = Path(__file__).resolve().parents[2]
    missing = [
        target for target in TESTS
        if not (root / target.split("::", 1)[0]).is_file()
    ]
    assert missing == [], f"Stale tools/validate_fast.py test paths: {missing}"
    assert len(TESTS) == len(set(TESTS)), "Duplicate fast-suite targets"



# Clean architecture boundary: only the Merge-owned M1 ledger certifies checkpoints.


def test_canonical_m1_ledger_is_only_full_checkpoint_authority(tmp_path):
    """Nine real active gate PASSes certify without a separate identity gate."""
    from tools.m1_progress import FIELDS, GATES, scoreboard

    ledger = tmp_path / 'docs/planning/M1_PASSES.tsv'
    ledger.parent.mkdir(parents=True)
    stamp = '2026-11-03T00:00:00+00:00'
    rows = [
        {'class': 'druid', 'level': '20', 'spec': 'unrestricted',
         'gate': gate, 'passed_at_utc': stamp, 'commit': 'a' * 40,
         'run_url': '', 'compatibility_id': '',
         'status': 'PASS', 'verified': '', 'applicable': '',
         'scope_provisional': '', 'measured_at_utc': stamp}
        for gate in GATES
    ]

    def save():
        with ledger.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter='\t')
            writer.writeheader()
            writer.writerows(rows)

    save()
    accepted = scoreboard(ledger)
    assert accepted['certified_checkpoints'] == 1
    assert accepted['passed_gates'] == len(GATES)

    # Historical metadata may differ; it does not create a tenth gate.
    rows[-1]['compatibility_id'] = 'other-label'
    save()
    assert scoreboard(ledger)['certified_checkpoints'] == 1

    # A genuinely missing gate PASS still prevents checkpoint acceptance.
    rows[-1].update(status='PARTIAL', passed_at_utc='',
                    verified='1', applicable='2', scope_provisional='1')
    save()
    assert scoreboard(ledger)['certified_checkpoints'] == 0
    assert scoreboard(ledger)['passed_gates'] == len(GATES) - 1


def test_registry_metadata_selection_defers_legacy_class_builder_imports(monkeypatch):
    """Presentation/eligibility reads must not instantiate every GameIR provider."""
    from types import SimpleNamespace
    from src.game.data.forever import registry

    imports = []

    def load(module_name, *, package):
        imports.append((module_name, package))
        return SimpleNamespace(
            build_source_slice=lambda level, ability_db_path=None:
            (level, ability_db_path)
        )

    monkeypatch.setattr(registry, "import_module", load)
    assert "druid" in registry.registered_class_keys()
    assert registry.generic_default_ready_levels("druid") == ()
    assert imports == []

    assert registry._PROVIDERS["druid"](20) == (20, None)
    assert registry._PROVIDERS["druid"](30, ability_db_path="stage.sqlite") == (
        30, "stage.sqlite"
    )
    assert imports == [
        (".druid", "src.game.data.forever"),
        (".druid", "src.game.data.forever"),
    ]


def test_registry_lightweight_import_does_not_load_legacy_combat_engine():
    """A fresh source-metadata read must not eagerly import GameIR or its runtime.

    The legacy src.game Evaluation exports remain available when explicitly
    requested, so existing consumers can migrate independently.
    """
    import subprocess
    import sys

    source = """
import sys
from src.game.data.forever.registry import registered_class_keys, generic_default_ready_levels
assert len(registered_class_keys()) == 9
assert generic_default_ready_levels('druid') == ()
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

from src.game import Evaluation, evaluation_from_combat_timeline
assert Evaluation.__name__ == 'Evaluation'
assert callable(evaluation_from_combat_timeline)
assert 'src.game.model.ir' in sys.modules
assert 'src.game.runtime.simulator' in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"registry import / explicit runtime compatibility failed: "
        f"{result.stdout}\n{result.stderr}"
    )



def test_forever_package_import_keeps_source_registry_deferred():
    """Source-only imports avoid legacy GameIR registry; builder API still works."""
    import subprocess
    import sys

    source = """
import sys
import src.game.data.forever as forever
from src.game.data.forever import source_db_scope

assert forever.__all__ == ['build_game_ir_slice']
assert 'src.game.data.forever.registry' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert callable(source_db_scope.ability_source_scope)

from src.game.data.forever import build_game_ir_slice
from src.game.data.forever.registry import build_game_ir_slice as direct
assert build_game_ir_slice is direct
assert 'src.game.data.forever.registry' in sys.modules
assert 'src.game.model.ir' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"Forever source-only import / public builder compatibility failed: "
        f"{result.stdout}\n{result.stderr}"
    )


def test_shared_overlay_import_does_not_load_legacy_game_ir():
    """Shared numeric overlays stay backend-neutral without a GameIR namespace shim."""
    assert not (ROOT / "src/game/model/overlay.py").exists()
    import subprocess
    import sys

    source = """
import sys
from src.shared.field_overlays import FieldOverlay
assert FieldOverlay.__name__ == 'FieldOverlay'
assert not any(name == 'src.game' or name.startswith('src.game.') for name in sys.modules)
import src.game.model as model
assert 'src.game.model.ir' not in sys.modules
from src.game.model import GameIRSlice, ActionDefinition
from src.game.model.ir import GameIRSlice as direct_slice, ActionDefinition as direct_action
assert GameIRSlice is direct_slice
assert ActionDefinition is direct_action
assert model.GameIRSlice is direct_slice
assert {'GameIRSlice', 'ActionDefinition'}.issubset(dir(model))
try:
    model.NotARealModelExport
except AttributeError:
    pass
else:
    raise AssertionError('unknown legacy model export should raise AttributeError')
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"model import boundary / legacy public exports failed: "
        f"{result.stdout}\\n{result.stderr}"
    )

def test_runtime_package_lightweight_events_defer_legacy_simulator():
    """Event-only imports stay independent; public legacy API still resolves."""
    import subprocess
    import sys

    source = """
import sys
import src.game.runtime as runtime
from src.game.runtime.events import CombatEvent, EventQueue
assert 'src.game.runtime.simulator' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert runtime.CombatEvent is CombatEvent
assert runtime.EventQueue is EventQueue
assert 'src.game.runtime.simulator' not in sys.modules
assert 'src.game.model.ir' not in sys.modules

from src.game.runtime import ActorState, TargetState
from src.game.runtime.state import ActorState as StateActor, TargetState as StateTarget
assert ActorState is StateActor and TargetState is StateTarget
assert 'src.game.runtime.simulator' not in sys.modules

from src.game.runtime import CombatRuntime, execute_action
from src.game.runtime.simulator import CombatRuntime as DirectRuntime, execute_action as direct_action
assert CombatRuntime is DirectRuntime and execute_action is direct_action
assert 'src.game.runtime.simulator' in sys.modules
assert 'src.game.model.ir' in sys.modules
assert {'CombatEvent', 'EventQueue', 'ActorState', 'TargetState', 'CombatRuntime'}.issubset(dir(runtime))
try:
    runtime.NotAnExport
except AttributeError:
    pass
else:
    raise AssertionError('unknown runtime export must raise AttributeError')
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"runtime event import / compatibility exports failed: "
        f"{result.stdout}\\n{result.stderr}"
    )

def test_source_target_profile_reads_do_not_import_transitional_game_ir():
    """Profile consumers read sourced values without importing Python game mechanics.

    Explicit legacy enrichment and the historical sqlite_talents.DEFAULT_DB
    import remain compatible until those callers move to selected native Rust.
    """
    import subprocess
    import sys

    source = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever.target_combat_source import (
    DEFAULT_DB as PROFILE_DB, load_target_combat_profile,
    physical_outgoing_expected_factors, source_enrich_target_combat,
)
assert PROFILE_DB is DEFAULT_DB
assert 'src.game.model.ir' not in sys.modules
profile = load_target_combat_profile(20)
factors = physical_outgoing_expected_factors(20)
assert profile['target_armor'] == factors['target_armor']
assert factors['direct_multiplier'] > 0
assert 'src.game.model.ir' not in sys.modules
from src.game.data.forever.sqlite_talents import DEFAULT_DB as HISTORICAL_DB
assert HISTORICAL_DB is DEFAULT_DB
assert 'src.game.model.ir' in sys.modules
assert callable(source_enrich_target_combat)
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"source-profile/GameIR import boundary failed: "
        f"{result.stdout}\\n{result.stderr}"
    )

def test_source_index_metadata_imports_do_not_load_legacy_game_rules():
    """Source-index metadata can be imported without loading legacy game mechanics."""
    import subprocess
    import sys

    source = """
import sys
from types import SimpleNamespace
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever.source_indexed_action_coverage import (
    DEFAULT_DB as INDEX_DB, _source_spell_ids, indexed_ability_coverage,
)
assert INDEX_DB is DEFAULT_DB
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules
action = SimpleNamespace(
    provenance=({'source_spell_id': 123},), metadata={'spell_id': 456},
)
assert _source_spell_ids(action) == {123, 456}
assert callable(indexed_ability_coverage)
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"source-index/GameIR import boundary failed: "
        f"{result.stdout}\\n{result.stderr}"
    )

def test_remaining_source_checkpoint_readers_defer_legacy_game_ir_compiler():
    """Independent source readers must not pull GameIR through DEFAULT_DB.

    Existing legacy audits and spell compilers retain their own explicit
    imports; this only isolates transitional source reads, not game legality.
    """
    import subprocess
    import sys

    source = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever.source_checkpoint_p3_ratings import (
    DEFAULT_DB as RATINGS_DB, displayed_percent_from_raw,
    forever_display_chance_fraction_per_raw_point,
)
from src.game.data.forever.sqlite_rake import (
    DEFAULT_DB as RAKE_DB, load_rake_facts,
)
assert RATINGS_DB is DEFAULT_DB
assert RAKE_DB is DEFAULT_DB
assert callable(load_rake_facts)
assert displayed_percent_from_raw('crit', 14.0) == 1.0
assert forever_display_chance_fraction_per_raw_point('hit') == 0.01 / 10.0
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"source checkpoint/GameIR boundary failed: "
        f"{result.stdout}\\n{result.stderr}"
    )


def test_source_only_ingest_and_maintenance_readers_do_not_import_game_ir():
    """SQLite source-only consumers share one path without loading talent/GameIR.

    Existing legacy sqlite_talents.DEFAULT_DB remains the same public object
    when explicitly requested; this is not a source-legality migration.
    """
    import subprocess
    import sys

    source = """
import json
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import (
    source_ability_repair,
    source_stat_aura_candidates,
    source_maintenance_ranks,
)

for module in (source_ability_repair, source_stat_aura_candidates, source_maintenance_ranks):
    assert module.DEFAULT_DB is DEFAULT_DB
assert callable(source_ability_repair.repair_queue)
assert callable(source_stat_aura_candidates.ingest)
assert callable(source_stat_aura_candidates.read_current_candidates)
assert callable(source_maintenance_ranks.latest_reactive_maintenance_rank)
assert callable(source_maintenance_ranks.latest_stat_maintenance_rank)

record = dict(
    class_key='druid', spell_id=41, batch_id='batch-1',
    name='Sourced Aura', level_hint=20, source_url='https://example.invalid/spell=41',
)
record['raw_listview_json'] = json.dumps({
    'id': 41, 'name': 'Sourced Aura', 'level': 20,
    'envChange': {'after': {
        'name': 'Sourced Aura',
        'text': "Increases the target's Stamina by 5 for 1 hour.",
        'cost': '10 Mana', 'cast': 'Instant', 'cooldown': '',
    }},
})
candidate = source_stat_aura_candidates._extract(record)
assert candidate[:9] == (
    'druid', 41, 'batch-1', 'https://example.invalid/spell=41',
    20, 'stamina', 5.0, 3600.0, 10.0,
)
assert candidate[-1] == 'BLOCKED_ACTOR_PRIMARY_BASELINE_AND_ACQUISITION_UNVERIFIED'
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

from src.game.data.forever.sqlite_talents import DEFAULT_DB as HISTORICAL_DB
assert HISTORICAL_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"Source-only import and legacy compatibility failed: "
        f"{result.stdout}\n{result.stderr}"
    )


def test_index_rank_source_reader_remains_lightweight_without_game_ir():
    """Typed index-only reads do not initialize the transitional talent compiler."""
    import subprocess
    import sys

    druid_source = (ROOT / "src/game/data/forever/druid.py").read_text(encoding="utf-8")
    assert "indexed_rank_identity" not in druid_source

    source = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
import src.game.data.forever.source_index_rank_parity as rank_source
from src.game.data.forever.source_index_rank_parity import (
    DEFAULT_DB as INDEX_DB, IndexedRankParityError,
    indexed_rank_fact, parse_index_after,
)
assert INDEX_DB is DEFAULT_DB
assert callable(indexed_rank_fact)
assert not hasattr(rank_source, "indexed_rank_identity")
parsed = parse_index_after({
    'cost': '30 Mana', 'cast': 'Instant',
    'text': 'Causes 12 to 24 Fire damage to the target.',
}, 'direct_damage')
assert parsed == {
    'kind': 'direct_damage', 'mana': 30.0, 'cast_s': 0.0,
    'low': 12.0, 'high': 24.0, 'school': 'fire',
}
try:
    parse_index_after({
        'cost': 'unverified', 'cast': 'Instant',
        'text': 'Causes 12 to 24 Fire damage to the target.',
    }, 'direct_damage')
except IndexedRankParityError as exc:
    assert str(exc) == 'INDEX_COST_OR_CAST_UNVERIFIED'
else:
    raise AssertionError('malformed source cost must still fail closed')

assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules
from src.game.data.forever.sqlite_talents import DEFAULT_DB as HISTORICAL_DB
assert HISTORICAL_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"indexed rank source/GameIR boundary failed: "
        f"{result.stdout}\n{result.stderr}"
    )


def test_source_slug_helper_is_not_entangled_with_legacy_talent_compiler():
    """Pure source-name normalization must not instantiate Python GameIR."""
    import subprocess
    import sys

    script = """
import sys
from src.shared.identifiers import source_slug
from tools.wf362_stage_warrior30_talents import _slug as stage_slug
assert stage_slug is source_slug
assert source_slug('Cat\\'s Paw') == 'cats_paw'
assert source_slug('  Holy/Fire  ') == 'holy_fire'
assert source_slug('Rank 1') == 'rank_1'
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
from src.game.data.forever.sqlite_talents import _slug as legacy_slug
assert legacy_slug is source_slug
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT,
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + "\\n" + result.stderr

    migrated = [
        "src/game/data/forever/source_ability_semantics.py",
        "src/game/data/forever/source_queued_swing.py",
        "src/game/data/forever/source_enemy_melee_ap_debuff.py",
        "src/game/data/forever/source_rank_overlay.py",
        "src/game/data/forever/source_control_action_compiler.py",
        "tools/wf362_stage_warrior30_talents.py",
        "tools/parse_verified_detail_to_staging.py",
    ]
    for path in migrated:
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "sqlite_talents import" not in source, path
        assert "source_slug as _slug" in source, path


def test_staging_metadata_import_without_legacy_game_ir():
    """Staging metadata can be stripped without eagerly loading game mechanics."""
    import subprocess
    import sys

    source = """
import sys
from types import SimpleNamespace
from src.game.data.forever.source_stage_isolation import strip_precompiled_source_actions

snapshot = SimpleNamespace(actions=(), modes=(), source_facts=())
assert strip_precompiled_source_actions(snapshot) is snapshot
for module in (
    'src.game.talents',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert module not in sys.modules, module
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + "\\n" + result.stderr

def test_generic_talent_frontier_identity_does_not_eagerly_load_game_ir():
    """Native-ready candidate identity must not load legacy Python rules.

    Calling the legacy neighbor evaluator must still use its original
    src.game.talents legality and budget implementation.
    """
    import subprocess
    import sys

    source = """
import sys
from src.game.talent_frontier import Neighbor, allocation_key, source_legal_talent_neighbors

assert allocation_key({'root': 0, 'arcane': 2, 'feral': 1}) == (
    ('arcane', 2), ('feral', 1))
neighbor = Neighbor((('arcane', 2),), 'rank_up', ('arcane',))
assert neighbor.as_dict() == {
    'allocation': {'arcane': 2},
    'operation': 'rank_up',
    'changed_ids': ['arcane'],
}
assert callable(source_legal_talent_neighbors)
assert 'src.game.talents' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

# Legacy consumers still resolve the original legality/budget implementation.
from src.game.talents import available_talent_points, validate_talent_selection
assert available_talent_points(20) > 0
assert callable(validate_talent_selection)
assert 'src.game.model.ir' in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + "\\n" + result.stderr

def test_optimizer_package_has_no_gameplay_or_ruleset_dependencies():
    """The new optimizer boundary must stay independent of game truth."""
    forbidden = (
        "src.game",
        "src.rulesets",
        "src.engines",
        "src.classic_mage_leveling_optimizer_v10",
    )
    offenders = {}
    for path in _python_files("src/optimization"):
        bad = [
            name for name in _imports(path)
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
        ]
        if bad:
            offenders[str(path)] = bad
    assert offenders == {}


def test_empty_classic_shared_ruleset_package_is_not_retained():
    """Do not keep an empty shared namespace under the legacy Classic adapter."""
    assert not (ROOT / "src/rulesets/classic/shared").exists()


def test_no_production_imports_use_retired_game_model_overlay_shim():
    offenders = []
    for root in ("src", "tools", "integrations"):
        for path in _python_files(root):
            if "src.game.model.overlay" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
