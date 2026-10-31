"""Run fast, focused .242 regressions and emit machine-readable results."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    'cross_pull_and_source_recovery': [
        'tests/test_wf242_persisted_periodics_and_multi_pull.py',
        'tests/test_wf241_mixed_hot_recovery.py',
        'tests/test_wf_coverage240_source_actions_position_healing.py',
    ],
    'incoming_combat': [
        'tests/test_wf_combat231_incoming_policy_recovery.py', '-k', 'not real_mode_policy_discovery',
    ],
    'periodic_aura': [
        'tests/test_periodic_aura_runtime_g09.py', '-k', 'not listener and not backend and not service and not record',
    ],
    'generic_runtime_and_healing': [
        'tests/test_generic_heal_recovery_g12.py::test_g12_ir_publishes_health_direct_heal_and_hot_as_generic_effects',
        'tests/test_generic_heal_recovery_g12.py::test_g12_direct_heal_executes_on_actor_resource_through_generic_runtime',
        'tests/test_generic_heal_recovery_g12.py::test_g12_periodic_heal_reuses_actor_aura_and_event_queue',
        'tests/test_generic_heal_recovery_g12.py::test_g12_recovery_uses_same_actor_state_and_real_heal_action_when_useful',
        'tests/test_generic_event_runtime_g07.py::test_generic_event_queue_executes_source_backed_tuned_wrath',
        'tests/test_generic_event_runtime_g07.py::test_generic_event_runtime_can_damage_without_killing',
        'tests/test_generic_auto_attack_g24.py::test_g24_real_cat_auto_attack_repeats_and_swings_during_form_gcd',
        'tests/test_generic_auto_attack_g24.py::test_g24_leaving_required_mode_stops_the_repeated_swing_timer',
    ],
    'mode_and_resource': [
        'tests/test_generic_cross_mode_policy_g30.py::test_g30_mode_state_is_generic_policy_primitive',
        'tests/test_generic_bear_policy_g29.py::test_g29_periodic_resource_effect_executes_enrage_without_class_dispatch',
    ],
}

def main():
    results = []
    total = 0
    for name, args in SUITES.items():
        command = [sys.executable, '-m', 'pytest', '-q', *args]
        try:
            proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=30)
            output = proc.stdout + proc.stderr
            match = re.search(r'(\d+) passed', output)
            passed = int(match.group(1)) if match else 0
            total += passed
            results.append({'suite': name, 'passed': passed, 'returncode': proc.returncode,
                            'output_tail': output[-1500:], 'command': ' '.join(command)})
        except subprocess.TimeoutExpired:
            results.append({'suite': name, 'timeout_s': 30, 'returncode': None})
    result = {'version': '0.11.48.242', 'selected_passed': total,
              'all_selected_passed': all(x.get('returncode') == 0 for x in results),
              'suites': results,
              'historical_regression_notes': [
                  'G30 cross-mode expected 26.0 but .241 baseline itself produces 31.5',
                  'G29 bear schema_version expected 16 but .241 baseline itself produces 17',
              ],
              'full_historical_suite_run': False}
    (ROOT / 'WF242_VALIDATION.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'passed': total, 'all_passed': result['all_selected_passed'],
                      'suites': [(x['suite'], x.get('passed'), x.get('returncode')) for x in results]}, indent=2))
    if not result['all_selected_passed']:
        sys.exit(1)

if __name__ == '__main__':
    main()
