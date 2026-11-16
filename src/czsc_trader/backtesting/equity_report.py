"""Project authenticated V5 account facts to the existing independent report."""

from dataclasses import asdict
import json
from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

from dataflows import MarketId
from execution_channels.historical import MarketExecutionRules, SessionPriceLimits, SuspensionInformation
from execution_channels.historical.equity import EquityExecutionResult
from strategy_evaluator import AuditStatus, audit_benchmark_replay
from strategy_evaluator.equity import audit_equity_account
from strategy_runtime import ObservationUnavailable, StrategyIdentity, StrategyObservation, canonical_sha256
from strategy_runtime.signal_explanation import SignalExplanationSnapshot
from strategy_runtime.signal_panel import ObservedSignalState, SignalAvailability, SignalPanelSnapshot, SignalStateOption

from .audit_adapter import build_benchmark_evidence
from .benchmarks import BenchmarkWindow, replay_benchmarks
from .evidence import build_manifest
from .execution_data import BacktestExecutionData
from .metrics import calculate_metrics
from .observation import UnavailablePlanObservation
from .result import BacktestResult
from .service import BacktestEvaluation
from .signal_replay import SignalReplay


ORDER_COLUMNS = ('order_id', 'decision_id', 'cycle_id', 'signal_date', 'execution_date', 'side',
                 'quantity', 'order_type', 'limit_price', 'status', 'reason')
FILL_COLUMNS = ('fill_id', 'order_id', 'decision_id', 'cycle_id', 'signal_date', 'fill_time',
                'side', 'quantity', 'price', 'fees', 'trigger', 'time_precision')
TRADE_COLUMNS = ('cycle_id', 'status', 'entry_date', 'exit_date', 'quantity', 'entry_price', 'exit_price', 'net_return')


def _records(frame):
    return json.loads(frame.to_json(orient='records', date_format='iso', date_unit='us', double_precision=15))


def _decision_reports(snapshot, candidate, account, zone):
    identity = StrategyIdentity(candidate.strategy_id, snapshot.identity.reference, snapshot.source_hash,
                                candidate.implementation_hash, candidate.instrument.symbol)
    staged = candidate.definition.execution_policy.settings.get('capital', {}).get('mode') == 'signal_cash_fraction'
    rows, observations, by_plan = [], [], {}
    for entry in account.decisions.to_dict('records'):
        plan = entry['plan']
        evidence = plan['evidence']
        signal = pd.Timestamp(entry['observed_through']).tz_convert(zone).date()
        day = pd.Timestamp(entry['execution_start']).tz_convert(zone).date()
        key = entry['decision_id']
        action = entry['side']
        target = float(entry['target'])
        signal_id = canonical_sha256({'implementation': candidate.implementation_hash,
            'observed_through': entry['observed_through'], 'target': target, 'explanation': entry['explanation']})
        decision = {'decision_id': 'DEC-' + key[:20].upper(), 'signal_date': pd.Timestamp(signal),
                    'valid_session': pd.Timestamp(day), 'target_position': target, 'plan_mode': evidence['planning_mode']}
        if staged:
            cycle = plan['cycle_after'] or plan['cycle_before'] or {}
            decision.update(plan_identity=key, signal_identity=signal_id,
                cycle_target=json.dumps({'target': target, 'target_quantity': entry['target_quantity']}),
                entry_cycle_before=json.dumps(plan['cycle_before']), entry_cycle_after=json.dumps(plan['cycle_after']),
                cycle_id=cycle.get('cycle_id'), entry_allocation_fraction=cycle.get('allocation_fraction'),
                cycle_allocation_fraction=cycle.get('allocation_fraction'), cycle_cash_budget=cycle.get('cash_budget'),
                cycle_target_quantity=cycle.get('target_quantity'),
                cycle_buy_cost_including_fees=cycle.get('buy_cost_including_fees'), cycle_status=cycle.get('phase'))
        rows.append(decision)
        by_plan[key] = decision
        head = (identity, candidate.implementation_hash, signal_id, key, signal, day, action, target)
        if entry['explanation'] is None:
            observation = UnavailablePlanObservation(*head, ObservationUnavailable(entry['signal_status']))
        else:
            explanation = SignalExplanationSnapshot.from_dict(entry['explanation'])
            state = ObservedSignalState(explanation.state_key, '目标仓位', '',
                (SignalStateOption('flat', '空仓'), SignalStateOption('long', '持仓')),
                explanation.case_key, SignalAvailability.AVAILABLE, None)
            observation = StrategyObservation(*head, (), (), SignalPanelSnapshot((), (), (state,), explanation))
        observations.append(observation)
    return pd.DataFrame(rows), tuple(observations), by_plan


def _execution_reports(account, decisions, zone):
    fills_by_order = {fill['order_id']: fill for fill in account.fills.to_dict('records')}
    orders, fills = [], []
    for row in account.orders.to_dict('records'):
        decision = decisions[row['decision_id']]
        fill = fills_by_order.get(row['order_id'])
        orders.append({**row, 'decision_id': decision['decision_id'], 'signal_date': decision['signal_date'],
                       'execution_date': decision['valid_session'], 'cycle_id': None if fill is None else fill['cycle_id'],
                       'status': 'FILLED' if fill is not None else 'UNFILLED'})
        if fill is not None:
            precision = fill['time_precision']
            fills.append({**fill, 'decision_id': decision['decision_id'], 'signal_date': decision['signal_date'],
                'fill_time': pd.Timestamp(fill['executed_at']).tz_convert(zone).tz_localize(None),
                'trigger': row['checkpoint'] or ('INTRADAY_LIMIT' if precision == 'BAR_INTERVAL' else 'OPEN'),
                'time_precision': 'SESSION' if precision == 'BAR_INTERVAL' else 'TIMESTAMP'})
    return pd.DataFrame(orders, columns=ORDER_COLUMNS), pd.DataFrame(fills, columns=FILL_COLUMNS)


def _daily_reports(account, decisions, candidate, zone, fee):
    rows = []
    cash, quantity = account.initial_cash, 0
    policy = candidate.definition.execution_policy
    staged = policy.settings.get('capital', {}).get('mode') == 'signal_cash_fraction'
    opens = dict(zip(account.decisions['portfolio_revision'], account.decisions['execution_start'], strict=True))
    first_revision = {day: revision for revision, start in reversed(tuple(opens.items()))
                      for day in (pd.Timestamp(start).tz_convert(zone).date().isoformat(),)}
    settlements = defaultdict(float)
    for entry in account.account_entries.to_dict('records'):
        if pd.Timestamp(entry['time']) <= pd.Timestamp(opens[entry['account_revision']]):
            settlements[entry['account_revision']] += entry['cash_delta']
    buy_costs = defaultdict(Decimal)
    if staged:
        for fill in account.fills.to_dict('records'):
            if fill['side'] == 'BUY':
                buy_costs[fill['account_revision']] += fill['quantity'] * Decimal(str(fill['price'])) * (1 + Decimal(str(fee)))
    for point in account.account_daily.to_dict('records'):
        decision = decisions[point['decision_id']]
        status = 'SUSPENDED' if point['execution_blocked'] else 'TRADING'
        if status == 'TRADING' and candidate.instrument.market is MarketId.CN and candidate.instrument.asset_class.value == 'ETF':
            status = None
        row = {'date': pd.Timestamp(point['session']), 'signal_date': decision['signal_date'],
               'target_position': decision['target_position'],
               'cash_before': cash + settlements[first_revision[point['session']]], 'quantity_before': quantity,
               'cash': point['cash'], 'quantity': point['quantity'], 'close': point['close'],
               'valuation_source_date': pd.Timestamp(point['valuation_price_at']).tz_convert(zone).tz_localize(None).normalize(),
               'trading_status': status, 'equity': point['equity']}
        if staged:
            cycle = json.loads(decision['entry_cycle_after'])
            if cycle is not None:
                cycle['buy_cost_including_fees'] = str(Decimal(cycle['buy_cost_including_fees']) + buy_costs[point['account_revision']])
                if point['quantity'] == 0 and decision['target_position'] == 0:
                    cycle = None
            info = cycle or {}
            row.update(entry_cycle_id=info.get('cycle_id'), entry_cycle_phase=info.get('phase'),
                       entry_cycle_cash_budget=info.get('cash_budget'),
                       entry_cycle_buy_cost_including_fees=info.get('buy_cost_including_fees'), entry_cycle=json.dumps(cycle))
        rows.append(row)
        cash, quantity = point['cash'], point['quantity']
    return pd.DataFrame(rows)


def _trade_reports(account, fills, zone):
    closed = {trade['cycle_id']: trade for trade in account.trades.to_dict('records')}
    rows = []
    for cycle, frame in fills.groupby('cycle_id', sort=False):
        buys = frame.loc[frame.side.eq('BUY')]
        sells = frame.loc[frame.side.eq('SELL')]
        trade = closed.get(cycle)
        quantity = int(buys.quantity.sum())
        rows.append({'cycle_id': cycle, 'status': 'OPEN' if trade is None else trade['status'],
                     'entry_date': buys.fill_time.iloc[0].date(),
                     'exit_date': None if trade is None else pd.Timestamp(trade['exit_at']).tz_convert(zone).date(),
                     'quantity': quantity, 'entry_price': float((buys.price * buys.quantity).sum() / quantity),
                     'exit_price': None if sells.empty else float((sells.price * sells.quantity).sum() / sells.quantity.sum()),
                     'net_return': None if trade is None else trade['net_return']})
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def _benchmark_prices(candidate, bars, constraints, sessions, zone):
    daily = bars.rename(columns={name: name.lower() for name in ('Open', 'High', 'Low', 'Close', 'Volume')})
    daily = pd.DataFrame(daily, copy=False).loc[:, ['Date', 'open', 'high', 'low', 'close', 'volume']]
    daily['dt'] = daily.pop('Date').dt.tz_convert(zone).dt.tz_localize(None).dt.normalize()
    daily = daily.dropna(subset=['open', 'high', 'low', 'close'])
    restricted = constraints.assign(session=constraints.Date.dt.tz_convert(zone).dt.date)
    restricted = restricted.sort_values('Date').drop_duplicates('session')
    halted = tuple(restricted.loc[~restricted.Tradable, 'session'])
    if candidate.instrument.market is MarketId.US:
        if set(halted).intersection(sessions.date):
            raise ValueError('the next-open report benchmarks require US tradability for every evaluation session')
        return daily, None
    bounds = tuple(SessionPriceLimits(row.session, row.PriceLimitLower, row.PriceLimitUpper, row.PriceTick)
                   for row in restricted.loc[restricted.Tradable].itertuples())
    scope = SuspensionInformation.PROVIDED if halted or candidate.instrument.asset_class.value == 'STOCK' else SuspensionInformation.NOT_PROVIDED
    return daily, MarketExecutionRules(candidate.instrument.symbol, bounds, halted, scope)


def _audit(run, candidate, bars, execution_bars, constraints, initial_cash, fee):
    ledger = {name: run[name] for name in
              ('decisions', 'orders', 'fills', 'account_entries', 'account_points', 'trades')}
    ledger.update(account_contract=5, decision_contract='FORMAL_V5', initial_cash=initial_cash,
                  specification=asdict(candidate.definition.execution_spec),
                  price_basis=run['price_basis'], quantity_basis=run['quantity_basis'], fee_rate=fee,
                  bars=_records(bars), constraints=_records(constraints),
                  execution_bars=None if execution_bars is None else _records(execution_bars))
    result = audit_equity_account(**ledger)
    if result.observations != len(run['account_points']):
        raise ValueError('SE audit did not cover the complete V5 account')
    return {'status': 'PASS', 'evidence_hash': canonical_sha256(ledger),
            'checks': ['v5_account_ledger'], 'reason_codes': []}


def equity_report(snapshot, request, candidate, run, products, identities, reference):
    fee = request.fee_rate
    account = EquityExecutionResult(**{name: pd.DataFrame(run[name]) for name in
        ('decisions', 'orders', 'fills', 'account_entries', 'account_points', 'account_daily', 'trades')},
        specification=asdict(candidate.definition.execution_spec), initial_cash=request.initial_cash,
        price_basis=run['price_basis'], quantity_basis=run['quantity_basis'])
    zone = ZoneInfo(candidate.instrument.timezone)
    decisions, observations, by_plan = _decision_reports(snapshot, candidate, account, zone)
    orders, fills = _execution_reports(account, by_plan, zone)
    daily = _daily_reports(account, by_plan, candidate, zone, fee)
    result = BacktestResult(snapshot.identity, decisions, orders, fills, daily, _trade_reports(account, fills, zone), observations)
    sessions = pd.DatetimeIndex(daily['date'], name='dt')
    bars, constraints = products['bars'], products['constraints']
    prices, rules = _benchmark_prices(candidate, products.get('benchmark:bars', bars), constraints, sessions, zone)
    source_hash = identities.get('benchmark:bars', identities['bars'])['content_sha256']
    execution = BacktestExecutionData(snapshot.runtime_root, candidate.instrument.symbol, request.asset_type, prices, prices,
        pd.DataFrame(), source_hash, sessions[-1].date(), sessions, market_rules=rules)
    signal = SignalReplay(snapshot, candidate, decisions, prices.dt.min(), prices.dt.max(), sessions[0], sessions[-1],
        snapshot.runtime_root, source_hash, {'mode': 'account_replay_v5', 'model_fee_rate': fee,
            'prepared_data_identity': reference.manifest_sha256,
            'execution_input_identities': {role: item['content_sha256'] for role, item in identities.items()}})
    window = BenchmarkWindow(sessions[0], sessions[-1], fee)
    benchmarks = replay_benchmarks(window, execution, request.initial_cash, lot_size=request.lot_size)
    audit = _audit(run, candidate, bars, products.get('execution:bars'), constraints, request.initial_cash, fee)
    audited_benchmarks = {name: audit_benchmark_replay(value) for name, value in
        build_benchmark_evidence(benchmarks, window, execution, request.initial_cash, lot_size=request.lot_size).items()}
    if any(value.status is not AuditStatus.PASS for value in audited_benchmarks.values()):
        raise ValueError('SE benchmark audit failed: ' + str({name: value.reason_codes for name, value in audited_benchmarks.items()}))
    audit['benchmarks'] = {name: value.to_dict() for name, value in audited_benchmarks.items()}
    metrics = {'strategy': {'reference': snapshot.identity.reference,
                            'metrics': calculate_metrics(result, request.initial_cash)}, 'benchmarks': benchmarks.metrics}
    market = candidate.instrument.market.value + '_' + candidate.instrument.asset_class.value
    manifest = build_manifest(request=request, snapshot=snapshot, data=execution, signals=signal,
        metrics=metrics, audit=audit, application={'mode': 'native_symbol', 'strategy_reference_symbol': candidate.instrument.symbol,
            'backtest_symbol': candidate.instrument.symbol, 'runtime_engine': 'srt', 'chart_renderer': 'TDR',
            'chart_contract': 'tdr_backtest_chart.v2'}, engine='TDR_ACCOUNT_REPLAY_V5',
        execution_facts={'market_security': market, 'fingerprint': source_hash, 'cutoff': sessions[-1].date().isoformat(),
            'signal_adjustment': 'hfq', 'execution_adjustment': request.price_basis.value,
            'pricing': {'basis': request.price_basis.value, 'quantity_unit': 'RESEARCH_UNIT',
                        'anchor_date': None, 'anchor_factor': None},
            'market_rules': None if rules is None else rules.to_dict()})
    return BacktestEvaluation(snapshot, request, signal, execution, result, benchmarks, metrics, manifest)
