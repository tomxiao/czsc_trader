"""Explicit event denominators and fixed-account contrasts, not strategy search."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '1'
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, get_research_overview, create_research_context, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef, ExperimentRef, ExecutionResources, MaterialEvidenceWrite

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[3]


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def overview():
    value = get_research_overview(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'))
    save(HERE / 'others/overview_start.json', value.to_dict())
    print('OVERVIEW_SAVED', flush=True)


def ratios(group, value_column):
    amounts = group[value_column].astype(float)
    excluded = ~group.permission.astype(bool)
    loss = amounts < 0
    win = amounts > 0
    negative = float(-amounts[loss].sum())
    positive = float(amounts[win].sum())
    caught = float(-amounts[loss & excluded].sum())
    missed = float(amounts[win & excluded].sum())
    return {'events': len(group), 'allowed': int((~excluded).sum()),
            'loss_events': int(loss.sum()), 'win_events': int(win.sum()),
            'loss_events_rejected': int((loss & excluded).sum()),
            'win_events_rejected': int((win & excluded).sum()),
            'negative_amount_yuan': negative, 'positive_amount_yuan': positive,
            'loss_amount_rejected_yuan': caught, 'profit_amount_missed_yuan': missed,
            'loss_amount_rejected_fraction': caught / negative if negative else None,
            'profit_amount_missed_fraction': missed / positive if positive else None,
            'allowed_net_amount_yuan': float(amounts[~excluded].sum())}


def events():
    refs = read(HERE / 'protocols/plan.json')['sources']
    event = pd.read_csv(EvidenceRef.from_dict(refs['events']).resolve(ROOT))
    event = event[event.horizon.eq(3) & event.status.eq('CLOSED')]
    features = pd.read_csv(EvidenceRef.from_dict(refs['price_features']).resolve(ROOT))
    event = event.merge(features[['position', 'r5']], on='position', validate='one_to_one')
    predictions = pd.read_csv(HERE / 'others/model_predictions.csv')
    g = predictions[predictions.ready].merge(event, on=['date', 'position'], validate='many_to_one')
    rows = []
    for (family, lag), arm in g.groupby(['family', 'lag'], sort=False):
        cohorts = {'all_ready_closed': arm, 'old_common_positions': arm[arm.position.ge(100)]}
        cohorts.update({f'fold_{lo}_{hi}': arm[arm.position.between(lo, hi)]
                        for lo, hi in ((100, 183), (184, 267), (268, 351), (352, 433))})
        cohorts.update({'prior5_up': arm[arm.r5.gt(0)], 'prior5_down': arm[arm.r5.lt(0)], 'prior5_zero': arm[arm.r5.eq(0)]})
        for cohort, sub in cohorts.items():
            for label in ('entry_net', 'net'):
                rows.append({'family': family, 'lag': int(lag), 'cohort': cohort, 'label': label, **ratios(sub, label)})
    save(HERE / 'others/event_metrics.json', {'rows': rows,
        'definition': 'One hypothetical 100000 yuan event per signal session; entry_net deducts actual buy fee only, net deducts both actual fees. Closed three-day common events only; overlapping money totals are not continuous-account PnL.',
        'unavailable_event_policy': 'UNFILLED/UNRESOLVED/end-open excluded from closed comparison, separately counted.',
        'all_event_status_counts': pd.read_csv(EvidenceRef.from_dict(refs['events']).resolve(ROOT)).query('horizon == 3').status.value_counts().to_dict()})
    g.to_csv(HERE / 'others/event_cohort.csv', index=False)
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))
    ex = ExperimentRef('S015', HERE.name)
    published = {}
    for name in ('model_predictions.csv', 'training_summary.json', 'event_metrics.json', 'event_cohort.csv'):
        path = HERE / 'others' / name
        ref = publish_evidence(ctx, MaterialEvidenceWrite(ex, path.stem, path.read_bytes(), 'text/csv' if path.suffix == '.csv' else 'application/json', path.suffix[1:]))
        published[name] = ref.to_dict()
    save(HERE / 'others/event_refs.json', published)
    print(json.dumps([row for row in rows if row['cohort'] == 'all_ready_closed' and row['lag'] == 1], ensure_ascii=False), flush=True)


def accounts():
    results = read(HERE / 'others/results.json')
    output = []
    for row in results['rows']:
        cid = row['candidate_id']
        for window, metrics in row['runs'].items():
            a = pd.read_csv(HERE / f'others/{cid}_{window}_account_daily.csv')
            d = pd.read_csv(HERE / f'others/{cid}_{window}_decisions.csv')
            fills = pd.read_csv(HERE / f'others/{cid}_{window}_fills.csv')
            exposure = a.quantity * a.close / a.equity
            years = []
            for year, group in a.groupby(a.date.str[:4]):
                idx = group.index[0]
                start = 100000. if idx == 0 else float(a.equity.iloc[idx-1])
                eq = np.r_[start, group.equity.astype(float)]
                years.append({'year': year, 'net_return': float(eq[-1]/start-1), 'dd': float((1-eq/np.maximum.accumulate(eq)).max()), 'net_yuan': float(eq[-1]-start)})
            blocked = d.permission.eq(1) & d.intent_age.gt(1)
            buys = fills[fills.side.eq('BUY')]
            sizes = buys.groupby('cycle_id').size()
            output.append({'candidate_id': cid, 'window': window, 'parameters': row['parameters'],
                           'average_close_exposure': float(exposure.mean()), 'held_sessions': int(a.quantity.gt(0).sum()),
                           'ready_permission_sessions': int(d.permission.eq(1).sum()), 'permission_during_active_intent_sessions': int(blocked.sum()),
                           'blocked_meaning': 'Permission while intent age>1; same-account unavailable slot, not a counterfactual lost trade. Exit-intent sessions disallow reentry independently.',
                           'buy_fills': len(buys), 'multi_buy_cycles': int((sizes > 1).sum()), 'years': years, 'metrics': metrics})
    by = {(r['parameters']['family'], r['parameters']['lag']): r for r in results['rows']}
    contrasts = []
    for base, variant in ((('B', 1), ('BF', 1)), (('BP', 1), ('BPF', 1)), (('B', 1), ('BP', 1)), (('BF', 1), ('BPF', 1)), (('BF', 1), ('BF', 3)), (('BPF', 1), ('BPF', 3))):
        for window in ('full', 's011_common'):
            b = by[base]['runs'][window]; v = by[variant]['runs'][window]
            contrasts.append({'base': list(base), 'variant': list(variant), 'window': window,
                              'net_return_delta_pp': 100*(v['net_return']-b['net_return']), 'dd_delta_pp': 100*(v['dd']-b['dd']),
                              'fees_delta_yuan': v['fees']-b['fees'], 'closed_delta': v['closed']-b['closed']})
    save(HERE / 'others/account_diagnostics.json', {'accounts': output, 'direct_contrasts': contrasts})
    print(json.dumps(contrasts, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('overview', 'events', 'accounts'))
    globals()[parser.parse_args().mode]()
