"""Split prior-close/open gap from RTH before known-state accounting; no replay."""
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import s017_ex062_state_audit as auth

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'research/S017/experiments/EX072_20261102'


def at(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def main():
    records = auth.read(WORK / 'others/all_accounts.json')
    family = auth.read(WORK / 'others/search_trials.json')
    rows = {r['candidate_id']: r for r in family['unique_results']}
    results = {}
    for cid in ('C0338', 'C0342', 'C0356'):
        payload, proof = auth.authenticated(records[cid])
        run = payload['runs']['candidate']
        decisions = {at(d['execution_end']): d for d in run['decisions']}
        fills = defaultdict(list)
        for fill in run['fills']:
            fills[at(fill['interval_end'])].append(fill)
        metrics = rows[cid]['metrics']
        bars = {at(b['Date']): b for b in payload['audit_inputs']['bars']}
        peak = at(metrics['max_drawdown_path']['peak'])
        trough = at(metrics['max_drawdown_path']['trough'])
        groups = defaultdict(lambda: dict(n=0, net_usd=0., net_log=0., fees=0.))
        previous_equity = float(payload['request']['initial_cash'])
        previous_quantity = 0
        previous_cash = previous_equity
        previous_phase, previous_route = 'FLAT', 'FLAT'
        points = sorted(run['account_points'], key=lambda p: at(p['time']))
        for point in points:
            stamp = at(point['time'])
            d = decisions[stamp]
            f = auth.facts(d)
            assert (f['held'] == 'True') == (previous_quantity > 0)
            actual_fills = fills[stamp]
            sides = {v['side'] for v in actual_fills}
            assert len(sides) <= 1
            if previous_quantity > 0:
                phase = 'ACCEPTED' if f['accepted_active'] == 'True' else 'INITIAL'
                transition = 'EXIT' if 'SELL' in sides else 'HOLD'
                mf = f['entry_multi_full'] == 'True'
                u = f['entry_u'] == 'True'
            elif 'BUY' in sides:
                phase, transition = 'INITIAL', 'ENTRY'
                mf = f['current_multi_full'] == 'True'
                u = f['current_u'] == 'True'
            else:
                phase, transition, mf, u = 'FLAT', 'FLAT', False, False
            route = 'MF' if mf else 'NON_MF_U' if u else 'NON_MF_OTHER'
            if phase == 'FLAT':
                route = 'FLAT'
            equity = float(point['equity'])
            fees = sum(v['fees'] for v in actual_fills)
            opening_equity = previous_cash + previous_quantity * bars[stamp]['Open']
            legs = (
                ('CLOSE_TO_OPEN', previous_phase, previous_route, 'GAP',
                 opening_equity - previous_equity, math.log(opening_equity / previous_equity), 0.),
                ('OPEN_TO_END', phase, route, transition,
                 equity - opening_equity, math.log(equity / opening_equity), fees),
            )
            periods = ['ALL', str(stamp.year)]
            if peak < stamp <= trough:
                periods.append('MAX_DD')
            for leg, leg_phase, leg_route, leg_transition, delta, growth, leg_fees in legs:
                for period in periods:
                    for dimension, value in (
                        ('TOTAL', 'TOTAL'), ('PHASE', leg_phase), ('ROUTE', leg_route),
                        ('PHASE_ROUTE', leg_phase + '_' + leg_route),
                        ('PHASE_TRANSITION', leg_phase + '_' + leg_transition),
                        ('LEG', leg),
                    ):
                        group = groups[(period, dimension, value)]
                        group['n'] += 1
                        group['net_usd'] += delta
                        group['net_log'] += growth
                        group['fees'] += leg_fees
            previous_equity = equity
            previous_quantity = point['quantity']
            previous_cash = point['cash']
            assert abs(previous_cash + previous_quantity * bars[stamp]['Close'] - equity) < 1e-6
            previous_phase = phase if previous_quantity > 0 else 'FLAT'
            previous_route = route if previous_quantity > 0 else 'FLAT'
        assert len(points) == 6490
        assert abs(groups[('ALL', 'TOTAL', 'TOTAL')]['net_usd'] - metrics['trade_pnl']['closed_net_pnl']) < 1e-6
        assert abs(groups[('ALL', 'TOTAL', 'TOTAL')]['net_log'] - math.log(metrics['ending_equity'] / 100000)) < 1e-10
        assert abs(groups[('MAX_DD', 'TOTAL', 'TOTAL')]['net_log'] - math.log1p(-metrics['bar_max_drawdown'])) < 1e-10
        for period in ('ALL', '2024', '2025', 'MAX_DD'):
            total = groups[(period, 'TOTAL', 'TOTAL')]
            for dimension in ('PHASE', 'ROUTE', 'PHASE_ROUTE', 'PHASE_TRANSITION', 'LEG'):
                selected = [v for (p, d, _), v in groups.items() if p == period and d == dimension]
                assert sum(v['n'] for v in selected) == total['n']
                assert abs(sum(v['net_usd'] for v in selected) - total['net_usd']) < 1e-6
                assert abs(sum(v['net_log'] for v in selected) - total['net_log']) < 1e-10
        results[cid] = dict(
            public_proof=proof, metrics=metrics, max_dd_window=[str(peak), str(trough)],
            accounting=[dict(period=k[0], dimension=k[1], group=k[2], **v) for k, v in sorted(groups.items())],
        )
        del payload, run, points, decisions, fills
        print('ACCOUNT_CLASSIFIED', cid, flush=True)
    out = dict(
        status='PASS_EXACT_GAP_SPLIT_KNOWN_STATE_ACCOUNTING',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        authentication_helper_sha256=auth.digest(Path(auth.__file__)),
        public_family_sha256=auth.digest(WORK / 'others/search_trials.json'), accounts=results,
        new_account_computes=0, new_strategy_replays=0, new_horizon_labels=0, sealed_test_access=False,
        supersedes='v1 assigned the complete prior-close/end move to current decision phase; '
        'v2 assigns close/open price gaps to previous live phase and RTH/fills/fees to current known phase.',
        scope='Known-at-execution risk state partitions actual interval equity deltas/log growth. '
        'MAX_DD is each existing account hindsight descriptive window, not a trading rule. '
        'Every interval first marks previous cash/quantity to current Open; this CLOSE_TO_OPEN '
        'leg uses the previous activated phase, so a new first-RTH acceptance cannot claim the already-realized overnight gap. '
        'OPEN_TO_END uses current decision phase and includes actual fills/fees. INITIAL/ACCEPTED include transitions. '
        'Dollar/log amounts describe the existing cash path, not avoidable loss, standalone component alpha, '
        'counterfactual strategy performance, or independent samples.',
    )
    target = ROOT / '.tmp/s017_research_diagnostic_v2_20261102.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')
    print('DIAGNOSTIC_PASS', auth.digest(target), flush=True)
    for cid, account in results.items():
        print(json.dumps(dict(candidate=cid, rows=[r for r in account['accounting']
            if r['period'] in ('ALL', 'MAX_DD') and r['dimension'] in ('PHASE', 'ROUTE')]), ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
