import ast
from pathlib import Path


def _imports(path):
    tree=ast.parse(Path(path).read_text(encoding='utf-8'))
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
    return sorted(Path(root).rglob('*.py'))


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
    base=Path('src/rulesets/forever/classes')
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


def test_engine_registry_points_at_ruleset_owned_packages_except_frozen_classic_legacy():
    import src.engine_registry as registry
    assert registry._ENGINE_MODULES
    assert registry._ENGINE_MODULES[('classic','mage')] == 'src.classic_mage_leveling_optimizer_v10'
    assert all(
        module.startswith('src.rulesets.')
        for key,module in registry._ENGINE_MODULES.items()
        if key != ('classic','mage')
    )
