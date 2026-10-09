"""Conditional entry information and actual policy paths, not causal trade labels."""
from datetime import date
from hashlib import sha256
import importlib.util
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import StrategyInit, TradableWindow
from common import SOURCE, CACHE, RUNS, PROTOCOLS, context, read, write, cache_read
from diagnose import rows


def expression():
    plan = read(PROTOCOLS / 'initial_plan.json')
    for name, expected in plan['source_files'].items():
        assert sha256((SOURCE.parent / name).read_bytes()).hexdigest() == expected
    package = types.ModuleType('_s013_score_audit')
    package.__path__ = [str(SOURCE / 'strategies')]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(package.__name__ + '.confirmed_range',
                                                 SOURCE / 'strategies/confirmed_range.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def inspect(bound):
    research = context(1)
    instance = research.runtime.create(StrategyInit(source=bound.strategy,
        tradable_window=TradableWindow(date(2020, 1, 2), date(2026, 9, 30)),
        data_dir=CACHE / ('inspect-' + bound.strategy.candidate_id)))
    binding = bound.input_bindings['full']
    instance.prepare_data(binding=binding)
    daily = research.data.fetch(binding.plan.requests['daily'], prepared=binding.prepared).dataframe
    return daily, instance.inspect_signals()


def main():
    module = expression()
    control_rows = [row for row in rows() if not row['parameters']['confirmation']['enabled']
                    and row['parameters']['bear']['acf_min'] is not None]
    prior_path = RUNS / 'score_attribution.json'
    prior = read(prior_path) if prior_path.exists() else None
    conditional, labels, opportunities = [], [], []
    if prior:
        conditional, opportunities = prior['conditional'], prior['original_opportunities']
    for row in (() if prior else control_rows):
        bound, result = cache_read(CACHE / f'{row["candidate_id"]}.pkl.gz')
        daily, history = inspect(bound)
        raw, normalized = module.confirmation_features(daily, module.components(daily).acf1, 120)
        normalized = normalized.reindex(history.index)
        assert np.isfinite(normalized.to_numpy()).all()
        score = normalized.mean(axis=1)
        eligible = history.signal_reason.eq('entry')
        selected = normalized.loc[eligible].copy()
        selected['score'] = score.loc[eligible]
        selected['regime'] = history.loc[eligible, 'regime']
        selected['signal_date'] = selected.index
        selected['parent'] = row['parent']
        selected['control'] = row['candidate_id']
        selected['year'] = selected.index.year
        # Descriptive next-open labels only. They never enter the score or strategy.
        execution = result.execution_data.execution_daily.copy()
        execution['dt'] = pd.to_datetime(execution.dt).dt.normalize()
        execution = execution.set_index('dt').sort_index()
        replay = result.runs[0].signals.decisions
        following = dict(zip(pd.to_datetime(replay.signal_date), pd.to_datetime(replay.valid_session), strict=True))
        selected['execution_date'] = selected.index.map(following)
        opens = execution.open.astype(float)
        for horizon in (1, 3, 5):
            price_returns = opens.shift(-horizon) / opens - 1
            selected[f'next_open_return_{horizon}'] = selected.execution_date.map(price_returns)
        for key, group in selected.groupby(['year', 'regime'], observed=True):
            for bucket, part in [('score_below_zero', group.loc[group.score < 0]),
                                 ('score_at_or_above_zero', group.loc[group.score >= 0])]:
                item = {'parent': row['parent'], 'control': row['candidate_id'], 'year': int(key[0]),
                        'route': key[1], 'bucket': bucket, 'signal_opportunities': len(part)}
                for horizon in (1, 3, 5):
                    values = part[f'next_open_return_{horizon}'].dropna()
                    item[f'valid_labels_{horizon}'] = len(values)
                    item[f'mean_price_return_{horizon}'] = None if values.empty else float(values.mean())
                conditional.append(item)
        opportunities.append({'parent': row['parent'], 'count': len(selected),
            'score_component_correlations': normalized.loc[eligible].corr().to_dict(),
            'identity': result.runs[0].identity.to_dict()})
        labels.append(selected.reset_index(drop=True))
    if not prior:
        label_frame = pd.concat(labels, ignore_index=True)
        label_frame.to_csv(RUNS / 'conditional_opportunities.csv', index=False)
    else:
        label_frame = pd.read_csv(RUNS / 'conditional_opportunities.csv')
    path_summaries = [] if not prior else prior['actual_paths']
    already = {row['candidate_id'] for row in path_summaries}
    for row in rows():
        if not row['parameters']['confirmation']['enabled'] or row['candidate_id'] in already:
            continue
        bound, _ = cache_read(CACHE / f'{row["candidate_id"]}.pkl.gz')
        _, history = inspect(bound)
        summaries = []
        for key, group in history.groupby([history.index.year, history.regime], observed=True):
            active = group.loc[group.confirmation_opportunity]
            summaries.append({'year': int(key[0]), 'route': key[1], 'opportunities': len(active),
                              'rejected': int(active.signal_reason.eq('confirmation_rejected').sum()),
                              'entries': int(group.signal_reason.eq('entry').sum())})
        assert not history.signal_reason.eq('cooldown').any()
        contextual = []
        if 'confirmation_exit_context' in history:
            for key, group in history.groupby([history.index.year, history.confirmation_exit_context], observed=True):
                active = group.loc[group.confirmation_opportunity]
                contextual.append({'year': int(key[0]), 'last_signal_exit': key[1],
                    'opportunities': len(active), 'rejected': int(active.signal_reason.eq('confirmation_rejected').sum()),
                    'entries': int(group.signal_reason.eq('entry').sum())})
        waits, rejected_streak = [], 0
        for reason in history.signal_reason:
            if reason == 'confirmation_rejected':
                rejected_streak += 1
            elif reason == 'entry':
                if rejected_streak:
                    waits.append(rejected_streak)
                rejected_streak = 0
        path_summaries.append({'candidate_id': row['candidate_id'], 'annual_route': summaries,
            'exit_context': contextual, 'blocked_opportunities_before_entry': waits,
            'still_blocked_opportunities_at_tail': rejected_streak})
    write(RUNS / 'score_attribution.json', {'status': 'PASS', 'conditional': conditional,
        'successful_configurations_covered': len(rows()),
        'original_opportunities': opportunities, 'actual_paths': path_summaries,
        'original_label_rows': len(label_frame),
        'unique_original_signal_dates': int(label_frame.signal_date.nunique()),
        'label_definition': 'T+1 open to open h sessions later; truncated missing tails retained; descriptive price label, not account return',
        'limits': ['known developer pool', 'old opportunities change under a new policy',
                   'original entry labels overlap across ten controls and are not independent samples',
                   'exit context and blocked opportunity counts describe signal policy, not actual fill-cycle waiting',
                   'blocked original trade profit is not an independent causal contribution', 'score is not a success probability']})
    print({'status': 'PASS', 'conditional_opportunities': len(label_frame), 'scored_paths': len(path_summaries)}, flush=True)


if __name__ == '__main__':
    main()
