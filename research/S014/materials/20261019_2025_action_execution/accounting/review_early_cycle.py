"""Independent EX041 method review; pure toy inputs, never actual branch history."""
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

import pandas as pd
from strategy_runtime import ObservedSeries, ParameterSet

ROOT = Path.cwd()
BASE = ROOT / 'research/S014/materials/20261019_2025_action_execution/early_cycle_method'
CHECKS = []

def forbid(*args, **kwargs):
    raise RuntimeError('Independent method review prohibits network')

socket.socket.connect = forbid
socket.create_connection = forbid

def check(name, condition):
    assert condition, name
    CHECKS.append(name)

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj

def main():
    planpath = BASE / 'method_plan.json'
    plan = json.loads(planpath.read_bytes())
    paths = {}
    for key in ['source', 'precheck_source', 'synthetic_receipt', 'original_EX023_source', 'prior_method']:
        binding = plan['bindings'][key]
        path = ROOT / binding['path']
        check('bound SHA ' + key, sha256(path.read_bytes()).hexdigest() == binding['sha256'])
        paths[key] = path
    toy_receipt = json.loads(paths['synthetic_receipt'].read_bytes())
    check('upstream actual numeric boundary and pure synthetic scope', toy_receipt['checks_count'] == 56 and toy_receipt['actual_SRT_observation_materializations'] == 164 and not toy_receipt['real_market_inputs_read'] and toy_receipt['real_strategy_account_runs'] == 0)
    old, new = load('A_original_cycle', paths['original_EX023_source']), load('A_new_cycle', paths['source'])
    past = pd.bdate_range(end='2025-05-29', periods=60)
    future = pd.to_datetime(['2025-05-30','2025-06-03','2025-06-04','2025-06-05','2025-06-06','2025-06-09','2025-06-10','2025-06-11','2025-06-12','2025-06-13','2025-06-16','2025-06-17','2025-06-18','2025-06-19','2025-06-20','2025-06-23','2025-06-24','2025-06-25','2025-06-26','2025-06-27','2025-06-30'])
    dates = pd.DatetimeIndex([pd.Timestamp('2019-12-31'), *past, *future])
    prices = pd.DataFrame(dict(Date=dates, Open=10., High=10.2, Low=9.8, Close=10., Volume=100000., Amount=1000000.))
    prices.loc[prices.Date.eq(pd.Timestamp('2025-05-30')), ['Close','Low']] = [9.,8.9]
    prices.loc[prices.Date.eq(pd.Timestamp('2025-06-17')), ['Close','Low']] = [8.,7.9]
    bounds = pd.DataFrame(dict(Date=dates, DownLimit=5., UpLimit=20.))
    status = pd.DataFrame(dict(Date=dates, Status='TRADING'))
    inputs = [prices.copy(),prices,bounds,status]
    configs = {mode: new.EarlyCycleConfig.parse({'mode': mode, 'entry_execution_date':'2025-05-30'}) for mode in ['NOOP','HOLD_ORIGINAL_CYCLE_H10']}
    baseline = old.history(*inputs, 'support_exit_reserve_H10')
    noop = new.history(*inputs, configs['NOOP'])
    hold = new.history(*inputs, configs['HOLD_ORIGINAL_CYCLE_H10'])
    pd.testing.assert_frame_equal(baseline, noop[baseline.columns], check_exact=True)
    check('independent toy full NOOP economic exact', True)
    first = dates.get_loc(pd.Timestamp('2025-05-30'))
    pd.testing.assert_frame_equal(baseline.iloc[:first], hold.iloc[:first][baseline.columns], check_exact=True)
    check('fixed BUY same first fill and preserved truthful support break', hold.iloc[first].buy_filled_today and hold.iloc[first].support_break and hold.iloc[first].support_exit_suppressed and not hold.iloc[first].exit_pending)
    check('original same-D exit intent suppressed before EJune3', baseline.iloc[first].exit_pending and baseline.iloc[first+1].sell_filled_today and hold.iloc[first+1].held_at_close)
    check('fixed entry/deadline/reservation unchanged', all(hold.iloc[first][key] == baseline.iloc[first][key] for key in ['entry_index','deadline_index','reservation_index']))
    deadline = int(hold.iloc[first].deadline_index)
    check('deadline priority and absolute reservation', hold.iloc[deadline].exit_pending and hold.iloc[deadline].deadline_exit_pending and hold.iloc[deadline].reservation_index == first+10)
    check('actual exit restores policy without new reservation', hold.iloc[deadline+1].sell_filled_today and hold.iloc[deadline+1].target_cycle_completed and not hold.iloc[deadline+1].protected_cycle_active and hold.iloc[deadline+1].reservation_index == first+10)
    check('later-cycle support exit restores', hold.loc[pd.Timestamp('2025-06-17'),'support_break'] and hold.loc[pd.Timestamp('2025-06-17'),'exit_pending'] and not hold.loc[pd.Timestamp('2025-06-17'),'protected_cycle_active'])
    for kind in ['suspended','locked_lower']:
        copy = [frame.copy(deep=True) for frame in inputs]
        if kind == 'suspended':
            copy[3].loc[deadline+1,'Status'] = 'SUSPENDED'
        else:
            for frame in copy[:2]:
                frame.loc[deadline+1,['Open','High','Low','Close']] = 5.
        out = new.history(*copy, configs['HOLD_ORIGINAL_CYCLE_H10'])
        check(kind + ' pending and old clocks retained', out.iloc[deadline+1].exit_pending and out.iloc[deadline+1].protected_sell_blocked and not out.iloc[deadline+1].sell_filled_today and out.iloc[deadline+1].reservation_index == first+10)
        check(kind + ' next legal exit restores policy', out.iloc[deadline+2].sell_filled_today and out.iloc[deadline+2].target_cycle_completed)
    missing = [f.copy(deep=True) for f in inputs]
    missing[3].loc[first,'Status'] = 'SUSPENDED'
    try:
        new.history(*missing, configs['HOLD_ORIGINAL_CYCLE_H10'])
    except ValueError:
        check('missed fixed real BUY rejects rather than selecting later cycle', True)
    else:
        raise AssertionError('must reject missed fixed entry')
    accepted = 0
    for mode in configs:
        impl = new.EarlyCycleStrategy(ParameterSet({'mode':mode,'entry_execution_date':'2025-05-30'}))
        original = old.RepairStrategy(ParameterSet({'variant':'support_exit_reserve_H10'}))
        for key in ['tradable_symbol','inputs','decision','execution','monitoring','capabilities']:
            check('original economic definition '+mode+' '+key, getattr(impl.definition,key) == getattr(original.definition,key))
        out = impl.calculate_history(dict(zip(['market','raw','limits','status'], inputs)), list(dates))
        for row in out.to_dict('records'):
            for field in impl.definition.observation.series:
                ObservedSeries(field.key,field.label,row[field.value_field],())
                accepted += 1
    check('fixed date contract actual date', configs['NOOP'].entry_execution_date == date(2025,5,30))
    result = dict(status='PASS_METHOD_AND_INDEPENDENT_SYNTHETIC_ONLY', checks=len(CHECKS), check_names=CHECKS,
                  actual_numeric_observation_values=accepted, plan_sha256=sha256(planpath.read_bytes()).hexdigest(),
                  bound_SHA=plan['bindings'], independent_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  real_account_runs_by_reviewer=0, real_counterfactual_history_rows=0, fits=0,
                  mandatory_actual_gates=['Fresh source-specific NOOP exact original economics and one-to-one identity mapping before H10.',
                  'Original May30 BUY/cash/fees/inventory and prior path exact; truthful support observations and all suppressed D retained.',
                  'Check actual original deadline and absolute reservation; pending blocked SELL retained and actual exit restores policy.',
                  'Fixed2025 T cash/position mark only; original-inventory disposition plus later participation identity.',
                  'No additivity with EX040 FORCE: different original nodes and subsequent capital paths.'],
                  interpretation='Seen-cycle diagnostic selected after known B/P facts; cannot establish a general H10 rule, predictive information, or full-year qualification.')
    with Path(__file__).with_name('early_cycle_independent_method_review.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps({'status':result['status'],'checks':len(CHECKS),'actual_numeric_values':accepted,'source_sha256':result['independent_source_sha256']}))

if __name__ == '__main__':
    main()
