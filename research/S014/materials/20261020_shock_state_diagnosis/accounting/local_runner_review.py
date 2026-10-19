"""Final EX049 source workflow/gates and synthetic aggregation review only."""
import ast
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys

import authenticate_shock_population as P

ROOT, OUT = P.ROOT, P.OUT
EX = ROOT / 'research/S014/experiments/EX049_20261020'
CHECKS = Counter()


def check(name, value):
    assert value, name
    CHECKS[name] += 1


def main():
    expected = {'src/run_component.py': '2768fcd4d12f2e7e2a453cc1dc089c66f9f4e3ab24a644483fce07669aa87cf6',
                'protocols/design.json': '473778576626672f9d01ff112d77b11f76f1aac155bbafb49ce00a5bbb89e4a1',
                'src/local_cycle.py': '58827ad8d59e4b3ebd99f250a25a05f8a1f552a9ebf8626ed1fef027f9134f6b',
                'src/prepared_reader.py': '078c5d78033f40e2c73767b6ac92f1f36dbc296282ff0b00e8159bf68d2952a7',
                'src/precheck.py': '74277aacf810152efc390d7e469e62b79395968070ed66e4b26bdd6b14ea3eda'}
    reviewed = {}
    for name, digest in expected.items():
        check('final exact bytes ' + name, P.ref(EX / name)['sha256'] == digest)
        reviewed[(EX / name).relative_to(ROOT).as_posix()] = digest
    design = P.read(EX / 'protocols/design.json')
    for name, digest in design['external_source_hashes'].items():
        check('root and prior immutable bindings ' + name, P.ref(ROOT / name)['sha256'] == digest)
    check('zero funded budget and exact population', design['new_funded_account_budget'] == 0 and design['event_count'] == 21 and design['actions'] == ['ON', 'OFF_LOCAL_CYCLE'])
    check('two fixed truehold states root binding', design['states'] == P.read(OUT.parent / 'method_decision.json')['state_direction_locked_before_new_labels'])
    source = (EX / 'src/run_component.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    attributes = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    check('no account evaluation preparation or data export in runner', not set(attributes) & {'prepare', 'evaluate', 'materialize', 'to_csv', 'to_parquet', 'to_pickle'})
    gate = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'check_gate')
    text = ast.get_source_segment(source, gate)
    check('source and ON gates require two independent reviewers', 'len(gate["reviews"]) == 2' in text and '{"A", "B"}' in text and 'len({v["sha256"]' in text)
    check('ON gate exact currentlock and formal ON identity', 'review["source_lock_sha256"] == gate["source_lock_sha256"]' in text and 'review["ON_ref"] == gate["ON_ref"]' in text)
    off = ast.get_source_segment(source, next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'off'))
    check('OFF uses public ON and exact local counterpart', 'R.published(gate["ON_ref"])' in off and 'on_ref.resolve(ROOT).read_bytes() == (EX / "others/on_controls.json").read_bytes()' in off)
    check('OFF verifies original prepared content same as ON', 'manifest == original["prepared_content_identities"]' in off)
    sys.path.insert(0, str(EX / 'src'))
    spec = importlib.util.spec_from_file_location('a_local_runner', EX / 'src/run_component.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fake = [{'origin_actual_event': {'year_of_D': 2020, 'holding_age_D': age, 'remaining_D_sessions_to_deadline': 9-age},
             'D_known_states': {'STATE': state}, 'label_POSTHOC': {'advantage': advantage},
             'alternative_MODELLED_POSTHOC': {'status': status}}
            for age, state, advantage, status in [(0, True, .1, 'CLOSED'), (1, False, -.2, 'CLOSED'), (2, None, None, 'CENSORED')]]
    values = module.aggregate(fake, 'STATE')
    check('synthetic no unknown or censor imputation', values['N'] == 3 and values['cells'][2]['N'] == 1 and values['cells'][2]['mean_advantage'] is None)
    common = values['same_closed_known_cohort_reference']
    check('same known closed cohort for local choices', common == {'N': 2, 'always_exit_mean': 0., 'always_hold_mean': -.05, 'frozen_true_hold_false_exit_mean': .05})
    empty = module.aggregate(fake, 'STATE', year=2022)
    check('empty year null rather than invented success', empty['N'] == 0 and all(r['N'] == 0 and r['mean_advantage'] is None for r in empty['cells']) and empty['same_closed_known_cohort_reference']['always_exit_mean'] is None)
    check('originalGRACE age0 split not optimized bin', module.aggregate(fake, 'STATE', age_kind='age0')['N'] == 1 and module.aggregate(fake, 'STATE', age_kind='later')['N'] == 2)
    result = {'status': 'PASS_FINAL_SOURCE_READER_RUNNER', 'reviewer': 'A', 'reviewed_hashes': reviewed,
              'implementation': P.ref(Path(__file__).resolve()), 'kernel_review': P.ref(OUT / 'local_source_review.json'),
              'check_count': sum(CHECKS.values()), 'checks': dict(CHECKS),
              'manual_review': ['Final source/reader/runner and root boundaries match declared21 event component; zero account interface/budget and no registrations.',
                                'Only originalON controls and D-known states allowed after local public lock; actualON A/B strict sameONref/currentlock gates before any OFF.',
                                'Own-cycle state, original absolute deadline and pending survive; public modeled SELL plus original fees conclude at fillEopen.',
                                'Total liquidation proceeds divided by original total entry cost; strict sign and null/censor behavior. Frozen state choices retain downD and no direction reversal.',
                                'Original actual population and empty2022 retained, common closedknown cohorts and exact age/remaining descriptions; no economic gates or account-return sum.'],
              'resources': {'actual_data_fetches': 0, 'real_ON_controls': 0, 'real_OFF_labels': 0, 'funded_accounts': 0, 'fits': 0}}
    print(json.dumps({'review': P.save('local_runner_review.json', result), 'checks': result['check_count']}))


if __name__ == '__main__':
    main()
