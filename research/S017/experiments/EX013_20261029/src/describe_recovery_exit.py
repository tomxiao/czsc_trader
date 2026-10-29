"""Describe original EX008 C31/C32 exits; no replay, optimization or new diagnosis.

Authenticate original public accounts, frozen source/definition and all four old
COMPUTED diagnoses. Join whole fills->orders->decisions->cycles. Independently
reconstruct the frozen causal close/ATR stop arithmetic from the account's own
audit-input bars, validating every held decision. First trigger, not the final
sell decision, determines INITIAL/TRAILING/COST_PROTECTION/TIED/UNKNOWN; open
cycles stay separate. Recovery-only, breakout-only, BOTH and UNKNOWN entry
groups are retained. This is original-trade accounting, not a filtered account,
zero-cost result or evidence that a different stop would improve performance.

ATR uses completed prior RTH days only. Peak is completed Close since actual
entry with recorded per-share cost as a floor. Each triggering level must also
match the frozen recovery reference recorded after the actual sale. Ties use
1e-8 absolute / 1e-10 relative numerical comparison, not a trading threshold.
Recovery exits reset subsequent entry references: changing a stop would also
change later entries, funds and opportunities. Years describe entry cohorts;
cycle PnL is not annual portfolio return. No 2026 price is read.
"""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import math
from pathlib import Path
import sys

import pandas as pd
from czsc_trader.research_tools import EvidenceRef, ExperimentRef

from analyze import load_accounts, ECONOMIC_FIELDS, PRIMARY, economic
from run import ROOT, WORK, read, save

sys.path.append(str(ROOT/'research/S017/experiments/EX011_20261029/src'))
sys.path.append(str(ROOT/'research/S017/experiments/EX014_20261029/src'))
from describe_entry_context import bind_source, aggregate, check_partition
from describe_entry_difference import ledger
from describe_exits import at, equal, ZONE

ORIGINAL = ExperimentRef('S017', 'EX008_20261029')
OLD = ORIGINAL.resolve(ROOT)
ENTRIES = ('RECOVERY_ONLY', 'BREAKOUT_ONLY', 'BOTH', 'UNKNOWN')
EXITS = ('INITIAL', 'TRAILING', 'COST_PROTECTION', 'TIED', 'UNKNOWN')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def facts(decision):
    basis = decision['explanation']['basis']
    value = {item['key']: item['text'] for item in basis}
    if len(value) != len(basis):
        raise ValueError('duplicate decision fact')
    return value


def near(a, b):
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8)


def summarize(rows):
    result = aggregate(rows)
    def distribution(field):
        values = pd.Series([row[field] for row in rows], dtype=float)
        return None if values.empty else {'min': float(values.min()), 'q25': float(values.quantile(.25)),
            'median': float(values.median()), 'q75': float(values.quantile(.75)), 'max': float(values.max())}
    result['completed_close_peak_gain_in_entry_atr'] = distribution('completed_close_peak_in_entry_atr')
    result['completed_close_peak_return_to_cost'] = distribution('completed_close_peak_return_to_cost')
    result['trigger_to_exit_seconds'] = distribution('trigger_to_exit_seconds')
    result['peak_below_original_one_atr_risk_distance'] = sum(row['completed_close_peak_in_entry_atr'] < 1. for row in rows)
    result['protection_ever_armed_cycles'] = sum(row['protection_ever_armed'] for row in rows)
    return result


def public(reference):
    ref = EvidenceRef.from_dict(reference)
    content = ref.resolve(ROOT).read_bytes()
    if sha256(content).hexdigest() != ref.sha256:
        raise ValueError('public evidence SHA changed')
    import json
    return json.loads(content)


def entry_group(value):
    recovery, breakout = value.get('recovery_entry'), value.get('breakout_entry')
    if recovery == breakout == 'True':
        return 'BOTH'
    if recovery == 'True' and breakout == 'False':
        return 'RECOVERY_ONLY'
    if breakout == 'True' and recovery == 'False':
        return 'BREAKOUT_ONLY'
    return 'UNKNOWN'


def paths(payload):
    frame = pd.DataFrame(payload['audit_inputs']['bars'])
    for key in ('Date', 'AvailableDate', 'BarStart'):
        frame[key] = pd.to_datetime(frame[key], utc=True)
    if (frame.Date.dt.year.gt(2025).any() or frame.Date.dt.year.lt(2018).any()
            or frame.Date.duplicated().any() or not frame.Date.is_monotonic_increasing
            or (frame.AvailableDate > frame.Date).any()):
        raise ValueError('unexpected source time scope/order/availability')
    frame['_day'] = frame.Date.dt.tz_convert(ZONE).dt.date
    daily = frame.groupby('_day').agg(High=('High','max'), Low=('Low','min'), Close=('Close','last'))
    previous = daily.Close.shift()
    ranges = pd.concat([daily.High-daily.Low, (daily.High-previous).abs(), (daily.Low-previous).abs()], axis=1).max(axis=1)
    # Matches the frozen 14 completed-session ATR; no current day's information.
    atr = ranges.rolling(14, min_periods=14).mean().shift()
    return frame, atr


def describe_account(key, payload, definition):
    p = definition.parameters
    if any(p[name] != expected for name, expected in {
        'exit_mode': 'ATR_TRAIL', 'atr_days': 14, 'atr_multiple': 3.,
        'initial_atr_multiple': 1., 'profit_protection': True, 'protect_gain_atr': 2.}.items()):
        raise ValueError('unexpected frozen stop policy')
    cycles, reconciliation, decisions, orders = ledger(payload)
    frame, atr = paths(payload)
    decision_rows = sorted(decisions.values(), key=lambda row: at(row['decision_at']))
    checked, freeze_checks, rows = 0, 0, []
    fills = payload['runs']['candidate']['fills']
    for cycle in cycles:
        origin = decisions[cycle['entry_decision_id']]
        group = entry_group(facts(origin))
        entry = at(cycle['entry_at'])
        sell = next((fill for fill in fills if fill['cycle_id'] == cycle['cycle_id'] and fill['side'] == 'SELL'), None)
        if sell is not None:
            net = sell['price']*sell['quantity']-sell['fees']-cycle['entry_cost']
            equal(net, cycle['net_pnl'], 'actual whole fills vs recorded cycle pnl')
            if not math.isclose(net/cycle['entry_cost'], cycle['net_return'], abs_tol=1e-9, rel_tol=1e-9):
                raise ValueError('actual fills vs recorded cycle net return differ')
        exit_decision = None if sell is None else decisions[orders[sell['order_id']]['decision_id']]
        end = at(exit_decision['observed_through']) if exit_decision else at(decision_rows[-1]['observed_through'])
        held = [row for row in decision_rows if entry < at(row['observed_through']) <= end
                and facts(row).get('held') == 'True']
        if not held:
            raise ValueError('real cycle has no held decision')
        cost = cycle['entry_cost']/cycle['entry_quantity']
        initial_atr = float(atr.loc[entry.astimezone(ZONE).date()])
        if not math.isfinite(initial_atr) or initial_atr <= 0:
            raise ValueError('missing causal entry ATR')
        initial = cost-initial_atr
        bars = frame.loc[(frame.Date > entry) & (frame.Date <= end)].copy()
        closes = bars.Close.astype(float)
        peaks = closes.cummax().clip(lower=cost)
        atrs = bars._day.map(atr)
        trailing = (peaks-3.*atrs).cummax()
        armed = peaks.ge(cost+2.*initial_atr)
        protection = pd.Series(initial, index=bars.index).where(~armed, cost)
        stops = pd.concat([pd.Series(initial, index=bars.index), trailing, protection], axis=1).max(axis=1).cummax()
        hit = closes.le(stops)
        latched = hit.cummax()
        states = {at(stamp.isoformat()): index for index, stamp in bars.Date.items()}
        for decision in held:
            observed = at(decision['observed_through'])
            if not observed <= at(decision['decision_at']) <= at(decision['execution_start']):
                raise ValueError('noncausal decision boundary')
            index = states[observed]
            value = facts(decision)
            for field, expected in {'close': float(closes.loc[index]), 'stop': float(stops.loc[index]),
                'initial_stop': initial, 'peak_close': float(peaks.loc[index]),
                'entry_cost_per_share': cost, 'entry_atr': initial_atr}.items():
                if not near(float(value[field]), expected):
                    raise ValueError(f'frozen actual state differs: {key}/{cycle["cycle_id"]}/{field}')
            if value['stop_hit'] != str(bool(latched.loc[index])) or decision['target'] != int(not latched.loc[index]):
                raise ValueError('latched stop/target differs')
            checked += 1
        triggered = bars.index[hit]
        first = None if len(triggered) == 0 else triggered[0]
        detail = {'exit_purpose': 'UNCLOSED' if sell is None else 'UNKNOWN',
            'first_trigger': None, 'active_constraints': [], 'freeze_checks': 0,
            'completed_close_peak_return_to_cost': float(peaks.iloc[-1]/cost-1),
            'completed_close_peak_in_entry_atr': float((peaks.iloc[-1]-cost)/initial_atr),
            'completed_close_min_return_to_cost': float(closes.min()/cost-1),
            'last_checked_observation': end.isoformat(), 'initial_atr': initial_atr,
            'initial_stop': initial, 'protection_ever_armed': bool(armed.any())}
        if sell is not None and first is None:
            raise ValueError('actual sale has no causal stop trigger')
        if first is not None:
            trigger_at = bars.loc[first, 'Date']
            level = float(stops.loc[first])
            constraints = {'INITIAL': initial, 'TRAILING': float(trailing.loc[first])}
            if bool(armed.loc[first]):
                constraints['COST_PROTECTION'] = cost
            active = [name for name, value in constraints.items() if near(value, level)]
            if not active:
                raise ValueError('ratcheted stop has no attributable source')
            purpose = active[0] if len(active) == 1 else 'TIED'
            detail.update(exit_purpose=purpose if sell else 'UNCLOSED', active_constraints=active,
                first_trigger={'observed_at': trigger_at.isoformat(), 'stop': level,
                    'close': float(closes.loc[first]), 'peak_close': float(peaks.loc[first]),
                    'peak_gain_in_entry_atr': float((peaks.loc[first]-cost)/initial_atr),
                    'cost': cost, 'constraints': constraints},
                completed_close_peak_return_to_cost_at_trigger=float(peaks.loc[first]/cost-1))
            if sell:
                if not trigger_at <= at(exit_decision['observed_through']) <= at(sell['interval_start']):
                    raise ValueError('trigger follows actual sale')
                actual_trigger = next(row for row in held if at(row['observed_through']) == trigger_at)
                if facts(actual_trigger)['stop_hit'] != 'True':
                    raise ValueError('first trigger not represented in public decisions')
                detail['first_trigger']['decision_id'] = actual_trigger['decision_id']
                detail['exit_decision_id'] = exit_decision['decision_id']
                detail['trigger_to_exit_seconds'] = (at(sell['interval_end'])-trigger_at).total_seconds()
                detail['held_decisions_from_trigger_to_exit'] = sum(at(row['observed_through']) >= trigger_at for row in held)
                detail['peak_to_actual_exit_price_change'] = cycle['exit_price']/float(peaks.loc[first])-1
                detail['exit_price_minus_trigger_close'] = cycle['exit_price']-float(closes.loc[first])
                for row in decision_rows:
                    value = facts(row)
                    if value.get('closed_cycle_id') == cycle['cycle_id']:
                        if (at(value['recovery_trigger_at']) != trigger_at
                                or not near(float(value['recovery_stop']), level)
                                or at(value['closed_exit_observed']) != at(exit_decision['observed_through'])
                                or at(row['decision_at']) < at(sell['interval_end'])):
                            raise ValueError('post-sale frozen recovery line/time differs from first trigger')
                        detail['freeze_checks'] += 1
                if detail['freeze_checks'] == 0:
                    raise ValueError('closed cycle lacks observable post-sale recovery reference')
                freeze_checks += detail['freeze_checks']
        rows.append({**cycle, 'entry_group': group, **detail})
    closed = [row for row in rows if row['status'] == 'CLOSED']
    opened = [row for row in rows if row['status'] == 'OPEN']
    total = summarize(closed)
    grouped = {entry: {purpose: summarize([row for row in closed if row['entry_group'] == entry and row['exit_purpose'] == purpose])
                      for purpose in EXITS} for entry in ENTRIES}
    partition = check_partition([part for group in grouped.values() for part in group.values()], total, key)
    years = {str(year): {entry: aggregate([row for row in closed if row['entry_group'] == entry
             and row['entry_session'].startswith(str(year))]) for entry in ENTRIES} for year in range(2019,2026)}
    check_partition([part for group in years.values() for part in group.values()], total, key+'/years')
    original_groups = read(OLD/'others/analysis.json')['new_entry_groups'][key]
    for group, old in original_groups.items():
        selected = [row for row in rows if row['entry_group'] == group]
        done = [row for row in selected if row['status'] == 'CLOSED']
        if len(selected) != old['entries'] or len(done) != old['closed']:
            raise ValueError('original entry grouping count differs')
        equal(math.fsum(row['net_pnl'] for row in done), old['closed_net_pnl'], 'original entry group net')
    return {'total_closed': total, 'entry_by_exit': grouped, 'entry_year_groups': years,
        'closed_cycles': closed, 'unclosed_cycles': opened, 'ledger_reconciliation': reconciliation,
        'partition_residuals': partition, 'held_decisions_verified': checked,
        'post_exit_frozen_reference_checks': freeze_checks,
        'unknown_counts': dict(Counter(row['entry_group'] for row in rows if row['entry_group'] == 'UNKNOWN'))}


def describe():
    payloads, refs = load_accounts(OLD, ORIGINAL, ('C0031','C0032'), exact=True)
    original = read(OLD/'others/analysis.json')
    for field in ECONOMIC_FIELDS:
        if payloads['C0031']['request'][field] != payloads['C0032']['request'][field]:
            raise ValueError('different economic contract: '+field)
    for product in PRIMARY:
        if payloads['C0031']['data'][product] != payloads['C0032']['data'][product]:
            raise ValueError('different primary data: '+product)
    for field in ('account_points','account_daily','fills','trades','actions','metrics'):
        if economic(payloads['C0031']['runs']['buy_hold'][field]) != economic(payloads['C0032']['runs']['buy_hold'][field]):
            raise ValueError('different embedded BH path: '+field)
    diagnoses = {}
    for name, record in original['diagnostics'].items():
        value = public(record['evidence'])
        subject, control = name.split('_vs_')
        expected = [asdict(EvidenceRef.from_dict(original['source_accounts'][candidate]))
                    for candidate in (control, subject)]
        if value['status'] != 'COMPUTED' or value['issues'] or value['sources'] != expected:
            raise ValueError('original public diagnosis pair or status differs')
        for key, payload in payloads.items():
            found = [row for row in value['reconciliation'] if row['evaluation_id'] == payload['evaluation_id']]
            if found:
                equal(found[0]['closing_equity'], payload['runs']['candidate']['account_points'][-1]['equity'], key+'/diagnostic final')
                equal(found[0]['opening_equity'], payload['request']['initial_cash'], key+'/diagnostic initial')
                equal(found[0]['decomposed_change'], found[0]['equity_change'], key+'/diagnostic reconciliation')
        diagnoses[name] = {'reference': record['evidence'], 'status': value['status'], 'sources': value['sources'],
                           'reconciliation': value['reconciliation']}
    accounts, sources = {}, {}
    for key, payload in payloads.items():
        if refs[key].to_dict() != original['source_accounts'][key]:
            raise ValueError('original account ref differs')
        definition, sources[key] = bind_source(OLD, ORIGINAL, key, payload)
        accounts[key] = describe_account(key, payload, definition)
    return {'schema': 'S017_ORIGINAL_RECOVERY_EXIT_DESCRIPTION_V1', 'status': 'PASS',
        'scope': 'EX008_C31_C32_PUBLIC_ORIGINAL_CYCLES_2019_2025_NO_NEW_ACCOUNT',
        'script_sha256': digest(Path(__file__)), 'source_accounts': {key: ref.to_dict() for key,ref in refs.items()},
        'frozen_sources': sources, 'original_public_diagnostics': diagnoses, 'accounts': accounts,
        'economic_primary_and_embedded_bh_equal': True,
        'method_sources': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path)} for path in (
            WORK/'src/analyze.py', ROOT/'research/S017/experiments/EX014_20261029/src/describe_entry_difference.py',
            ROOT/'research/S017/experiments/EX011_20261029/src/describe_entry_context.py',
            ROOT/'research/S017/experiments/EX011_20261029/src/describe_exits.py', OLD/'others/analysis.json')],
        'limitations': ['ORIGINAL_SELECTED_TRADES_NOT_CAUSAL_OR_FILTER_COUNTERFACTUAL',
            'COMPLETED_CLOSE_PEAK_NOT_INTRABAR_MAXIMUM_OR_EXECUTABLE_PROFIT',
            'EXIT_CONSTRAINT_CLASSIFICATION_NOT_PROOF_EXIT_WAS_TOO_EARLY_OR_TOO_LATE',
            'STOP_CHANGE_ALSO_CHANGES_FUTURE_RECOVERY_REFERENCE_AND_CAPITAL_PATH',
            'OPEN_MARK_SEPARATE_NO_HYPOTHETICAL_SELL_FEE', 'ENTRY_YEAR_COHORT_NOT_ANNUAL_ACCOUNT_RETURN',
            'NUMERICAL_TOLERANCE_NOT_SEARCHED_TRADING_THRESHOLD', 'REUSED_DEVELOPMENT_SAMPLE_NOT_INDEPENDENT_VALIDATION'],
        'new_evaluations': 0, 'new_public_diagnoses': 0, 'new_configurations': 0}


if __name__ == '__main__':
    result = describe()
    save(WORK/'others/recovery_exit_description.json', result)
    print({key: {'closed': account['total_closed']['cycles'], 'verified_decisions': account['held_decisions_verified'],
        'freeze_checks': account['post_exit_frozen_reference_checks'], 'recovery': account['entry_by_exit']['RECOVERY_ONLY']}
           for key, account in result['accounts'].items()})
