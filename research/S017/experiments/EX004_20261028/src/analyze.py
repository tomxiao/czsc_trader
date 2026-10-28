"""EX004 identity-bound continuous accounts and descriptive profit giveback."""
from collections import defaultdict
from datetime import date, datetime
from hashlib import sha256
import importlib.util
from math import isclose
from pathlib import Path
from statistics import median
import sys
from zoneinfo import ZoneInfo

from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest, AccountRunRef
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from strategy_manager import CandidateKey


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load analysis dependency: {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUN = _load_module('_s017_ex004_analysis_runner', Path(__file__).with_name('run.py'))
ROOT, WORK, REPOSITORY, EXPERIMENT = RUN.ROOT, RUN.WORK, RUN.REPOSITORY, RUN.EXPERIMENT
PRIOR_EXPERIMENT = ExperimentRef('S017', 'EX002_20261028')
PRIOR_WORK = PRIOR_EXPERIMENT.resolve(ROOT)
PRIOR_SOURCE = PRIOR_WORK/'src/analyze.py'
PRIOR_RUNNER_SOURCE = PRIOR_WORK/'src/run.py'
_prior_runner = _load_module('_s017_ex002_for_ex004_runner', PRIOR_RUNNER_SOURCE)
_sentinel = object()
_saved_run = sys.modules.get('run', _sentinel)
try:
    sys.modules['run'] = _prior_runner
    PRIOR = _load_module('_s017_ex002_for_ex004_helpers', PRIOR_SOURCE)
finally:
    if _saved_run is _sentinel:
        del sys.modules['run']
    else:
        sys.modules['run'] = _saved_run


COMPARISONS = (
    ('C0021', 'C0002', 'Replace short-channel exit with 10-percent ratcheting close stop; same 65-bar entry.'),
    ('C0022', 'C0002', 'Replace short-channel exit with daily-ATR ratcheting close stop; same 65-bar entry.'),
    ('C0023', 'C0002', 'Change entry lookback from 65 to 260 bars; same 26-bar channel exit.'),
    ('C0024', 'C0021', 'Change entry lookback from 65 to 260 bars; same percent stop.'),
    ('C0025', 'C0022', 'Change entry lookback from 65 to 260 bars; same daily-ATR stop.'),
    ('C0025', 'C0024', 'Compare daily-volatility and price-percentage stop distances; same 260-bar entry.'),
    ('C0025', 'C0026', 'Add upward ratchet to the same initial daily-ATR loss stop; same 260-bar entry.'),
    ('C0025', 'C0023', 'Replace short-channel exit with daily-ATR ratchet; same 260-bar entry.'),
)


def load_subset(work, experiment, keys, *, exact_manifest=False):
    rows = RUN.read(work/'others/accounts.json')
    if exact_manifest and set(rows) != set(keys):
        raise ValueError('new account manifest differs from fixed EX004 configurations')
    if not set(keys) <= set(rows):
        raise ValueError('requested control account is missing')
    payloads, references = {}, {}
    for key in keys:
        record = rows[key]
        reference = EvidenceRef.from_dict(record['evidence'])
        if reference.experiment != experiment or (reference.schema, reference.schema_version) != ('equity_research', 2):
            raise ValueError('account evidence experiment or schema differs')
        content = reference.resolve(ROOT).read_bytes()
        if sha256(content).hexdigest() != reference.sha256:
            raise ValueError('account evidence bytes differ from published identity')
        payload = EquityEvaluationResult(record['request_hash'], content).payload
        if (payload.get('schema'), payload.get('schema_version')) != ('equity-research/v2', 2):
            raise ValueError('unexpected serialized account schema')
        if (payload['evaluation_id'] != record['evaluation_id']
                or payload['evaluation_identity'] != record['evaluation_identity']
                or payload['request']['candidate_id'] != key
                or payload['request']['experiment'] != {
                    'strategy_id': experiment.strategy_id, 'experiment_id': experiment.experiment_id}):
            raise ValueError('account manifest identity differs from published evidence')
        for account in payload['runs'].values():
            PRIOR._validate_run(account, payload['request']['initial_cash'])
        payloads[key], references[key] = payload, reference
    return payloads, references


def verify_contracts(payloads):
    fields = ('initial_cash', 'fee_rate', 'window', 'history_start', 'data_manifest', 'input_binding',
              'specification_hash', 'specification', 'benchmark_sha256', 'sources', 'instrument',
              'drawdown_basis', 'concentration_basis', 'frequency_window_days', 'measurement_tier')
    control = payloads['C0000']['request']
    comparisons = []
    for key, payload in payloads.items():
        for field in fields:
            equal = payload['request'][field] == control[field]
            comparisons.append({'candidate': key, 'field': field, 'equal': equal})
            if not equal:
                raise ValueError(f'noncomparable retained contract: {key}/{field}')
    return {'status': 'PASS', 'checks': comparisons}


def cycle_giveback(payload):
    """Describe close-observed cycle excursions, not a peak-selling backtest.

    This deliberately supports only one full buy and at most one full sell per
    cycle, no corporate actions, and an unchanged quantity while held. It fails
    rather than silently generalizing the price excursion to a different ledger.
    """
    account, fee = payload['runs']['candidate'], payload['request']['fee_rate']
    if account['actions']:
        raise ValueError('giveback attribution requires no corporate actions')
    fills, marks = defaultdict(list), defaultdict(list)
    sessions = {row['session']:index for index,row in enumerate(account['account_daily'])}

    def duration(start, end):
        left = datetime.fromisoformat(start.replace('Z', '+00:00'))
        right = datetime.fromisoformat(end.replace('Z', '+00:00'))
        first = left.astimezone(ZoneInfo('America/New_York')).date()
        last = right.astimezone(ZoneInfo('America/New_York')).date()
        return {
            'calendar_days_inclusive': (last-first).days+1,
            'elapsed_calendar_hours': (right-left).total_seconds()/3600.,
            'trading_sessions_inclusive': sessions[last.isoformat()]-sessions[first.isoformat()]+1,
            'time_basis': 'entry interval start to exit interval end or terminal observation; model interval bounds, not precise fill timestamps',
        }
    for fill in account['fills']:
        fills[fill['cycle_id']].append(fill)
    for point in account['account_points']:
        if point['quantity'] > 0:
            if point['cycle_id'] is None or point['valuation_stale']:
                raise ValueError('held excursion requires a cycle ID and current observed mark')
            marks[point['cycle_id']].append(point)
    closed = {trade['cycle_id']: trade for trade in account['trades']}
    if len(closed) != len(account['trades']):
        raise ValueError('duplicate closed-cycle ledger rows')
    rows, open_rows = [], []
    for cycle_id, cycle_fills in fills.items():
        buys = [fill for fill in cycle_fills if fill['side'] == 'BUY']
        sells = [fill for fill in cycle_fills if fill['side'] == 'SELL']
        if len(buys) != 1 or len(sells) > 1 or len(buys)+len(sells) != len(cycle_fills):
            raise ValueError('excursion diagnostic supports one buy and at most one full exit')
        buy, points = buys[0], marks[cycle_id]
        quantity = buy['quantity']
        cost = quantity*buy['price']+buy['fees']
        if not points or any(point['quantity'] != quantity for point in points):
            raise ValueError('cycle quantity changed or no held close was observed')
        if any(point['time'] < buy['interval_end'] for point in points):
            raise ValueError('held mark predates the completed entry interval')
        peak = max(points, key=lambda point: point['close'])
        peak_marked_pnl = quantity*peak['close']-cost
        peak_net_liquidation_pnl = quantity*peak['close']*(1.-fee)-cost
        row = {
            'cycle_id': cycle_id, 'entry_interval_start': buy['interval_start'],
            'entry_interval_end': buy['interval_end'], 'quantity': quantity,
            'entry_fill_price': buy['price'], 'entry_cost_including_fee': cost,
            'held_bar_observations': len(points), 'held_sessions': len({p['session'] for p in points}),
            'peak_completed_close': peak['close'], 'peak_close_at': peak['time'],
            'peak_marked_pnl_after_entry_fee': peak_marked_pnl,
            'peak_hypothetical_net_liquidation_pnl': peak_net_liquidation_pnl,
            'peak_hypothetical_net_liquidation_return_on_cost': peak_net_liquidation_pnl/cost,
            'positive_peak_hypothetical_net_profit': max(0., peak_net_liquidation_pnl),
        }
        if sells:
            sell, trade = sells[0], closed.get(cycle_id)
            if trade is None or trade['status'] != 'CLOSED' or sell['quantity'] != quantity:
                raise ValueError('closed cycle does not reconcile with its complete sale')
            income = quantity*sell['price']-sell['fees']
            for actual, expected in ((trade['cost'],cost), (trade['income'],income),
                                     (trade['net_pnl'],income-cost)):
                if not isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-7):
                    raise ValueError('cycle fees or profit do not reconcile with fills')
            if trade['entry_at'] != buy['interval_start'] or trade['exit_at'] != sell['interval_end']:
                raise ValueError('cycle entry/exit intervals differ from retained trade')
            if any(point['time'] > sell['interval_start'] for point in points):
                raise ValueError('holding marks include the already-exited interval')
            signed_giveback = peak_net_liquidation_pnl-trade['net_pnl']
            row.update(status='CLOSED', exit_interval_start=sell['interval_start'],
                exit_interval_end=sell['interval_end'], exit_fill_price=sell['price'],
                actual_net_pnl=trade['net_pnl'], actual_net_return=trade['net_return'],
                signed_peak_net_profit_minus_realized=signed_giveback,
                nonnegative_giveback=max(0., signed_giveback),
                realized_above_observed_close_peak=max(0., -signed_giveback),
                giveback_fraction_of_positive_peak=(signed_giveback/peak_net_liquidation_pnl
                    if peak_net_liquidation_pnl > 0 else None))
            row['duration'] = duration(buy['interval_start'], sell['interval_end'])
            rows.append(row)
        else:
            last = account['account_points'][-1]
            if cycle_id in closed or last['cycle_id'] != cycle_id or last['quantity'] != quantity:
                raise ValueError('unclosed cycle differs from terminal account position')
            terminal_net = quantity*last['close']*(1.-fee)-cost
            row.update(status='OPEN', observed_through=last['time'], terminal_close=last['close'],
                terminal_marked_pnl_after_entry_fee=quantity*last['close']-cost,
                terminal_hypothetical_net_liquidation_pnl=terminal_net,
                signed_peak_net_profit_minus_terminal=peak_net_liquidation_pnl-terminal_net)
            row['duration'] = duration(buy['interval_start'], last['time'])
            open_rows.append(row)
    if len(rows) != len(closed) or len(rows) != account['metrics']['closed_cycles'] or len(open_rows) > 1:
        raise ValueError('cycle excursion coverage differs from account ledger')
    positive = [row for row in rows if row['peak_hypothetical_net_liquidation_pnl'] > 0]
    winners = [row['actual_net_pnl'] for row in rows if row['actual_net_pnl'] > 0]
    losers = [row['actual_net_pnl'] for row in rows if row['actual_net_pnl'] < 0]
    return {
        'status': 'PASS', 'closed_cycles': rows, 'open_cycles': open_rows,
        'summary': {
            'closed_count': len(rows), 'open_count': len(open_rows),
            'closed_wins': len(winners), 'closed_losses': len(losers),
            'closed_breakeven': len(rows)-len(winners)-len(losers),
            'closed_win_fraction': len(winners)/len(rows) if rows else None,
            'mean_winning_net_pnl_usd': sum(winners)/len(winners) if winners else None,
            'mean_losing_net_pnl_usd': sum(losers)/len(losers) if losers else None,
            'top_three_share_of_positive_closed_profit': sum(sorted(winners, reverse=True)[:3])/sum(winners) if winners else None,
            'median_closed_held_bars': median([r['held_bar_observations'] for r in rows]) if rows else None,
            'median_closed_held_sessions': median([r['held_sessions'] for r in rows]) if rows else None,
            'median_closed_trading_sessions_inclusive': median([r['duration']['trading_sessions_inclusive'] for r in rows]) if rows else None,
            'median_closed_calendar_days_inclusive': median([r['duration']['calendar_days_inclusive'] for r in rows]) if rows else None,
            'positive_peak_closed_count': len(positive),
            'positive_peak_but_realized_nonpositive_count': sum(r['actual_net_pnl'] <= 0 for r in positive),
            'median_giveback_fraction_of_positive_peak': median([r['giveback_fraction_of_positive_peak'] for r in positive]) if positive else None,
            'median_signed_giveback_return_on_entry_cost': median([
                r['signed_peak_net_profit_minus_realized']/r['entry_cost_including_fee'] for r in rows]) if rows else None,
            'sum_closed_actual_net_pnl': sum(r['actual_net_pnl'] for r in rows),
        },
        'limitations': [
            'Peak is a hindsight descriptive maximum of completed held closes, not an executable exit signal.',
            'Initial intrabar High is excluded; no precise fill time or intrabar excursion is inferred.',
            'Hypothetical liquidation at a close subtracts the declared exit fee only; it is not an order-fill counterfactual.',
            'Giveback can exceed 100 percent if a positive peak becomes a loss, or be negative after an upward exit gap.',
            'USD sums mix different position sizes and wealth paths; they are not additive strategy improvement estimates.',
            'Open cycles are separate and do not count as realized trades or closed-profit concentration.',
            'Trading-session and calendar-day duration includes entry and exit days; held_sessions counts days with a held completed-close observation, which can exclude an open-of-day exit.',
        ],
    }


def account_ref(reference, payload):
    value = dict(payload['evaluation_identity'])
    value['candidate'] = CandidateKey(**value['candidate'])
    return AccountRunRef(reference, EvaluationIdentity(**value))


def diagnostics(payloads, references):
    root = ROOT/'research/S017/assets/runs/EX004_20261028/diagnostics'
    research, result = RUN.context(), {}
    for subject, control, question in COMPARISONS:
        key = subject+'_vs_'+control
        path = root/(key+'.json')
        diagnosis = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
            account_ref(references[control], payloads[control]),
            account_ref(references[subject], payloads[subject]),
            EvaluationWindow('DEV_2019_2025', date(2019,1,2), date(2025,12,31))))
        raw = diagnosis.to_dict()
        RUN.save(path, raw)
        evidence = RUN.material(research, 'diagnosis-'+key, path)
        summaries = []
        for index, pnl in enumerate(diagnosis.pnl_breakdown):
            summaries.append({'evaluation_id': pnl.evaluation_id,
                'opening_equity': pnl.daily[0].opening_equity if pnl.daily else None,
                'closing_equity': pnl.daily[-1].closing_equity if pnl.daily else None,
                'entry': sum(p.entry for p in pnl.daily), 'holding': sum(p.holding for p in pnl.daily),
                'exit': sum(p.exit for p in pnl.daily), 'fees': sum(p.fees for p in pnl.daily),
                'residual': sum(p.residual for p in pnl.daily),
                'annual': raw['pnl_breakdown'][index]['annual']})
        result[key] = {'status': diagnosis.status.value, 'issues': list(diagnosis.issues),
            'baseline': control, 'alternative': subject, 'question': question,
            'raw_path': path.relative_to(ROOT).as_posix(), 'evidence': evidence.to_dict(),
            'pnl_summary': summaries, 'cycle_path_rows': len(diagnosis.path_comparison),
            'daily_path_rows': len(diagnosis.daily_paths), 'reconciliation': raw['reconciliation'],
            'partial_year_note': 'Original platform flag retained; Jan 1 comparison may label a full trading year partial.',
            'attribution': 'One configured dimension changes, but complete account paths and later opportunities can change; this is accounting evidence, not proof of market causation.'}
        print('DIAGNOSIS', key, diagnosis.status.value, flush=True)
    return result


def main():
    dependency_hashes = {p:sha256(p.read_bytes()).hexdigest() for p in (PRIOR_SOURCE, PRIOR_RUNNER_SOURCE)}
    new_payloads, new_refs = load_subset(WORK, EXPERIMENT, tuple(RUN.configurations()), exact_manifest=True)
    controls, control_refs = load_subset(PRIOR_WORK, PRIOR_EXPERIMENT, ('C0000', 'C0001', 'C0002'))
    extra_experiment = ExperimentRef('S017', 'EX003_20261028')
    extra, extra_refs = load_subset(extra_experiment.resolve(ROOT), extra_experiment, ('C0013',))
    controls.update(extra)
    control_refs.update(extra_refs)
    payloads, references = {**controls, **new_payloads}, {**control_refs, **new_refs}
    contract_check = verify_contracts(payloads)
    path_check = PRIOR.verify_hold_path(payloads)
    summary = {key: PRIOR.summarize(value) for key,value in new_payloads.items()}
    control_summary = {key: PRIOR.summarize(value) for key,value in controls.items()}
    giveback = {key:cycle_giveback(payload) for key,payload in payloads.items()}
    diagnosis = diagnostics(payloads, references)
    if any(sha256(p.read_bytes()).hexdigest() != digest for p,digest in dependency_hashes.items()):
        raise RuntimeError('reused analysis dependency changed during computation')
    okay = path_check['status'] == 'PASS' and all(value['status'] == 'COMPUTED' for value in diagnosis.values())
    output = {
        'schema': 's017-stage2-ex004-analysis/v1', 'status': 'PASS' if okay else 'FAIL',
        'scope': '2019-01-02 through 2025-12-31 development only; stage two',
        'analysis_dependencies': [{'path':p.relative_to(ROOT).as_posix(), 'sha256':digest}
                                  for p,digest in dependency_hashes.items()],
        'reused_functions': ['summarize', 'verify_hold_path', '_validate_run'],
        'module_isolation': 'EX002 and EX004 runners have separate importlib identities; output belongs to EX004.',
        'source_accounts': {key:ref.to_dict() for key,ref in references.items()},
        'control_usage': {
            'C0000':'EX002 executable buyhold, no new replay or registration',
            'C0001':'EX002 slow direction baseline, no new replay or registration',
            'C0002':'EX002 65-bar breakout and 26-bar channel exit, no new replay or registration',
            'C0013':'EX003 prior highest-return timing expression; selected using known development results',
        },
        'semantics': {
            'annual_return':'year-end equity divided by preceding session equity; initial cash only for first year',
            'rolling_return':'252 retained sessions, 21-session step; incomplete trailing windows excluded',
            'excess_return':'candidate minus embedded buyhold on identical continuous-account slices',
            'holding':'positive-quantity observation share, not elapsed wall-clock exposure',
            'drawdown':'slice-opening and inherited full-account peak reported separately, positive magnitudes',
            'independence':'all accounts use the same development pool; overlapping windows are not independent',
            'economic_acceptance':'descriptive comparisons; no automatic acceptance or stage advancement',
        },
        'contract_comparability': contract_check, 'buy_hold_path_verification': path_check,
        'accounts': summary, 'controls': control_summary, 'cycle_giveback': giveback, 'diagnostics': diagnosis,
    }
    RUN.save(WORK/'others/analysis.json', output)
    if not okay:
        raise RuntimeError('analysis contains failed buyhold-path check or public account diagnosis')
    print('EX004 ANALYSIS PASS', WORK/'others/analysis.json', flush=True)


if __name__ == '__main__':
    main()
