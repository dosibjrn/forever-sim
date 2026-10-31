import json

from src import master_optimizer as master
from src import state_manager as sm
from src import listener


def _patch_state_root(monkeypatch, tmp_path):
    state=tmp_path/'state'
    monkeypatch.setattr(sm,'STATE',state)
    monkeypatch.setattr(sm,'RUNTIME',state/'runtime')
    monkeypatch.setattr(sm,'LOGS',state/'logs')
    monkeypatch.setattr(sm,'IMPORTS',state/'imports')
    monkeypatch.setattr(sm,'TRACKS',state/'tracks')
    monkeypatch.setattr(sm,'BEST',state/'best')
    monkeypatch.setattr(sm,'CANDIDATES',state/'best'/'candidates')
    monkeypatch.setattr(sm,'CHECKPOINTS',state/'checkpoints')
    monkeypatch.setattr(sm,'HISTORY',state/'history')
    monkeypatch.setattr(sm,'SEEDS',state/'seeds')
    monkeypatch.setattr(sm,'USER_CONFIG',state/'config.json')
    sm._SEED_SUMMARY_CACHE.clear(); sm._SEED_FILE_SUMMARY_CACHE.clear()
    listener._SEED_CACHE.clear()
    sm.ensure_dirs()
    return state


def _seed(path, level, policy):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'level':level,'mode':'test','candidates':[{
        'policy':policy,'allocation':'','normalized_min_per_100':1.0,
    }]}),encoding='utf-8')


def test_per_level_seed_banks_are_school_scoped(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch,tmp_path)
    all_dir=sm.school_seed_dir('buy_water','all')
    frost_dir=sm.school_seed_dir('buy_water','frost')
    assert all_dir != frost_dir
    assert all_dir == sm.track_paths('buy_water').seeds  # backward-compatible all-school path

    _seed(all_dir/'lvl_20.json',20,'FBa')
    _seed(frost_dir/'lvl_20.json',20,'FBo')
    assert json.loads((all_dir/'lvl_20.json').read_text())['candidates'][0]['policy']=='FBa'
    assert json.loads((frost_dir/'lvl_20.json').read_text())['candidates'][0]['policy']=='FBo'


def test_listener_switch_frost_then_all_reads_correct_level_bank(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch,tmp_path)
    _seed(sm.school_seed_dir('buy_water','all')/'lvl_20.json',20,'FBa')
    _seed(sm.school_seed_dir('buy_water','frost')/'lvl_20.json',20,'FBo')
    sm.RUNTIME.mkdir(parents=True,exist_ok=True)

    (sm.RUNTIME/'status.json').write_text(json.dumps({'school':'frost'}),encoding='utf-8')
    assert listener.seed_bank(20,'buy_water')['candidates'][0]['policy']=='FBo'

    (sm.RUNTIME/'status.json').write_text(json.dumps({'school':'all'}),encoding='utf-8')
    assert listener.seed_bank(20,'buy_water')['candidates'][0]['policy']=='FBa'


def test_talent_marginal_priors_are_school_scoped(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch,tmp_path)
    assert sm.talent_marginal_stats_path('buy_water','all') != sm.talent_marginal_stats_path('buy_water','frost')
    sm.update_talent_marginal_stats([{'talent':'imp_frostbolt','rank':1,'level':11,
                                      'delta_active_dps':1.0,'delta_min_per_100':-1.0}],
                                    'buy_water','frost')
    assert sm.load_talent_marginal_stats('buy_water','frost')['talents']
    assert not sm.load_talent_marginal_stats('buy_water','all')['talents']


def test_controller_keeps_all_and_frost_progress_independent(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch,tmp_path)
    legacy={
        'version':3,'next_water_mode':'conjured_water',
        'tracks':{
            'buy_water':{'epoch':7,'tier':3,'no_improve_epochs':1,'current_experiment':None,'experiments':[]},
            'conjured_water':master._new_track_controller(),
        },
    }
    sm.RUNTIME.mkdir(parents=True,exist_ok=True)
    (sm.RUNTIME/'controller.json').write_text(json.dumps(legacy),encoding='utf-8')
    c=master.load_controller()
    assert c['version']==4
    assert master.controller_track(c,'buy_water','all')['epoch']==7
    assert master.controller_track(c,'buy_water','frost')['epoch']==0
    master.controller_track(c,'buy_water','frost')['epoch']=4
    assert master.controller_track(c,'buy_water','all')['epoch']==7
    assert master.choose_water_mode(c,'both','all')=='conjured_water'
    assert master.choose_water_mode(c,'both','frost')=='buy_water'

def test_v3_frost_last_writer_is_quarantined_from_all_school(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch,tmp_path)
    shared=sm.school_seed_dir('buy_water','all')
    _seed(shared/'lvl_20.json',20,'FBo')
    (shared/'memory').mkdir(parents=True,exist_ok=True)
    _seed(shared/'memory'/'lvl_20.json',20,'FBo')
    sm.talent_marginal_stats_path('buy_water','all').write_text(json.dumps({'version':1,'talents':{'x':{}}}),encoding='utf-8')
    frost_exp={'id':'buy_frost_exp_00000_tier0','epoch':0,'tier':0,'status':'completed',
               'school':'frost','water_mode':'buy_water','started_at':10.0,'completed_at':20.0,
               'improved_best':False}
    old={'version':3,'next_water_mode':'buy_water','tracks':{
        'buy_water':{'epoch':1,'tier':0,'no_improve_epochs':1,'current_experiment':None,'experiments':[frost_exp]},
        'conjured_water':master._new_track_controller(),
    }}
    (sm.RUNTIME/'controller.json').write_text(json.dumps(old),encoding='utf-8')

    c=master.load_controller()
    assert master.controller_track(c,'buy_water','all')['epoch']==0
    assert master.controller_track(c,'buy_water','frost')['epoch']==1
    assert not (sm.school_seed_dir('buy_water','all')/'lvl_20.json').exists()
    assert (sm.school_seed_dir('buy_water','frost')/'lvl_20.json').exists()
    assert (sm.school_seed_dir('buy_water','frost')/'memory'/'lvl_20.json').exists()
    assert not sm.talent_marginal_stats_path('buy_water','all').exists()
    assert sm.talent_marginal_stats_path('buy_water','frost').exists()
