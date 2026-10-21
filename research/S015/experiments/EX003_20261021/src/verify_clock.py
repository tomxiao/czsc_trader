"""Verify pilot plans at two clocks using retained, authenticated inputs only."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, time
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import Dataflows, DataSpace, ProviderConfig
from strategy_runtime import (
    ExecutionPolicy, ExecutionPricing, SignalHistoryMode, StrategyCandidate,
    StrategyInit, StrategyInputBinding, StrategyRuntime, TradingPoint,
)
from trading_execution_engine import HistoricalExecutor, MarketExecutionRules


ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'research/S015/assets/runs/EX003_20261021/strategy_study'
ZONE = ZoneInfo('Asia/Shanghai')


def encode(value):
    if is_dataclass(value):
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def normalized(frame):
    """Normalize only serialization dtypes; preserve IDs, order and numeric values."""
    output = frame.copy().reset_index(drop=True)
    for column in output:
        if column in {'date', 'signal_date', 'execution_date', 'valid_session',
                      'fill_time', 'entry_date', 'exit_date', 'valuation_source_date'}:
            output[column] = pd.to_datetime(output[column])
    return output


def main():
    pilot = json.loads((WORK / 'pilot.json').read_text(encoding='utf-8'))
    ref = pilot['evidence']
    evidence_path = ROOT / 'research/S015/assets/evidence/EX003_20261021' / ref['evidence_id']
    original = evidence_path.read_bytes()
    if sha256(original).hexdigest() != ref['sha256']:
        raise ValueError('published pilot evidence hash differs')
    evidence = json.loads(original)
    run = evidence['runs'][0]
    if pilot['input_bindings'] != evidence['input_bindings']:
        raise ValueError('pilot binding differs from published evidence')
    binding = StrategyInputBinding.from_mapping(pilot['input_bindings']['full'])
    pricing = ExecutionPricing.from_dict(evidence['request_identity']['pricing'])
    payload = {'decision_feedback': 'MARKET_INTENT', 'runtime': {
        'module': 'strategy_runtime.strategies.pressure_reversal',
        'qualname': 'PressureReversal', 'contract_version': 2,
        'source_files': ['strategies/pressure_reversal.py'],
        'source_sha256': 'b10d4691e4db85766dabd5e06edf523da076d6504778bb7d088aee14060f1ab1',
    }, 'parameters': pilot['parameters']}
    candidate = StrategyCandidate('S015', 'C0001', payload, EXPERIMENT / 'src/strategy_runtime')
    flows = Dataflows(base_dir=ROOT, space=DataSpace(Path('research/S015/assets/data')),
                      providers=ProviderConfig(bindings={}))
    runtime = StrategyRuntime(dataflows=flows)
    instance = runtime.create(StrategyInit(
        candidate, binding.plan.tradable_window, ROOT / '.tmp/s015-clock-validation',
        pricing=pricing,
    ))
    instance.prepare_data(binding=binding)
    replay = run['replay_evidence']
    daily = pd.DataFrame(replay['execution_daily']).rename(columns={'date': 'dt'})
    daily['dt'] = pd.to_datetime(daily['dt'])
    intraday = pd.DataFrame(replay['execution_intraday'])
    if intraday.empty:
        intraday = pd.DataFrame(columns=['dt', 'high', 'low'])
    else:
        intraday = intraday.rename(columns={'date': 'dt'})
        intraday['dt'] = pd.to_datetime(intraday['dt'])
    policy = ExecutionPolicy(**run['signal_support']['execution_policy'])
    rules = MarketExecutionRules.from_dict(evidence['request_identity']['market_rules'])
    executors = [HistoricalExecutor(
        strategy_reference=candidate.reference_id, symbol='159326.SZ',
        execution_daily=daily, execution_intraday=intraday,
        evaluation_start=pd.Timestamp(binding.plan.tradable_window.start),
        evaluation_end=pd.Timestamp(binding.plan.tradable_window.end),
        initial_cash=100000., execution_policy=policy, order_types=('LIMIT', 'MARKET'),
        pricing=pricing, market_rules=rules,
    ) for _ in range(2)]
    pairs = []
    original_daily = normalized(pd.DataFrame(run['ledgers']['account_daily']['data']))
    for index, (day, signal) in enumerate(binding.plan.signal_dates.items()):
        plans = []
        snapshots = []
        for clock, executor in zip((time(17, 30), time(20, 31)), executors, strict=True):
            point = TradingPoint(day, datetime.combine(signal, clock, tzinfo=ZONE))
            portfolio, state = executor.snapshot(point)
            snapshots.append((portfolio, state))
            actual = original_daily.iloc[index]
            if int(actual.quantity_before) != portfolio.position_quantity:
                raise AssertionError(f'pilot quantity path differs at {day}')
            if abs(float(actual.cash_before) - float(portfolio.available_cash)) > 1e-8:
                raise AssertionError(f'pilot cash path differs at {day}')
            plans.append(instance.plan_at(point=point, portfolio=portfolio, state=state,
                                          history_mode=SignalHistoryMode.WINDOW))
        for first, second in zip(snapshots[0], snapshots[1], strict=True):
            a, b = encode(first), encode(second)
            a.pop('as_of')
            b.pop('as_of')
            if a != b:
                raise AssertionError(f'pre-plan account or cycle state differs at {day}')
        first, second = (encode(plan) for plan in plans)
        first.pop('generated_at')
        second.pop('generated_at')
        if first != second:
            raise AssertionError(f'complete plan differs at {day}')
        digest = sha256(json.dumps(first, sort_keys=True).encode()).hexdigest()
        pairs.append({'session': day.isoformat(), 'plan_identity': plans[0].plan_identity,
                      'complete_economic_plan_sha256': digest})
        for plan, executor in zip(plans, executors, strict=True):
            executor.execute(plan)
    results = [executor.finish() for executor in executors]
    counts = {}
    for name in ('decisions', 'orders', 'fills', 'trades', 'account_daily'):
        first, second = (normalized(getattr(result, name)) for result in results)
        pd.testing.assert_frame_equal(first, second, check_dtype=False, check_exact=True)
        original_frame = normalized(pd.DataFrame(run['ledgers'][name]['data']))
        pd.testing.assert_frame_equal(first, original_frame[first.columns], check_dtype=False,
                                      check_exact=False, rtol=1e-12, atol=1e-8)
        counts[name] = len(first)
    result = {
        'status': 'PASS', 'candidate': 'S015-C0001', 'pilot_evidence': ref,
        'input_binding_identity': binding.identity, 'sessions': len(pairs),
        'clocks': ['17:30 Asia/Shanghai', '20:31 Asia/Shanghai'],
        'comparison': 'All ExecutionPlan fields except generated_at; all snapshot fields except as_of',
        'actual_path_check': 'Both complete TXE paths match retained pilot pre-plan cash and quantities',
        'ledger_comparison': 'All five ledgers match each other exactly and retained formal pilot including IDs',
        'ledger_original_tolerance': {'relative': 1e-12, 'absolute': 1e-8},
        'counts': counts, 'execution_contract': rules.contract_version,
        'execution_intraday_rows': len(intraday),
        'provider_configuration': 'empty bindings; prepare_data(binding=existing) only; no provider preparation',
        'history_mode': 'WINDOW', 'plan_pairs': pairs,
        'limits': [
            'Conditional equivalence for C0001 and these authenticated retained inputs only.',
            'Historical vendor publication, revision chain and 17:30 availability remain unverified.',
            'Original formal pilot run used 20:31; its original timestamps and evidence remain unchanged.',
            'This is a dedicated public SRT/TXE verification replay, not a new TDR account evaluation.',
        ],
    }
    destination = EXPERIMENT / 'others/clock_validation.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                           encoding='utf-8', newline='\n')
    print(json.dumps({key: result[key] for key in ('status', 'sessions', 'counts', 'execution_contract')}))


if __name__ == '__main__':
    main()
