"""Independent EX049 kernel/reader review using synthetic inputs only."""
import ast
from collections import Counter
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

import authenticate_shock_population as P
import local_cycle_oracle as O

ROOT, OUT = P.ROOT, P.OUT
EX = ROOT / 'research/S014/experiments/EX049_20261020'
CHECKS = Counter()


def check(name, value):
    assert value, name
    CHECKS[name] += 1


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    expected = {'local_cycle.py': '58827ad8d59e4b3ebd99f250a25a05f8a1f552a9ebf8626ed1fef027f9134f6b',
                'prepared_reader.py': '078c5d78033f40e2c73767b6ac92f1f36dbc296282ff0b00e8159bf68d2952a7',
                'precheck.py': '74277aacf810152efc390d7e469e62b79395968070ed66e4b26bdd6b14ea3eda'}
    for path, digest in expected.items():
        check('exact final source ' + path, P.ref(EX / 'src' / path)['sha256'] == digest)
    for path, digest in [('method_decision.json', 'e37d22bab5e8ae0806d8a63b1d57625eefeed79d485f310047f04beeb3ba7ec8'),
                         ('method_state_boundary_clarification.json', '6b59dfcf896f95735a2979ed8e60bd25534427a2f7db2bbd6ccfacd277103342')]:
        check('root final locked method ' + path, P.ref(OUT.parent / path)['sha256'] == digest)
    sys.path.insert(0, str(EX / 'src'))
    C = load('local_cycle', EX / 'src/local_cycle.py')
    T = load('a_local_fixture', EX / 'src/precheck.py')
    seed, data, dates = T.fixture()
    # Construct a second original-account representation for the independent
    # oracle. Later original holding/entry fields are deliberately irrelevant.
    rows = []
    for i, stamp in enumerate(data.source_market.index[:-1]):
        feature = data.source_features.loc[stamp]
        rows.append({'signal_date': str(stamp.date()), 'valid_session': data.clock[str(stamp.date())], 'warmup_sessions': i,
                     'entry_index': seed.entry_index if str(stamp.date()) == seed.entry_E else -1,
                     'entry_fill_price': seed.runtime_entry_price if str(stamp.date()) == seed.entry_E else None,
                     **{k: float(feature[k]) for k in ['shock_known', 'z5', 'atr_positive', 'atr20_prior', 'support_floor', 'ma20_prior', 'ma20_prior_lag5']}})
    account = {'runs': [{'ledgers': {'decisions': {'data': rows}, 'fills': {'data': [
        {'fill_id': 'B', 'price': 10., 'quantity': 100, 'fees': 1.}, {'fill_id': 'S', 'price': 11., 'quantity': 100, 'fees': 1.1}]}}}]}
    event = {'event_id': seed.event_id, 'cycle_id': seed.cycle_id, 'D': seed.first_shock_D, 'actual_entry_fill_E': seed.entry_E,
             'actual_entry_fill_id': 'B', 'actual_exit_fill_id': 'S'}
    frames = {'adjusted_daily': data.source_market, 'projected_execution': data.projected_execution,
              'execution_daily': data.raw_execution, 'price_limits': data.price_limits, 'trading_status': data.trading_status}
    for mode in ['ON', 'OFF_LOCAL_CYCLE']:
        independent = O.reconstruct(event, account, frames, mode)
        modeled = C.simulate(seed, data, C.Action(mode))
        check('independent toy cycle exact liquidation ' + mode, independent['sale']['E'] == modeled['exit_E'] and independent['sale']['price'] == modeled['exit_price_ledger'] and independent['sale']['fee'] == modeled['exit_fee'])
        check('independent toy complete trace coverage ' + mode, len(independent['trace']) == len(modeled['trace']))
        for ours, theirs in zip(independent['trace'], modeled['trace'], strict=True):
            for key in ['D', 'valid_E', 'entry_index', 'deadline_index', 'reservation_index', 'holding_age', 'target_position', 'exit_pending',
                        'pending_inherited', 'deadline_exit', 'profit_exit_eligible', 'shock_condition', 'selected_shock_exit', 'selected_cost_exit',
                        'selected_risk_exit', 'ordinary_support_exit', 'entry_grace_eligible', 'entry_grace_applied', 'net_profit', 'cost_loss_price']:
                check('independent toy original-entry state ' + key, ours[key] == theirs[key])
    for stamp in [dates[3], dates[6], dates[10]]:
        original = next(r for r in rows if r['signal_date'] == str(stamp.date()))
        states = O.causal_states(str(stamp.date()), original, frames)
        theirs = C.state_at_D(data, str(stamp.date()))
        for key in ['PRIOR_TREND_ESTABLISHED', 'NON_FINAL_DAY_DOMINATED', 'r1_log', 'r4_log']:
            check('independent fixed state expression ' + key, states[key] == theirs[key])
    for value in [np.inf, np.nan, 0., -1.]:
        prices = data.source_market.copy(deep=True)
        prices.loc[dates[6], 'Close'] = value
        check('S2 nonfinite or nonpositive explicit UNKNOWN', C.state_at_D(replace(data, source_market=prices), str(dates[6].date()))['NON_FINAL_DAY_DOMINATED'] is None)
    reader_tree = ast.parse((EX / 'src/prepared_reader.py').read_text(encoding='utf-8'))
    attrs = [n.func.attr for n in ast.walk(reader_tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    check('reader no preparation evaluation or market export', not set(attrs) & {'prepare', 'evaluate', 'materialize', 'to_csv', 'to_pickle', 'to_parquet'})
    fetches = [n for n in ast.walk(reader_tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'fetch']
    check('reader only existing prepared fetch', len(fetches) == 1 and any(k.arg == 'prepared' for k in fetches[0].keywords))
    precheck = P.read(EX / 'others/synthetic_precheck.json')
    check('32 current pure receipt source bound', precheck['status'] == 'PASS_PURE_SYNTHETIC_ONLY' and precheck['checks_count'] == 32 and all(precheck['source_hashes'][k] == v for k, v in expected.items()))
    result = {'status': 'PASS', 'reviewed_files': [P.ref(EX / 'src' / name) for name in expected], 'check_count': sum(CHECKS.values()), 'checks': dict(CHECKS),
              'implementation': P.ref(Path(__file__).resolve()), 'independent_oracle': P.ref(Path(O.__file__).resolve()),
              'synthetic_receipt': P.ref(EX / 'others/synthetic_precheck.json'),
              'manual_review': ['Typed original actual seed and unchanged absolute entry+9/+10; own-entry state retained after originalSELL, no later originalcycle holding flags reused.',
                                'Mandatory pending/deadline, cost/support/GRACE retained, blockedSELL persists, fillE-open ends event without newBUY or laterDclose.',
                                'Runtime originalBUY reconstruction in source4 units and actual liquidation in execution4 anchoredunits are distinct and authenticated; actual fundedQ fixed.',
                                'Original prepared-only reader and emptyproviders plus socket/requests deny, no newdata/market export/account computation.',
                                'S2 original draft finite guard omission corrected before any actual fetch/state/ON/OFF; originaldraft30receipt and source bytes preserved.',
                                'No real state or alternative label read in this source review. All21 ON exact controls and publicsource lock still required before OFF.'],
              'resources': {'actual_input_fetches': 0, 'real_ON_controls': 0, 'real_OFF_labels': 0, 'new_funded_accounts': 0, 'fits': 0}}
    print(json.dumps({'review': P.save('local_source_review.json', result), 'checks': result['check_count']}))


if __name__ == '__main__':
    main()
