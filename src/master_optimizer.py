#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src import optimizer_core as opt
from src.engine_registry import eng
from src import game_context
from src import mc_adjudication
from src import pnp_cache
from src import state_manager as sm
from src.forever_build import configure as configure_forever_build, metadata as forever_build_metadata

STOP = threading.Event()

class ReconfigureRequested(Exception):
    pass



def request_stop_from_signal(signum=None, frame=None):
    """Async-signal-safe-ish stop request: never perform buffered I/O here.

    Python may re-enter a signal handler while stdout/stderr is already inside a
    buffered write.  Printing from the handler can then raise ``RuntimeError:
    reentrant call inside <_io.BufferedWriter>``.  The normal control flow/
    heartbeat owns user-visible stop reporting after the event flag is set.
    """
    STOP.set()


def adaptive_race_enabled(args) -> bool:
    try:
        return int(args.path_race_max_mobs) >= max(2, int(args.path_race_start_mobs))
    except Exception:
        return False


def prepare_fixed_candidate_for_authority(card: dict, args) -> dict:
    return (mc_adjudication.provisionalize_fixed_validation(card)
            if adaptive_race_enabled(args) else card)


def candidate_hours_for_log(card: dict) -> str:
    """Human-readable score that is safe for provisional adaptive-race candidates.

    Fixed-policy replay candidates are deliberately stripped of authoritative
    ``validated_hours`` while adaptive whole-path adjudication is enabled.  The
    replay result remains available as ``fixed_replay_hours`` and is useful for
    progress logging, but must be labelled provisional.
    """
    validated = card.get('validated_hours')
    if validated is not None:
        return f'{float(validated):.6f} h'
    fixed = card.get('fixed_replay_hours')
    if fixed is not None:
        return f'{float(fixed):.6f} h provisional-fixed-replay'
    return 'pending-adjudication'


def candidate_hours_value(card: dict, default=float('inf')):
    """Numeric replay/validated score for ordering provisional candidates."""
    validated = card.get('validated_hours')
    if validated is not None:
        return float(validated)
    fixed = card.get('fixed_replay_hours')
    if fixed is not None:
        return float(fixed)
    return default


def prepare_startup_replay_states(priors):
    """Parse and canonical-dedupe persisted startup replay candidates.

    Stored replay rows can be textually different yet normalize to the exact
    same legal OuterState (notably legacy level-11 two-point prefixes).  Dedupe
    *after* reconstruction so startup validation never spends a 100m slot twice
    on the same canonical path.
    """
    states=[]; kept=[]; skipped=[]; seen=set()
    for c in priors:
        try:
            hint = c.get('validated_hours') if c.get('validated_hours') is not None else c.get('search_hours')
            st = opt.outer_state_from_replay(c.get('replay') or [], cumulative_hours_hint=hint)
            canonical_replay=opt.replay_state(st)
            pid=sm.candidate_path_id_from_replay(canonical_replay)
        except Exception as e:
            skipped.append((c,e)); continue
        if pid in seen:
            skipped.append((c,ValueError('duplicate canonical startup path'))); continue
        seen.add(pid); states.append(st); kept.append(c)
    return states,kept,skipped


def run_adaptive_race_gate(water_mode: str, args, checkpoint=None):
    if not adaptive_race_enabled(args):
        return None
    cfg = eng.SimConfig(
        use_best_water=(water_mode == 'buy_water'), seed=9001, root_break_mode='scaled'
    )
    return mc_adjudication.adjudicate_state_candidates(
        water_mode, cfg,
        start_mobs=int(args.path_race_start_mobs),
        max_mobs=int(args.path_race_max_mobs),
        growth=2, alpha=float(args.path_race_alpha),
        max_candidates=int(args.path_race_top),
        school=getattr(args,'school','all'),
        checkpoint=checkpoint,
    )


def configure_console():
    """Make Windows/Git-Bash logging unable to crash on policy glyphs."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


def console_safe(value):
    return (str(value)
            .replace("≤", "<=").replace("≥", ">=")
            .replace("→", "->").replace("×", "x")
            .replace("·", "|").replace("—", "-"))



def repair_challenger_if_needed(st, validated, water_mode: str, validation_mobs: int, school: str = 'all'):
    """Run the deterministic lvl59 one-point sanity gate before BEST promotion."""
    if int(validation_mobs) < 100 or not validated:
        return st, validated, None
    incumbent=sm.current_best_meta(water_mode,school).get('best_validated_hours')
    hours=validated.get('validated_hours')
    if hours is None or (incumbent is not None and float(hours) >= float(incumbent)-1e-12):
        return st, validated, None
    rst,rval,samples,info=opt.repair_terminal_point(
        st,validated,n=int(validation_mobs),use_best_water=(water_mode=='buy_water'))
    if samples:
        sm.update_talent_marginal_stats(samples,water_mode,school)
    return rst,rval,info


def now_text():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def atomic_controller(controller: dict):
    sm.atomic_write_json(sm.RUNTIME / 'controller.json', controller)


def _new_track_controller():
    return {
        'epoch': 0, 'tier': 0, 'no_improve_epochs': 0,
        'current_experiment': None, 'experiments': [],
    }

def _ensure_school_tracks(controller: dict, school: str) -> dict:
    school=eng.normalize_primary_school(school)
    if school=='all':
        tracks=controller.setdefault('tracks', {})
    else:
        by=controller.setdefault('tracks_by_school', {})
        tracks=by.setdefault(school, {})
    for mode in sm.WATER_MODES:
        tracks.setdefault(mode, _new_track_controller())
    return tracks


def controller_track(controller: dict, mode: str, school: str='all') -> dict:
    return _ensure_school_tracks(controller,school)[sm.normalize_water_mode(mode)]


def _exp_school(exp: dict | None) -> str:
    try:
        return eng.normalize_primary_school((exp or {}).get('school','all'))
    except Exception:
        return 'all'


def _track_from_v3_school(old_track: dict, school: str) -> dict:
    """Recover one school's controller history from the old shared v3 track."""
    school=eng.normalize_primary_school(school)
    exps=[dict(e) for e in (old_track.get('experiments') or []) if _exp_school(e)==school]
    cur=old_track.get('current_experiment')
    cur=dict(cur) if cur and _exp_school(cur)==school else None
    # Pre-school controllers have no school-tagged history. Preserve their
    # aggregate counters as all-school state for backwards compatibility.
    any_tagged=any('school' in e for e in (old_track.get('experiments') or [])) or bool((old_track.get('current_experiment') or {}).get('school'))
    if school=='all' and not any_tagged:
        out=_new_track_controller(); out.update({
            'epoch':int(old_track.get('epoch',0)), 'tier':int(old_track.get('tier',0)),
            'no_improve_epochs':int(old_track.get('no_improve_epochs',0)),
            'current_experiment':old_track.get('current_experiment'),
            'experiments':list(old_track.get('experiments') or [])[-100:],
        }); return out
    if not exps and cur is None:
        return _new_track_controller()
    completed=[e for e in exps if e.get('status')=='completed']
    epoch=max([int(e.get('epoch',0))+1 for e in completed] + ([int(cur.get('epoch',0))] if cur else [0]))
    tier=max([int(e.get('tier',0)) for e in exps] + ([int(cur.get('tier',0))] if cur else [0]))
    # Reconstruct only the trailing plateau counter for this school. Two misses
    # would already have expanded tier and reset it in the old controller.
    misses=0
    for e in reversed(completed):
        if e.get('improved_best'): break
        misses+=1
        if misses>=2: misses=0; break
    return {'epoch':epoch,'tier':tier,'no_improve_epochs':misses,
            'current_experiment':cur,'experiments':exps[-100:]}


def _latest_v3_writer_school(old_track: dict) -> str:
    rows=list(old_track.get('experiments') or [])
    cur=old_track.get('current_experiment')
    if cur: rows.append(cur)
    if not rows: return 'all'
    def when(e):
        return float(e.get('completed_at') or e.get('started_at') or e.get('epoch') or 0)
    return _exp_school(max(rows,key=when))


def _migrate_shared_seed_bank_from_v3(mode: str, school: str) -> None:
    """Quarantine the last constrained writer out of the legacy all-school bank.

    v0.8.4-v0.9.1 stored Frost-only level banks in the same directory as
    all-school. If the most recent v3 experiment was constrained, the shared
    files are that constrained run's output, not valid all-school incumbents.
    """
    school=eng.normalize_primary_school(school)
    if school=='all': return
    src=sm.school_seed_dir(mode,'all'); dst=sm.school_seed_dir(mode,school)
    dst.mkdir(parents=True,exist_ok=True)
    for fp in list(src.glob('lvl_*.json')):
        try: shutil.move(str(fp), str(dst/fp.name))
        except OSError: pass
    mem=src/'memory'; dmem=dst/'memory'
    if mem.exists():
        dmem.mkdir(parents=True,exist_ok=True)
        for fp in list(mem.glob('lvl_*.json')):
            try: shutil.move(str(fp), str(dmem/fp.name))
            except OSError: pass
    # The marginal prior was produced by the same constrained search.
    old=sm.talent_marginal_stats_path(mode,'all'); new=sm.talent_marginal_stats_path(mode,school)
    if old.exists() and not new.exists():
        try: shutil.move(str(old),str(new))
        except OSError: pass


def _checkpoint_ref(path: Path) -> str:
    """Serialize a checkpoint path for controller/status state.

    Legacy/local runs keep compact project-relative paths. Service attempts may
    place WOW_SIM_STATE_BASE outside the repository, in which case an absolute
    path is required. ``sm.ROOT / absolute_path`` remains the correct resolver
    for both representations.
    """
    p = Path(path)
    try:
        return str(p.relative_to(sm.ROOT))
    except ValueError:
        return str(p.resolve())


def load_controller() -> dict:
    p = sm.RUNTIME / 'controller.json'
    old = {}
    if p.exists():
        try: old = json.loads(p.read_text(encoding='utf-8'))
        except Exception: old = {}
    if old.get('version', 0) >= 4 and isinstance(old.get('tracks'), dict):
        old.setdefault('tracks_by_school', {})
        old.setdefault('next_water_mode_by_school', {})
        _ensure_school_tracks(old,'all')
        for school in ('frost','fire','arcane'):
            if school in old['tracks_by_school']:
                _ensure_school_tracks(old,school)
        old.setdefault('next_water_mode', 'buy_water')
        return old

    if old.get('version', 0) >= 3 and isinstance(old.get('tracks'), dict):
        # v3 mixed all schools into one controller and one per-level seed bank.
        # Recover tagged experiment history per school and quarantine the most
        # recent constrained writer's bank before the first v4 search starts.
        legacy_tracks={m:dict(old['tracks'].get(m) or _new_track_controller()) for m in sm.WATER_MODES}
        for mode,tr in legacy_tracks.items():
            _migrate_shared_seed_bank_from_v3(mode,_latest_v3_writer_school(tr))
        all_tracks={m:_track_from_v3_school(legacy_tracks[m],'all') for m in sm.WATER_MODES}
        by={}
        for school in ('frost','fire','arcane'):
            scoped={m:_track_from_v3_school(legacy_tracks[m],school) for m in sm.WATER_MODES}
            if any(t.get('epoch') or t.get('current_experiment') or t.get('experiments') for t in scoped.values()):
                by[school]=scoped
        return {
            'version':4,'created_at':old.get('created_at',time.time()),
            'next_water_mode':old.get('next_water_mode','buy_water'),
            'next_water_mode_by_school':{}, 'tracks':all_tracks, 'tracks_by_school':by,
        }

    # v1/v2 was exclusively best-available-water and unconstrained school.
    buy = _new_track_controller()
    buy.update({
        'epoch': int(old.get('epoch', 0)), 'tier': int(old.get('tier', 0)),
        'no_improve_epochs': int(old.get('no_improve_epochs', 0)),
        'current_experiment': old.get('current_experiment'),
        'experiments': old.get('experiments', [])[-100:],
    })
    if buy['current_experiment']:
        buy['current_experiment'].setdefault('water_mode', 'buy_water')
    next_mode = 'conjured_water' if buy['epoch'] or buy['experiments'] else 'buy_water'
    return {
        'version': 4, 'created_at': old.get('created_at', time.time()),
        'next_water_mode': next_mode, 'next_water_mode_by_school': {},
        'tracks': {'buy_water': buy, 'conjured_water': _new_track_controller()},
        'tracks_by_school': {},
    }

def choose_water_mode(controller: dict, requested: str = 'both', school: str='all') -> str:
    if requested in sm.WATER_MODES:
        return requested
    school=eng.normalize_primary_school(school)
    tracks=_ensure_school_tracks(controller,school)
    for mode in sm.WATER_MODES:
        exp = tracks[mode].get('current_experiment')
        if exp and exp.get('status') != 'completed':
            return mode
    if school=='all':
        nxt=controller.get('next_water_mode','buy_water')
    else:
        nxt=controller.setdefault('next_water_mode_by_school',{}).get(school,'buy_water')
    return sm.normalize_water_mode(nxt)

def config_for(epoch: int, tier: int, test_mode: bool = False, water_mode: str = 'buy_water', max_respecs: int = 2) -> dict:
    if test_mode:
        return {
            'start_level': 11, 'end_level': 13,
            'snapshot_width': 8, 'snapshot_mobs': 1,
            'beam': 6, 'score_mobs': 1,
            'dest_cheap_mobs': 1, 'dest_refine_mobs': 1, 'dest_k': 4,
            'max_respecs': int(max_respecs), 'seed': 47 + epoch * 101 + (500003 if water_mode == 'conjured_water' else 0),
            'exploration_frac': 0.20,
        }

    width_scale = 2 ** (tier // 2)
    ladder = (1,2,4,8,16,32,64,100)
    return {
        'start_level': 11,
        'end_level': 60,
        'snapshot_width': min(256, 32 * width_scale),
        'snapshot_mobs': 1,  # per-level mapper owns its full PnP ladder
        'beam': min(192, 28 * width_scale),
        'score_mobs': ladder[min(7, 2 + tier // 2)],
        'dest_cheap_mobs': ladder[min(7, 1 + tier // 3)],
        'dest_refine_mobs': ladder[min(7, 3 + tier // 2)],
        'dest_k': min(96, 12 + tier * 8),
        'max_respecs': int(max_respecs),
        'seed': 47 + epoch * 104729 + tier * 1009 + (50000017 if water_mode == 'conjured_water' else 0),
        'exploration_frac': min(0.60, 0.15 + tier * 0.06),
    }


def scored_start_level(data: dict) -> int | None:
    layers = data.get('outer_layers') or {}
    states = [s for vals in layers.values() for s in vals]
    if not states:
        return None
    st = min(states, key=lambda s: s.cumulative_s)
    scored = [ev.level for ev in st.events if ev.score_s > 0]
    return min(scored) if scored else None


def publish_checkpoint_candidates(data: dict, source: str, top_k: int = 8, water_mode: str = 'buy_water'):
    layers = data.get('outer_layers')
    if not layers:
        return []
    # Display stays small, but the landscape should capture a representative
    # cloud of complete 10->60 talent paths rather than only the visible top 8.
    capture_k=max(int(top_k),384)
    states = opt.all_top_states(layers, top_k=capture_k)
    precision = int(data.get('preview_precision_mobs') or data.get('search_meta',{}).get('selection_mobs') or data.get('search_meta',{}).get('score_mobs') or 0)
    candidates = [sm.candidate_dict(st, i, source, water_mode=water_mode, search_precision_mobs=precision)
                  for i, st in enumerate(states, 1)]
    sm.merge_display_candidates(candidates, max_k=top_k, water_mode=water_mode)
    sm.publish_viewer_snapshot(water_mode)
    return candidates


def import_legacy_to_gui(top_k: int = 8):
    info = sm.adopt_legacy_if_useful()
    if not info or not info.get('adopted'):
        return
    cp = sm.CHECKPOINTS / 'legacy_latest.pkl'
    try:
        data = opt.load_checkpoint(cp)
    except Exception:
        return
    if not data:
        return
    start = scored_start_level(data)
    end = data.get('outer_level')
    source = f'legacy_{start or "?"}_{end or "?"}'
    publish_checkpoint_candidates(data, source, top_k, 'buy_water')
    # Only a full 11-60 legacy checkpoint is eligible for later validation/promotion.
    sm.atomic_write_json(sm.RUNTIME / 'legacy_summary.json', {
        'source': source,
        'scored_start_level': start,
        'outer_level': end,
        'eligible_full_arc': start == 11 and end == 60,
    })


def preview_uncertainty_margin(precision_mobs: int) -> float:
    """Loose coarse-search margin used only to decide who gets exact replay next."""
    n=max(1,int(precision_mobs or 1))
    return max(0.01, min(0.15, 0.12 / (n ** 0.5)))


def select_preview_validation_states(layers: dict, precision_mobs: int, incumbent_hours,
                                     already_path_ids: set[str], water_mode: str,
                                     fallback_top: int = 2, scan_top: int = 32):
    """Incumbent-driven validation queue.

    Any full-arc path whose coarse estimate overlaps the incumbent confidence
    band bypasses the normal top-N quota. If none do, keep the old top-N fallback
    so exploration still receives exact calibration.
    """
    states = opt.all_top_states(layers or {}, top_k=max(int(scan_top), int(fallback_top), 1))
    if not states:
        return []
    probes=[]
    margin=preview_uncertainty_margin(precision_mobs)
    try:
        incumbent=float(incumbent_hours) if incumbent_hours is not None else None
    except Exception:
        incumbent=None
    for st in states:
        probe=sm.candidate_dict(st, 1, 'preview_probe', water_mode=water_mode,
                                search_precision_mobs=int(precision_mobs or 0))
        pid=probe.get('path_id') or probe.get('id')
        if not probe.get('full_arc') or not pid or pid in already_path_ids:
            continue
        est=probe.get('search_hours')
        plausible = (incumbent is not None and est is not None and
                     float(est) <= incumbent * (1.0 + margin))
        probes.append((st, pid, plausible, float(est) if est is not None else float('inf')))
    challengers=[x for x in probes if x[2]]
    if challengers:
        challengers.sort(key=lambda x:x[3])
        return [x[0] for x in challengers]
    probes.sort(key=lambda x:x[3])
    return [x[0] for x in probes[:max(0,int(fallback_top))]]



@dataclass(frozen=True)
class StartupState:
    controller: dict
    imported_seed_dirs: list
    imported_respec_schedules: list


def initialize_persistent_state(args) -> StartupState:
    sm.ensure_dirs()
    sm.migrate_legacy_buy_water_state()
    imported_priors = sm.import_state_priors(args.import_state_dir)
    imported_seed_dirs = list(imported_priors.get('seed_dirs') or [])
    imported_respec_schedules = list(imported_priors.get('respec_schedules') or [])
    for mode in sm.WATER_MODES:
        sm.seed_baseline_if_needed(mode)
        if adaptive_race_enabled(args):
            sm.migrate_adaptive_validation_authority(mode)
    import_legacy_to_gui(args.top_k)
    for mode in sm.WATER_MODES:
        sm.publish_viewer_snapshot(mode)
    controller = load_controller()
    atomic_controller(controller)
    return StartupState(controller, imported_seed_dirs, imported_respec_schedules)

def build_arg_parser():
    ap = argparse.ArgumentParser(description='Persistent anytime Mage optimizer')
    game_context.add_game_arguments(ap)
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument('--forever-as-of', dest='forever_as_of', default=None, help='Forever beta build/as-of date YYYY-MM-DD')
    ap.add_argument('--heartbeat-seconds', type=int, default=60)
    ap.add_argument('--heartbeat-history', type=int, default=288)
    ap.add_argument('--validation-mobs', type=int, default=100)
    ap.add_argument('--validate-top', type=int, default=10)
    ap.add_argument('--path-race-start-mobs', type=int, default=100,
                    help='adaptive whole-path race starting precision per level')
    ap.add_argument('--path-race-max-mobs', type=int, default=800,
                    help='adaptive whole-path race max precision per level; 0 disables adaptive authority')
    ap.add_argument('--path-race-top', type=int, default=12,
                    help='maximum canonical full paths admitted to adaptive adjudication')
    ap.add_argument('--path-race-alpha', type=float, default=0.05,
                    help='family-wise alpha for adaptive path confidence intervals')
    ap.add_argument('--preview-validate-top', type=int, default=2,
                    help='100-mob fixed-policy validations launched immediately after each full-arc preview frontier')
    ap.add_argument('--startup-replay-top', type=int, default=5,
                    help='on a new simulator hash, replay this many prior full-path leaders plus one leader per path school before normal search')
    ap.add_argument('--top-k', type=int, default=10)
    ap.add_argument('--water-mode', choices=['both','buy_water','conjured_water'], default='both',
                    help='default both: alternate the two independent water tracks')
    school_group = ap.add_mutually_exclusive_group()
    school_group.add_argument('--school', choices=['all','frost','fire','arcane'], default='all',
                              help='primary rotation school only; cross-tree support talents remain legal')
    school_group.add_argument('--frost', dest='school', action='store_const', const='frost',
                              help='shortcut for --school frost')
    ap.add_argument('--import-state-dir', action='append', default=[], metavar='PATH',
                    help='read an old optimizer state/repo folder as guidance-only talent/respec priors; repeatable')
    ap.add_argument('--once', action='store_true', help='finish current experiment then exit')
    ap.add_argument('--test-mode', action='store_true', help=argparse.SUPPRESS)
    return ap


def main(argv=None):
    configure_console()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    selected_game = game_context.validate_cli_selection(parser, args)
    if selected_game.ruleset == 'forever':
        explicit = args.forever_as_of is not None
        identity = configure_forever_build(args.forever_as_of, source='cli_explicit' if explicit else 'legacy_compat_default')
        args.forever_as_of = identity.as_of.isoformat()
    if not bool(getattr(eng,'MC_SUPPORTED',True)):
        parser.error(f"{eng.RULESET}/{eng.CLASS_NAME} does not have an MC backend yet; use python -m src.v2.runner --ruleset {eng.RULESET} --class {eng.CLASS_NAME}")
    os.environ[eng.PRIMARY_SCHOOL_ENV] = args.school

    startup = initialize_persistent_state(args)
    controller = startup.controller
    imported_seed_dirs = startup.imported_seed_dirs
    imported_respec_schedules = startup.imported_respec_schedules

    signal.signal(signal.SIGINT, request_stop_from_signal)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, request_stop_from_signal)

    active_checkpoint = {'path': None}
    status_lock = threading.Lock()
    live_status = {
        'mode': 'optimizer', 'state': 'starting', 'pid': os.getpid(), 'workers': args.workers,
        'message': 'initializing', 'started_at': time.time(), 'water_mode': None, 'school': args.school,
        'forever_build': forever_build_metadata() if selected_game.ruleset == 'forever' else None,
    }

    def set_status(**kwargs):
        with status_lock:
            live_status.update(kwargs)
            snapshot = dict(live_status)
        mode = snapshot.get('water_mode') or 'buy_water'
        snapshot['best'] = sm.current_best_meta(mode,args.school)
        snapshot['best_by_water'] = {m: sm.current_best_meta(m,args.school) for m in sm.WATER_MODES}
        sm.publish_status(snapshot)
        # Pre-aggregate tiny viewer files here. Listener requests never scan the
        # multi-GB SQLite DB or all candidate/seed files.
        for m in sm.WATER_MODES:
            sm.publish_viewer_snapshot(m, snapshot)
        return snapshot

    def heartbeat_loop():
        # Hard upper bound for silent stdout: publish + print at least once per
        # heartbeat interval even while one expensive worker batch is in flight.
        first = True
        while not STOP.is_set():
            with status_lock:
                snapshot = dict(live_status)
            mode = snapshot.get('water_mode') or 'buy_water'
            snapshot['best'] = sm.current_best_meta(mode,args.school)
            snapshot['best_by_water'] = {m: sm.current_best_meta(m,args.school) for m in sm.WATER_MODES}
            cp = active_checkpoint.get('path')
            if cp and Path(cp).exists():
                try:
                    sm.atomic_copy(Path(cp), sm.RUNTIME / 'optimizer.pkl')
                except Exception as e:
                    snapshot['heartbeat_copy_error'] = repr(e)
            sm.publish_status(snapshot)
            for m in sm.WATER_MODES:
                sm.publish_viewer_snapshot(m, snapshot)
            sm.heartbeat_snapshot(snapshot, keep=args.heartbeat_history)
            try:
                sm.make_chat_handoff()
            except Exception as e:
                print(f'[heartbeat] chat handoff failed: {e}', flush=True)
            if not first:
                elapsed = time.time() - snapshot.get('started_at', time.time())
                msg = snapshot.get('message','')
                prog = ''
                if snapshot.get('validation_total'):
                    prog = f" validation={snapshot.get('validation_done',0)}/{snapshot.get('validation_total')}"
                if snapshot.get('state') == 'searching' and str(snapshot.get('phase','')).startswith('outer') and snapshot.get('outer_stage'):
                    stage_elapsed = max(0.0, time.time() - float(snapshot.get('outer_stage_started_at') or time.time()))
                    prog += f" stage={snapshot.get('outer_stage')} stage_elapsed={stage_elapsed:.0f}s"
                print(f"[heartbeat] state={snapshot.get('state','?')} water={snapshot.get('water_mode','?')} exp={snapshot.get('experiment','?')}"
                      f" level={snapshot.get('level','—')}{prog} elapsed={elapsed/60:.1f}m | {msg}", flush=True)
            first = False
            STOP.wait(max(5, min(60, args.heartbeat_seconds)))

    hb = threading.Thread(target=heartbeat_loop, name='heartbeat', daemon=True)
    hb.start()

    def replay_startup_priors():
        """Re-establish current-hash incumbents before spending compute on search.

        A simulator semantics/hash change invalidates old numeric authority, but
        not the structural path.  Replay the previous global leaders plus one
        representative of each path school immediately at validation precision.
        """
        modes = list(sm.WATER_MODES) if args.water_mode == 'both' else [args.water_mode]
        for mode in modes:
            if STOP.is_set() or args.startup_replay_top <= 0 or args.validation_mobs <= 0:
                return
            # Startup replay is a hash-change/no-incumbent recovery lane, not a
            # tax paid on every normal restart.
            if sm.current_best_meta(mode,args.school).get('best_validated_hours') is not None:
                continue
            priors = sm.startup_replay_candidates(mode, args.startup_replay_top)
            priors = [c for c in priors if opt.replay_matches_primary_school(c.get('replay') or [], args.school)]
            if not priors:
                continue
            states,kept,skipped=prepare_startup_replay_states(priors)
            for c,e in skipped:
                print(f'[startup replay skip] water={mode} id={c.get("id")} reason={e}', flush=True)
            if not states:
                continue
            label = 'BUY/BEST-AVAILABLE' if mode == 'buy_water' else 'CONJURED-ONLY'
            print(f'[startup replay] water={label} candidates={len(states)} mobs={args.validation_mobs} '
                  f'global_top={args.startup_replay_top}+school-leaders before normal search', flush=True)
            set_status(state='startup_replay', water_mode=mode, experiment='startup_replay',
                       validation_mobs=args.validation_mobs, validation_done=0,
                       message=f'replaying {len(states)} prior full paths under current simulator hash')

            def progress(done,total,lvl,rotation,score_s,_active_dps):
                if done == 1 or done == total or done % max(1,total//12) == 0:
                    set_status(state='startup_replay', water_mode=mode, experiment='startup_replay',
                               validation_mobs=args.validation_mobs, validation_done=done,
                               validation_total=total, validation_level=lvl,
                               message=f'current-hash startup replay {done}/{total} rows')

            def complete(ci, validated):
                prior=kept[ci]; st=states[ci]
                cand=sm.candidate_dict(
                    st, ci+1, 'startup_current_hash_replay', validated,
                    water_mode=mode,
                    search_precision_mobs=sm.candidate_search_precision(prior))
                cand=prepare_fixed_candidate_for_authority(cand,args)
                cand['replayed_from_id']=prior.get('id')
                cand['replayed_from_source']=prior.get('source')
                sm.merge_display_candidates([cand], max_k=args.top_k, water_mode=mode)
                sm.publish_viewer_snapshot(mode)
                print(f'[startup replayed {ci+1}/{len(states)}] water={mode} '
                      f'{candidate_hours_for_log(cand)} school={cand.get("school")} id={cand["id"]}', flush=True)
                if (not adaptive_race_enabled(args)) and args.validation_mobs >= 100 and sm.promote_if_better(cand, None, mode, school=args.school):
                    stamp=time.strftime('%Y%m%d-%H%M%S')
                    sm.atomic_write_json(sm.track_paths(mode).history / f'improvement_{stamp}_{cand["id"]}.json', cand)
                    print(f'[BEST startup replay] water={mode} {candidate_hours_for_log(cand)} candidate={cand["id"]}', flush=True)

            try:
                opt.validate_states_fast(
                    states, n=args.validation_mobs, seed=9001, workers=args.workers,
                    progress_callback=progress, candidate_callback=complete,
                    heartbeat_seconds=min(60,args.heartbeat_seconds),
                    stop_check=STOP.is_set,
                    use_best_water=(mode == 'buy_water'))
            except opt.StopRequested:
                return
            if adaptive_race_enabled(args):
                set_status(state='adjudicating', water_mode=mode, experiment='startup_path_race',
                           message='adaptive whole-path race over Fast/native/historical union')
                raced=run_adaptive_race_gate(mode,args,None)
                if raced is not None:
                    status='resolved' if raced.race.resolved else 'unresolved'
                    surv=[raced.prepared[i].path_id for i in raced.race.survivor_indices]
                    print(f'[path race startup] water={mode} {status} rounds={raced.race.rounds} survivors={surv}',flush=True)
            set_status(state='starting', water_mode=mode, experiment=None,
                       message='startup replay/adjudication complete; entering normal search')

    try:
        replay_startup_priors()
        while not STOP.is_set():
            water_mode = choose_water_mode(controller, args.water_mode, args.school)
            track = controller_track(controller, water_mode, args.school)
            tp = sm.track_paths(water_mode)
            other_tp = sm.track_paths(sm.other_water_mode(water_mode))
            exp = track.get('current_experiment')
            if (not exp or exp.get('status') == 'completed' or
                    eng.normalize_primary_school(exp.get('school','all')) != args.school):
                epoch = int(track.get('epoch', 0))
                tier = int(track.get('tier', 0))
                desired_respecs = sm.read_user_config()['max_respecs']
                cfg = config_for(epoch, tier, args.test_mode, water_mode, desired_respecs)
                short = 'buy' if water_mode == 'buy_water' else 'conj'
                school_tag = '' if args.school == 'all' else f'_{args.school}'
                exp_id = f'{short}{school_tag}_exp_{epoch:05d}_tier{tier}'
                cp = tp.checkpoints / f'{exp_id}.pkl'
                exp = {
                    'id': exp_id, 'epoch': epoch, 'tier': tier, 'status': 'running',
                    'water_mode': water_mode, 'school': args.school, 'config': cfg,
                    'checkpoint': _checkpoint_ref(cp), 'started_at': time.time(),
                }
                track['current_experiment'] = exp
                atomic_controller(controller)
            else:
                # Old in-flight experiments keep their exact config unless the
                # user explicitly changes max-respecs in the viewer. Then archive
                # the outer experiment and start a fresh reduce; disk sim cache is
                # untouched, so already-computed mobs are never repeated.
                exp.setdefault('water_mode', water_mode)
                desired_respecs = sm.read_user_config()['max_respecs']
                if int(exp.get('config',{}).get('max_respecs',2)) != int(desired_respecs):
                    old_r=int(exp.get('config',{}).get('max_respecs',2))
                    print(f'[reconfigure] max_respecs {old_r} -> {desired_respecs}; rebuilding outer reduce only, preserving epoch/seeds/PnP cache', flush=True)
                    cp = sm.ROOT / exp['checkpoint']
                    d = opt.load_checkpoint(cp) if cp.exists() else None
                    if d and d.get('snapshot_pools'):
                        opt.save_checkpoint(cp, {
                            'version': d.get('version',7), 'phase':'snapshots',
                            'snapshot_mode': d.get('snapshot_mode','independent_pnp_v3'),
                            'snapshot_pools': d.get('snapshot_pools',{}),
                            'use_best_water': d.get('use_best_water', water_mode=='buy_water'),
                            'objective_version': opt.OBJECTIVE_VERSION,
                            'sim_code_hash': pnp_cache.current_sim_hash(),
                        })
                    exp['config']['max_respecs']=int(desired_respecs)
                    exp['status']='running'
                    atomic_controller(controller)
                    continue
                cfg = exp['config']
                cp = sm.ROOT / exp['checkpoint']
                exp_id = exp['id']

            use_best_water = water_mode == 'buy_water'
            active_checkpoint['path'] = cp
            cp_state = 'resume' if cp.exists() else 'new'
            label = 'BUY/BEST-AVAILABLE' if use_best_water else 'CONJURED-ONLY'
            print(f'[experiment] {exp_id} ({cp_state}) water={label} tier={exp["tier"]} workers={args.workers} '
                  f'beam={cfg["beam"]} snap={cfg["snapshot_width"]} score_mobs={cfg["score_mobs"]} '
                  f'dest_k={cfg["dest_k"]} explore={cfg["exploration_frac"]:.2f} '
                  f'respecs<={cfg["max_respecs"]} seeds=PnP[1>2>4>8>16>32>64>100]+disk-cache+cross-water'
                  f'+imports({len(imported_seed_dirs)}) school={args.school} objective=XP-weighted(11->60; score11-59)', flush=True)
            set_status(state='searching', water_mode=water_mode, experiment=exp_id, tier=exp['tier'], config=cfg,
                       checkpoint=_checkpoint_ref(cp), message='search/resume in progress')

            preview_validated_ids = set(sm.current_validated_path_ids(water_mode,args.school))
            preview_improved = {'value': False}

            def validate_preview_candidates(data: dict, source: str):
                if args.preview_validate_top <= 0 or args.validation_mobs <= 0:
                    return
                layers0 = data.get('outer_layers') or {}
                precision = int(data.get('preview_precision_mobs') or 0)
                incumbent_h = sm.current_best_meta(water_mode,args.school).get('best_validated_hours')
                todo = select_preview_validation_states(
                    layers0, precision, incumbent_h, preview_validated_ids, water_mode,
                    fallback_top=args.preview_validate_top,
                    scan_top=max(32, args.top_k * 4, args.preview_validate_top * 8))
                if not todo:
                    return
                for st0 in todo:
                    probe = sm.candidate_dict(st0, 1, source, water_mode=water_mode, search_precision_mobs=precision)
                    preview_validated_ids.add(probe.get('path_id') or probe['id'])
                print(f'[preview validate ASAP] precision={precision}m candidates={len(todo)} -> {args.validation_mobs}m fixed-policy replay', flush=True)
                set_status(state='validating_preview', water_mode=water_mode, experiment=exp_id,
                           phase='preview_validation', validation_mobs=args.validation_mobs,
                           validation_done=0, validation_total=None,
                           message=f'ASAP validating {len(todo)} promising full-arc candidate(s) from {precision}m preview')

                def asap_progress(done,total,lvl,rotation,score_s,_active_dps):
                    if done == 1 or done == total or done % max(1,total//10) == 0:
                        set_status(state='validating_preview', water_mode=water_mode, experiment=exp_id,
                                   phase='preview_validation', validation_mobs=args.validation_mobs,
                                   validation_done=done, validation_total=total, validation_level=lvl,
                                   message=f'ASAP preview validation {done}/{total} rows')

                def asap_complete(ci, validated):
                    st0=todo[ci]
                    st0, validated, repair_info = repair_challenger_if_needed(st0, validated, water_mode, args.validation_mobs, args.school)
                    if repair_info and repair_info.get('changed'):
                        print(f'[BEST local repair] lvl59 {repair_info.get("old_point")} -> {repair_info.get("best_point")} '
                              f'saved={repair_info.get("hours_saved",0.0)*60:.3f} min', flush=True)
                    cand=sm.candidate_dict(st0, ci+1, f'{source}_validated_asap', validated,
                                           water_mode=water_mode, search_precision_mobs=precision)
                    cand=prepare_fixed_candidate_for_authority(cand,args)
                    sm.merge_display_candidates([cand], max_k=args.top_k, water_mode=water_mode)
                    sm.publish_viewer_snapshot(water_mode)
                    print(f'[preview validated] {candidate_hours_for_log(cand)} precision-source={precision}m '
                          f'respecs={cand.get("respec_levels",[])} id={cand["id"]}', flush=True)
                    if (not adaptive_race_enabled(args)) and args.validation_mobs >= 100 and sm.promote_if_better(cand, None, water_mode, school=args.school):
                        preview_improved['value']=True
                        stamp=time.strftime('%Y%m%d-%H%M%S')
                        sm.atomic_write_json(tp.history / f'improvement_{stamp}_{cand["id"]}.json', cand)
                        print(f'[BEST replayable ASAP] {candidate_hours_for_log(cand)} candidate={cand["id"]}', flush=True)

                opt.validate_states_fast(todo, n=args.validation_mobs, seed=9001, workers=args.workers,
                                         progress_callback=asap_progress, candidate_callback=asap_complete,
                                         heartbeat_seconds=min(60,args.heartbeat_seconds),
                                         stop_check=STOP.is_set, use_best_water=use_best_water)
                set_status(state='searching', water_mode=water_mode, experiment=exp_id, phase='snapshots',
                           level=None, validation_done=None, validation_total=None, validation_level=None,
                           message=f'resuming search after ASAP {precision}m preview validation')

            def checkpoint_callback(data: dict):
                phase = data.get('phase')
                lvl = data.get('outer_level') or data.get('snapshot_level')
                if phase in {'outer_preview_progress', 'outer_fastlane_progress', 'outer_progress'}:
                    stage = data.get('outer_stage') or 'working'
                    precision = int(data.get('preview_precision_mobs') or 0)
                    status_phase = {'outer_preview_progress': 'outer_preview', 'outer_fastlane_progress': 'outer_fastlane', 'outer_progress': 'outer'}[phase]
                    detail = data.get('outer_stage_detail') or {}
                    bits = []
                    for key in ('probe', 'selection_mobs', 'respec_layer', 'candidates', 'mobs', 'dest_k', 'pool'):
                        if key in detail:
                            bits.append(f'{key}={detail[key]}')
                    suffix = (' ' + ' '.join(bits)) if bits else ''
                    # Memory-only update: the heartbeat thread will publish it.
                    # Avoid rewriting viewer/checkpoint files several times per level.
                    with status_lock:
                        live_status.update({
                            'state': 'searching', 'water_mode': water_mode, 'experiment': exp_id,
                            'phase': status_phase, 'level': lvl, 'outer_stage': stage,
                            'outer_stage_started_at': time.time(), 'preview_precision_mobs': precision,
                            'validation_done': None, 'validation_total': None, 'validation_level': None,
                            'message': f'{status_phase} {precision}m level {lvl} stage={stage}{suffix}',
                        })
                    return
                if cp.exists():
                    sm.atomic_copy(cp, sm.RUNTIME / 'optimizer.pkl')
                set_status(state='searching', water_mode=water_mode, experiment=exp_id, phase=phase, level=lvl,
                           validation_done=None, validation_total=None, validation_level=None,
                           message=f'{phase} through level {lvl}')
                if phase in {'outer', 'outer_preview', 'outer_fastlane'}:
                    if phase in {'outer_preview', 'outer_fastlane'}:
                        pm = int(data.get('preview_precision_mobs') or data.get('snapshot_precision_mobs') or 0)
                        lane = 'fastlane' if phase == 'outer_fastlane' else 'preview'
                        source = f'{exp_id}_{lane}_{pm}m'
                    else:
                        source = f'{exp_id}_search'
                    publish_checkpoint_candidates(data, source, args.top_k, water_mode)
                    if phase in {'outer_preview', 'outer_fastlane'}:
                        validate_preview_candidates(data, source)
                if sm.read_user_config()['max_respecs'] != int(cfg.get('max_respecs',2)):
                    raise ReconfigureRequested()
                if STOP.is_set():
                    raise opt.StopRequested()

            try:
                # Runtime proposal prior only; exact simulation still decides scores.
                opt.set_talent_value_prior(sm.load_talent_marginal_stats(water_mode,args.school))
                layers = opt.run_search(
                    **cfg,
                    workers=args.workers,
                    checkpoint=cp,
                    resume=True,
                    callback=checkpoint_callback,
                    seed_dir=sm.school_seed_dir(water_mode,args.school),
                    cross_seed_dirs=[sm.school_seed_dir(sm.other_water_mode(water_mode),args.school)] + imported_seed_dirs,
                    use_best_water=use_best_water,
                    respec_prior_schedules=imported_respec_schedules,
                    incumbent_hours_provider=lambda: sm.current_best_meta(water_mode,args.school).get('best_validated_hours'),
                    fastlane_max_per_preview=3,
                )
            except ReconfigureRequested:
                new_r=sm.read_user_config()['max_respecs']
                print(f'[reconfigure] checkpointed; switching max_respecs to {new_r}; outer reduce only, same epoch/cache', flush=True)
                d = opt.load_checkpoint(cp) if cp.exists() else None
                if d and d.get('snapshot_pools'):
                    opt.save_checkpoint(cp, {
                        'version': d.get('version',7), 'phase':'snapshots',
                        'snapshot_mode': d.get('snapshot_mode','independent_pnp_v3'),
                        'snapshot_pools': d.get('snapshot_pools',{}),
                        'use_best_water': bool(use_best_water),
                        'objective_version': opt.OBJECTIVE_VERSION,
                        'sim_code_hash': pnp_cache.current_sim_hash(),
                    })
                exp['config']['max_respecs']=int(new_r)
                exp['status']='running'
                atomic_controller(controller)
                continue
            except opt.StopRequested:
                print('[stop] search batch checkpointed; rerun ./run.sh to continue.', flush=True)
                break

            if STOP.is_set():
                break

            search_states = opt.all_top_states(layers, top_k=args.top_k)
            if search_states:
                lead = search_states[0]
                rs = [ev.level for ev in lead.events if ev.kind == 'respec']
                print(f'[search complete] best={lead.cumulative_s/3600:.6f} h respecs={rs} '
                      f'coherence={getattr(lead, "coherence_penalty", 0.0):.2f}', flush=True)
            final_search_precision=max(int(cfg['score_mobs']),max(pnp_cache.PRECISION_LADDER))
            search_candidates = [sm.candidate_dict(st, i, f'{exp_id}_search', water_mode=water_mode, search_precision_mobs=final_search_precision) for i, st in enumerate(search_states, 1)]
            sm.merge_display_candidates(search_candidates, max_k=args.top_k, water_mode=water_mode)

            # Fast full-arc validation: replay the exact build+rotation policies
            # selected by search. Do NOT re-run the policy optimizer here. The
            # top batch is deduplicated across candidate/level rows and farmed
            # out to the worker pool. Expensive policy refinement is a later
            # search concern and must never block the first top-k validation.
            improved = bool(preview_improved['value'])
            if cfg['start_level'] == 11 and cfg['end_level'] == 60 and search_states:
                already = sm.current_validated_path_ids(water_mode,args.school)
                vstates = []
                for st0 in search_states:
                    probe0 = sm.candidate_dict(st0, 1, f'{exp_id}_search', water_mode=water_mode, search_precision_mobs=final_search_precision)
                    if (probe0.get('path_id') or probe0['id']) in already:
                        continue
                    vstates.append(st0)
                    if len(vstates) >= max(1, args.validate_top): break
                print(f'[validation start] candidates={len(vstates)} mobs={args.validation_mobs} '
                      f'mode=fixed-policy replay workers={args.workers}', flush=True)
                set_status(state='validating', water_mode=water_mode, experiment=exp_id, validation_rank=None,
                           validation_mobs=args.validation_mobs, validation_done=0,
                           message=f'fast replay-validating top {len(vstates)} candidates')

                published = {}
                def validation_progress(done, total, lvl, rotation, score_s, _active_dps):
                    # Completion prints are throttled; the independent heartbeat
                    # guarantees <=60 s silence even if no worker finishes.
                    if done == 1 or done == total or done % max(1, total // 20) == 0:
                        print(f'[validate batch] {done}/{total} unique rows · level={lvl:02d} '
                              f'{score_s/60:.2f} min/100 | {console_safe(rotation)}', flush=True)
                    set_status(state='validating', water_mode=water_mode, experiment=exp_id, validation_mobs=args.validation_mobs,
                               validation_done=done, validation_total=total, validation_level=lvl,
                               message=f'fast replay validation {done}/{total} unique rows')

                def validation_heartbeat(done, total, cdone, ctotal):
                    print(f'[validate heartbeat] rows={done}/{total} candidates={cdone}/{ctotal}', flush=True)
                    set_status(state='validating', water_mode=water_mode, experiment=exp_id, validation_mobs=args.validation_mobs,
                               validation_done=done, validation_total=total,
                               message=f'fast replay validation; {cdone}/{ctotal} candidates complete')

                def candidate_complete(ci, validated):
                    nonlocal improved
                    st = vstates[ci]
                    st, validated, repair_info = repair_challenger_if_needed(st, validated, water_mode, args.validation_mobs, args.school)
                    if repair_info and repair_info.get('changed'):
                        print(f'[BEST local repair] lvl59 {repair_info.get("old_point")} -> {repair_info.get("best_point")} '
                              f'saved={repair_info.get("hours_saved",0.0)*60:.3f} min', flush=True)
                    cand = sm.candidate_dict(st, ci + 1, f'{exp_id}_validated', validated, water_mode=water_mode, search_precision_mobs=final_search_precision)
                    cand = prepare_fixed_candidate_for_authority(cand,args)
                    published[ci] = cand
                    sm.merge_display_candidates([cand], max_k=args.top_k, water_mode=water_mode)
                    sm.publish_viewer_snapshot(water_mode)
                    rs = cand.get('respec_levels', [])
                    print(f'[validated candidate {ci+1}/{len(vstates)}] '
                          f'{candidate_hours_for_log(cand)} respecs={rs} id={cand["id"]}', flush=True)
                    if (not adaptive_race_enabled(args)) and args.validation_mobs >= 100 and sm.promote_if_better(cand, cp, water_mode, school=args.school):
                        improved = True
                        stamp = time.strftime('%Y%m%d-%H%M%S')
                        sm.atomic_write_json(tp.history / f'improvement_{stamp}_{cand["id"]}.json', cand)
                        print(f'[BEST replayable] {candidate_hours_for_log(cand)} candidate={cand["id"]}', flush=True)

                try:
                    opt.validate_states_fast(vstates, n=args.validation_mobs, seed=9001,
                                             workers=args.workers,
                                             progress_callback=validation_progress,
                                             heartbeat_callback=validation_heartbeat,
                                             heartbeat_seconds=min(60, args.heartbeat_seconds),
                                             candidate_callback=candidate_complete,
                                             stop_check=STOP.is_set,
                                             use_best_water=use_best_water)
                except opt.StopRequested:
                    print('[stop] validation interrupted cleanly; search checkpoint remains resumable.', flush=True)

                if published:
                    ranked = sorted(published.values(), key=candidate_hours_value)
                    print('[validation complete] ' + ' · '.join(
                        f"#{j+1} {candidate_hours_value(c, float('nan')):.4f}h provisional r={c.get('respec_levels',[])}"
                        for j, c in enumerate(ranked[:10])
                    ), flush=True)
                if adaptive_race_enabled(args):
                    set_status(state='adjudicating', water_mode=water_mode, experiment=exp_id,
                               phase='adaptive_path_race', message='racing canonical full-path finalist union')
                    raced=run_adaptive_race_gate(water_mode,args,cp)
                    if raced is not None:
                        status='resolved' if raced.race.resolved else 'unresolved'
                        surv=[raced.prepared[i].path_id for i in raced.race.survivor_indices]
                        print(f'[path race] {status} rounds={raced.race.rounds} survivors={surv}',flush=True)
                        if raced.promoted:
                            improved=True

            if STOP.is_set():
                break

            exp['status'] = 'completed'
            exp['completed_at'] = time.time()
            exp['improved_best'] = improved
            track.setdefault('experiments', []).append(exp)
            track['experiments'] = track['experiments'][-100:]
            track['epoch'] = int(exp['epoch']) + 1
            if improved:
                track['no_improve_epochs'] = 0
            else:
                track['no_improve_epochs'] = int(track.get('no_improve_epochs', 0)) + 1

            # Each water track expands independently. Alternation prevents one
            # easier mode from monopolizing compute, while their seed banks can
            # still cross-pollinate talent allocations.
            if track['no_improve_epochs'] >= 2:
                track['tier'] = int(track.get('tier', 0)) + 1
                track['no_improve_epochs'] = 0
                print(f'[expand] water={water_mode} plateau -> search tier {track["tier"]}', flush=True)
            track['current_experiment'] = None
            if args.water_mode == 'both':
                if args.school=='all':
                    controller['next_water_mode'] = sm.other_water_mode(water_mode)
                else:
                    controller.setdefault('next_water_mode_by_school',{})[args.school] = sm.other_water_mode(water_mode)
            atomic_controller(controller)
            set_status(state='experiment_complete', water_mode=water_mode, experiment=exp_id,
                       message='checkpointed; next epoch/other water track will continue automatically')
            sm.make_chat_handoff()

            if args.once:
                break

        set_status(state='stopped', message='stopped cleanly; rerun to continue')
    except Exception as e:
        set_status(state='crashed', message=repr(e))
        try:
            sm.make_chat_handoff()
        except Exception:
            pass
        raise
    finally:
        STOP.set()
        hb.join(timeout=2)
        # Drain the non-blocking cache writer after the scheduler has stopped
        # producing work. This never runs on simulation worker processes.
        pnp_cache.shutdown_writer()


if __name__ == '__main__':
    main()
