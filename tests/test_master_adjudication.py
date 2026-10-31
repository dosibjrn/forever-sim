from types import SimpleNamespace

from src import master_optimizer as master


def _args(**kw):
    base = dict(path_race_start_mobs=100, path_race_max_mobs=800,
                path_race_top=12, path_race_alpha=0.05)
    base.update(kw)
    return SimpleNamespace(**base)


def test_fixed_replay_is_provisional_when_adaptive_race_enabled():
    card = {'validated_hours': 40.0, 'validation_mobs': 100,
            'validation_mode': 'fixed_policy_replay_xp_weighted_pnp', 'sim_code_hash': 'h'}
    out = master.prepare_fixed_candidate_for_authority(card, _args())
    assert out['validated_hours'] is None
    assert out['fixed_replay_hours'] == 40.0


def test_fixed_replay_remains_authoritative_when_race_explicitly_disabled():
    card = {'validated_hours': 40.0, 'validation_mobs': 100,
            'validation_mode': 'fixed_policy_replay_xp_weighted_pnp', 'sim_code_hash': 'h'}
    out = master.prepare_fixed_candidate_for_authority(card, _args(path_race_max_mobs=0))
    assert out['validated_hours'] == 40.0


def test_master_race_gate_delegates_to_adjudication_with_cached_config(monkeypatch):
    seen = {}
    def fake(mode, cfg, **kwargs):
        seen['mode'] = mode; seen['cfg'] = cfg; seen['kwargs'] = kwargs
        return 'result'
    monkeypatch.setattr(master.mc_adjudication, 'adjudicate_state_candidates', fake)
    out = master.run_adaptive_race_gate('conjured_water', _args(path_race_start_mobs=50, path_race_max_mobs=400), checkpoint='cp')
    assert out == 'result'
    assert seen['mode'] == 'conjured_water'
    assert seen['cfg'].use_best_water is False
    assert seen['kwargs']['start_mobs'] == 50
    assert seen['kwargs']['max_mobs'] == 400
    assert seen['kwargs']['checkpoint'] == 'cp'


def test_master_arg_parser_defaults_are_stable():
    parser = master.build_arg_parser()
    args = parser.parse_args([])
    assert args.path_race_start_mobs == 100
    assert args.path_race_max_mobs == 800
    assert args.path_race_top == 12
    assert args.path_race_alpha == 0.05
    assert args.water_mode == 'both'
    assert args.import_state_dir == []


def test_master_arg_parser_accepts_repeatable_imports_and_disables_race():
    parser = master.build_arg_parser()
    args = parser.parse_args(['--path-race-max-mobs','0', '--import-state-dir','a', '--import-state-dir','b', '--once'])
    assert args.path_race_max_mobs == 0
    assert args.import_state_dir == ['a','b']
    assert args.once is True


def test_initialize_persistent_state_has_one_testable_startup_boundary(monkeypatch):
    calls=[]
    monkeypatch.setattr(master.sm, 'WATER_MODES', ['buy_water','conjured_water'])
    monkeypatch.setattr(master.sm, 'ensure_dirs', lambda: calls.append(('ensure_dirs',)))
    monkeypatch.setattr(master.sm, 'migrate_legacy_buy_water_state', lambda: calls.append(('migrate_legacy',)))
    monkeypatch.setattr(master.sm, 'import_state_priors', lambda paths: calls.append(('import_priors',tuple(paths))) or {'seed_dirs':['s'], 'respec_schedules':[[22]]})
    monkeypatch.setattr(master.sm, 'seed_baseline_if_needed', lambda m: calls.append(('seed',m)))
    monkeypatch.setattr(master.sm, 'migrate_adaptive_validation_authority', lambda m: calls.append(('authority',m)))
    monkeypatch.setattr(master, 'import_legacy_to_gui', lambda k: calls.append(('legacy_gui',k)))
    monkeypatch.setattr(master.sm, 'publish_viewer_snapshot', lambda m: calls.append(('viewer',m)))
    monkeypatch.setattr(master, 'load_controller', lambda: {'controller':1})
    monkeypatch.setattr(master, 'atomic_controller', lambda c: calls.append(('controller',c['controller'])))
    args=_args(import_state_dir=['old'], top_k=7)
    out=master.initialize_persistent_state(args)
    assert out.controller == {'controller':1}
    assert out.imported_seed_dirs == ['s']
    assert out.imported_respec_schedules == [[22]]
    assert calls[:3] == [('ensure_dirs',),('migrate_legacy',),('import_priors',('old',))]
    assert ('authority','buy_water') in calls and ('authority','conjured_water') in calls
    assert calls[-1] == ('controller',1)


def test_candidate_hours_for_log_uses_authoritative_validated_hours_when_present():
    assert master.candidate_hours_for_log({'validated_hours': 40.125}) == '40.125000 h'


def test_candidate_hours_for_log_uses_provisional_fixed_replay_when_adaptive_race_strips_validation():
    card = {'validated_hours': 40.125, 'validation_mobs': 100,
            'validation_mode': 'fixed_policy_replay_xp_weighted_pnp', 'sim_code_hash': 'h'}
    provisional = master.prepare_fixed_candidate_for_authority(card, _args())
    assert provisional['validated_hours'] is None
    assert master.candidate_hours_for_log(provisional) == '40.125000 h provisional-fixed-replay'
    assert master.candidate_hours_value(provisional) == 40.125


def test_candidate_hours_for_log_handles_missing_score_without_crashing():
    assert master.candidate_hours_for_log({'validated_hours': None}) == 'pending-adjudication'
    assert master.candidate_hours_value({'validated_hours': None}, 123.0) == 123.0

def test_master_arg_parser_accepts_primary_school_filter():
    parser = master.build_arg_parser()
    args = parser.parse_args(['--school','frost'])
    assert args.school == 'frost'


def test_master_arg_parser_accepts_frost_shortcut():
    parser = master.build_arg_parser()
    args = parser.parse_args(['--frost'])
    assert args.school == 'frost'


def test_master_arg_parser_rejects_frost_and_conflicting_school():
    parser = master.build_arg_parser()
    import pytest
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(['--frost','--school','fire'])
    assert exc.value.code == 2



def test_signal_stop_handler_is_idempotent_and_does_not_print(monkeypatch):
    # Regression for repeated SIGTERM re-entering buffered stdout while the old
    # handler itself was printing.  The handler must only set the event.
    master.STOP.clear()
    def forbidden(*a, **k):
        raise AssertionError('signal handler must not perform buffered I/O')
    monkeypatch.setattr('builtins.print', forbidden)
    master.request_stop_from_signal(15, None)
    master.request_stop_from_signal(15, None)
    assert master.STOP.is_set()
    master.STOP.clear()


def test_prepare_startup_replay_states_dedupes_after_state_reconstruction(monkeypatch):
    replay_a=[{'level':11,'allocation':'imp_frostbolt=2','action':'start','rotation':'FBo'}]
    replay_b=[{'level':11,'allocation':'imp_frostbolt=2','action':'point','detail':'imp_frostbolt','rotation':'FBo'}]
    # Isolate the post-reconstruction dedupe contract: two historical encodings
    # normalize to the same canonical replay/state.
    st=SimpleNamespace()
    monkeypatch.setattr(master.opt,'outer_state_from_replay',lambda replay,cumulative_hours_hint=None: st)
    monkeypatch.setattr(master.opt,'replay_state',lambda state: replay_a)
    monkeypatch.setattr(master.sm,'candidate_path_id_from_replay',lambda replay:'same-canonical-path')
    states,kept,skipped=master.prepare_startup_replay_states([
        {'id':'a','replay':replay_a,'search_hours':1.0},
        {'id':'b','replay':replay_b,'search_hours':2.0},
    ])
    assert states == [st]
    assert [c['id'] for c in kept] == ['a']
    assert [c['id'] for c,_e in skipped] == ['b']
    assert 'duplicate canonical startup path' in str(skipped[0][1])
