"""Rebuild the stage-three search union without changing sealed experiments."""
from pathlib import Path
from hashlib import sha256
import json
import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive
from research_experiment import load_experiment, load_experiment_input

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / '.tmp/s011-stage3-union'
ROUNDS = (15, 23, 22, 24, 25)
FIELDS = ('tail_weight', 'spx_weight', 'entry', 'exit', 'max_days', 'lookback', 'premium')


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records, contracts, round_counts = [], [], []
    for number in ROUNDS:
        root = REPO / f'experiments/S011/20260930_S011_EX{number}'
        validate_experiment_archive(root)
        loaded = load_experiment(root)
        receipt = json.loads((root / 'artifacts/execution_receipt.json').read_text())['receipt_sha256']
        load_experiment_input(root / 'artifacts', expected_receipt_sha256=receipt)
        contracts.append({'experiment': root.name, 'receipt': receipt,
            'manifest_sha256': sha256((root / 'experiment_manifest.json').read_bytes()).hexdigest(),
            'source_sha256': loaded.binding.source_sha256})
        table = pd.read_csv((REPO / 'experiments/S011/20260930_S011_EX16/artifacts/qualification.csv')
                            if number == 15 else root / 'artifacts/trials.csv', float_precision='round_trip')
        parameters = json.loads((root / 'artifacts/trial_parameters.json').read_text())
        prior_keys = {r['parameter_key'] for r in records}
        before = len(prior_keys)
        for row in table.to_dict('records'):
            trial = int(row['trial'])
            path = root / f'artifacts/trials/T{trial:03}'
            account = pd.read_csv(path / 'account_daily.csv.gz', float_precision='round_trip')
            key = json.dumps(parameters[trial], sort_keys=True)
            behavior = sha256(account[['date', 'cash', 'quantity', 'equity']].to_csv(index=False).encode()).hexdigest()
            records.append({**row, **parameters[trial], 'experiment': f'EX{number}',
                'reference': f'EX{number}T{trial:03}', 'parameter_key': key, 'account_key': behavior,
                'end_equity': float(account.equity.iloc[-1]), 'prior_parameter': key in prior_keys})
        round_counts.append({'experiment': f'EX{number}', 'evaluations': len(table),
            'qualified_evaluations': int(table.qualified.sum()),
            'new_parameters': len({r['parameter_key'] for r in records}) - before})
    all_rows = pd.DataFrame(records)
    for key, group in all_rows.groupby('parameter_key'):
        assert group.account_key.nunique() == 1, ('same parameters changed account', key)
    unique = all_rows.drop_duplicates('parameter_key').copy()
    eligible = unique.loc[unique.qualified].copy()
    def dominated(row):
        return ((eligible.cagr >= row.cagr) & (eligible.drawdown >= row.drawdown) &
                ((eligible.cagr > row.cagr) | (eligible.drawdown > row.drawdown))).any()
    pareto = eligible.loc[[not dominated(r) for r in eligible.itertuples()]].copy()
    behavior_frontier = pareto.drop_duplicates('account_key')
    all_rows.to_csv(OUTPUT / 'all_evaluations.csv', index=False)
    unique.to_csv(OUTPUT / 'unique_parameters.csv', index=False)
    pareto.to_csv(OUTPUT / 'pareto_parameters.csv', index=False)
    behavior_frontier.to_csv(OUTPUT / 'pareto_accounts.csv', index=False)
    fixed = []
    for row in behavior_frontier.to_dict('records'):
        ex = row['experiment']
        root = REPO / f'experiments/S011/20260930_S011_{ex}'
        trial_dir = root / f'artifacts/trials/T{int(row["trial"]):03}'
        origin = row['reference']
        if ex == 'EX23':
            source_trials = json.loads((root / 'artifacts/source_trials.json').read_text())
            origin = source_trials[int(row['trial'])]['candidate_id']
        fixed.append({'identity': 'S011-' + origin, 'evidence_reference': row['reference'],
            'candidate_id': origin, 'strategy_id': 'S011', 'path_base': 'repository_root',
            'source_root': (root / 'runtime/strategy_runtime').relative_to(REPO).as_posix(),
            'strategy_payload': json.loads((trial_dir / 'payload.json').read_text()),
            'strategy_identity': json.loads((trial_dir / 'identity.json').read_text()),
            'metrics': {k: row[k] for k in ('cagr', 'drawdown', 'closed_trades', 'frequency', 'end_equity')},
            'equivalent_parameter_references': pareto.loc[pareto.account_key.eq(row['account_key']), 'reference'].tolist()})
    (OUTPUT / 'frontier_configurations.json').write_text(json.dumps({
        'status': 'DEVELOPMENT_FRONTIER_NOT_STAGE_FOUR_REPRESENTATIVES',
        'configurations': fixed, 'stage_four_complete': False,
        'cio_candidate_package_created': False, 'freeze_or_deployment_authorized': False}, indent=2) + '\n', encoding='utf-8')
    progress = []
    optuna = all_rows.loc[all_rows.experiment.eq('EX23')]
    for end in range(48, 385, 48):
        feasible = optuna.iloc[:end].loc[lambda x: x.qualified]
        progress.append({'through': end, 'qualified': len(feasible),
                         'best_cagr': float(feasible.cagr.max()), 'best_drawdown': float(feasible.drawdown.max())})
    evolution, previous_accounts, included = [], set(), []
    for number in ROUNDS:
        included.append(f'EX{number}')
        prefix = all_rows.loc[all_rows.experiment.isin(included) & all_rows.qualified].drop_duplicates('account_key')
        current = prefix.loc[[not ((prefix.cagr >= row.cagr) & (prefix.drawdown >= row.drawdown) &
            ((prefix.cagr > row.cagr) | (prefix.drawdown > row.drawdown))).any() for row in prefix.itertuples()]]
        keys = set(current.account_key)
        evolution.append({'through_experiment': f'EX{number}', 'frontier_accounts': len(keys),
            'new_frontier_accounts': len(keys - previous_accounts), 'frontier_references': current.reference.tolist()})
        previous_accounts = keys
    summary = {'rounds': round_counts, 'frontier_evolution': evolution,
        'evaluations_excluding_inherited_duplicates_and_technical_replays': len(all_rows),
        'unique_parameters': len(unique), 'distinct_accounts': unique.account_key.nunique(),
        'qualified_parameters': len(eligible), 'qualified_accounts': eligible.account_key.nunique(),
        'pareto_parameters': len(pareto), 'pareto_accounts': len(behavior_frontier),
        'frontier': behavior_frontier[['reference', *FIELDS, 'cagr', 'drawdown', 'closed_trades', 'frequency', 'end_equity']].to_dict('records'),
        'optuna_progress': progress, 'archives': contracts,
        'development_only': True, 'stage_four_complete': False,
        'count_warning': 'Parameter configurations of one expression, not independent economic hypotheses; repeated account behaviors are counted separately only in evaluation totals.'}
    (OUTPUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    # Paired controls identify signal versus execution changes without altering trades.
    controls = {'old': (23, 54), 'lower_entry': (22, 3), 'tighter_price': (24, 3), 'earlier_exit': (24, 7)}
    ledgers = {}
    for label, (ex, trial) in controls.items():
        folder = REPO / f'experiments/S011/20260930_S011_EX{ex}/artifacts/trials/T{trial:03}'
        ledgers[label] = {name: pd.read_csv(folder / f'{name}.csv.gz')
                          for name in ('decisions', 'orders', 'fills', 'trades')}
    paired = []
    order_rows = []
    for left, right in (('old', 'lower_entry'), ('lower_entry', 'tighter_price'), ('tighter_price', 'earlier_exit')):
        a, b = ledgers[left], ledgers[right]
        changed = a['decisions'].target_position.ne(b['decisions'].target_position)
        fa, fb = a['fills'], b['fills']
        buy_a = set(pd.to_datetime(fa.loc[fa.side.eq('BUY'), 'fill_time']).dt.strftime('%Y-%m-%d'))
        buy_b = set(pd.to_datetime(fb.loc[fb.side.eq('BUY'), 'fill_time']).dt.strftime('%Y-%m-%d'))
        def cycle_result(frames, dates):
            fills = frames['fills'].copy()
            fills['day'] = pd.to_datetime(fills.fill_time).dt.strftime('%Y-%m-%d')
            ids = fills.loc[fills.side.eq('BUY') & fills.day.isin(dates), 'cycle_id']
            fills = fills.loc[fills.cycle_id.isin(ids)].copy()
            fills['net_cashflow'] = fills.quantity * fills.price * fills.side.map({'SELL': 1., 'BUY': -1.}) - fills.fees
            return fills.groupby('cycle_id').net_cashflow.sum().tolist()
        pair = {'from': left, 'to': right, 'changed_target_dates': a['decisions'].loc[changed, 'signal_date'].tolist(),
            'removed_buy_dates': sorted(buy_a - buy_b), 'added_buy_dates': sorted(buy_b - buy_a),
            'removed_cycle_net_cashflows': cycle_result(a, buy_a - buy_b),
            'added_cycle_net_cashflows': cycle_result(b, buy_b - buy_a)}
        paired.append(pair)
        for label in (left, right):
            orders = ledgers[label]['orders'].copy()
            orders['comparison'] = left + ' -> ' + right
            orders['configuration'] = label
            order_rows.append(orders)
    (OUTPUT / 'paired_changes.json').write_text(json.dumps(paired, indent=2) + '\n', encoding='utf-8')
    pd.concat(order_rows, ignore_index=True).to_csv(OUTPUT / 'paired_orders.csv', index=False)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
