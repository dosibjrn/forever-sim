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
    """Eleven compatible live PASS stamps count; incompatible stamps do not."""
    from src.game.checkpoint_acceptance_status import accepted_checkpoint_status
    from tools.m1_progress import FIELDS, GATES

    source = ROOT / 'evidence/wf360/WF360_ACCEPTANCE.json'
    evidence = tmp_path / 'evidence/wf360'
    evidence.mkdir(parents=True)
    (evidence / source.name).write_bytes(source.read_bytes())

    ledger = tmp_path / 'docs/planning/M1_PASSES.tsv'
    ledger.parent.mkdir(parents=True)
    stamp = '2026-11-03T00:00:00+00:00'
    rows = [
        {'class': 'druid', 'level': '20', 'spec': 'unrestricted',
         'gate': gate, 'passed_at_utc': stamp, 'commit': 'a' * 40,
         'run_url': '', 'compatibility_id': 'same-native-scenario-source',
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
    accepted = accepted_checkpoint_status(tmp_path)
    assert accepted['accepted_checkpoints'] == '1/148'
    assert accepted['full_checkpoint_certified'] is True
    assert accepted['legacy_six_gate_accepted_checkpoints'] == '2/148'

    rows[-1]['compatibility_id'] = 'different-source-or-engine'
    save()
    incompatible = accepted_checkpoint_status(tmp_path)
    assert incompatible['accepted_checkpoints'] == '0/148'
    assert incompatible['full_checkpoint_certified'] is False
    assert incompatible['legacy_six_gate_accepted_checkpoints'] == '2/148'
