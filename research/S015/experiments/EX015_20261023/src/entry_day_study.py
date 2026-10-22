"""One fixed PR versus AllDaily contrast for entry-to-close signed PnL."""
# ruff: noqa: E402
import argparse
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import EvidenceRef, ExecutionResources, ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparedDataRef
from trading_execution_engine import MarketExecutionRules, DailyQuote, OrderSpec, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parents[1]
EX = ExperimentRef('S015', HERE.name)
FOLDS = ((100, 184), (184, 268), (268, 352), (352, 434))
COLS = {
    'PR': ['base_r1', 'base_r5', 'base_vol20', 'pressure', 'calm_range'],
    'AllDaily': ['base_r1', 'base_r5', 'base_vol20', 'pressure', 'calm_range',
                 'body', 'trend20', 'location', 'lower_wick', 'efficiency5'],
}


def read(p):
    return json.loads(p.read_bytes())


def save(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))


def material(p):
    return publish_evidence(context(), MaterialEvidenceWrite(EX, p.stem, p.read_bytes(),
        {'.py': 'text/x-python', '.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown'}[p.suffix], p.suffix[1:]))


def sources():
    old = ROOT / 'research/S015/experiments'
    allrefs = [EvidenceRef.from_dict(v) for v in read(old/'EX011_20261023/others/published_refs.json')['references']]
    wanted = {'features': ('features_reconstructed', 'EX011_20261023'),
              'inputs': ('input_facts', 'EX010_20261023'), 'old_labels': ('event_labels', 'EX010_20261023'),
              'old_source': ('component_study', 'EX010_20261023')}
    refs = {k: next(r for r in allrefs if (r.name, r.experiment.experiment_id) == pair) for k, pair in wanted.items()}
    row = next(r for r in read(ROOT/'research/S015/assets/runs/EX003_20261021/strategy_study/grid_results.json') if r['candidate_id'] == 'C0031')
    refs['account'] = EvidenceRef.from_dict(row['evidence'])
    refs['diagnosis'] = EvidenceRef.from_dict(read(old/'EX014_20261023/report_ref.json')['report'])
    for ref in refs.values():
        ref.resolve(ROOT)
    return refs


def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    refs = sources()
    protocol = {
        'authorization': '同意，请自主完成这项阶段二固定对照，重点说明能否识别入场当天的亏损，以及会错过多少盈利。',
        'mandate': 'MANDATE/3', 'predecessor': 'EX014 diagnosis and COMPONENTS/6',
        'question': 'PR versus AllDaily: can existing daily information distinguish actual entry-to-close losses while retaining gains?',
        'data': 'Original434 decision dates2025-01-02..2026-10-21 plus75 warmup; no new input/date/holdout/minute feature. Existing prepared adjusted/raw daily and authenticated509-row feature matrix only.',
        'label': 'Each event independent100000cash. Exact old1% limit sizing, market rules, T+1 public resolve_fill. Gross y=quantity*(T+1close-fillprice)/100000. Record buyfee and net_entry=y-buyfee/100000. No sell, no next-day return, no intraday-low proxy.',
        'coverage': 'No next session RIGHT_CENSORED; no buy fill BUY_UNFILLED; missing data explicit error. Neither becomes zero. Exact zero PnL retained as neutral. One fewer boundary exclusion than oldh1 because no T+2 exit is required.',
        'models': COLS, 'ridge': 'alpha10, intercept unpenalized, training-only standardization; one paired contrast. Training mean is a no-information diagnostic benchmark only.',
        'folds': FOLDS, 'purge': 'Actual label end position strictly less than first test decision position; fixed75-row prewarm offset; no retraining inside test fold.',
        'grouping': 'For EACH model, training fitted signed-gross-PnL predictions have fixed1/3,2/3 linear-interpolated quantiles; apply to test predictions. <=q1 low, >=q2 high, else middle. Degenerate q1>=q2 stops, no arbitrary grouping. Training fitted scores are not independently calibrated. Low group is the sole hypothetical exclusion; all3 groups, common-low/added-low/released-low/neither groups reported. No reversed sign/threshold search/test ranking. Different low-group counts are reported, not equal budgets.',
        'metrics': ['MSE versus PR and training mean', 'low-group loss precision and count recall',
                    'low-group negative amount fraction and positive amount missed, gross and buyfee-net',
                    'retained positive amount, all3group amounts', 'fixed zero-prediction sign accuracy and balanced accuracy'],
        'strata': 'All forward-test events;2025/2026 signal-year;four folds; old434 C0031 actual first-buy signal dates. Actual subset is postselected descriptive, not a deployable input or new model; sizes/fills differ from independent100k labels. Do not call amount sums investment returns.',
        'uncertainty': 'Seed13 moving contiguous chronological blocks10/20,499 draws on predictions and labels; no model refit. Report MSE gain and low-group lost-negative versus missed-positive FRACTION difference. Zero-denominator draws omitted with count. Within subsets block over full chronology then mask, not treating sparse entries as consecutive trading days.',
        'falsification': 'Report years/folds and remove5 largest absolute gross test labels with fixed predictions; future-label and future-feature perturbation must not alter prior fold predictions; compare all overlapping new buy fills against oldh1 labels; check signed decomposition and grouping identities.',
        'budget': {'paired_comparisons': 1, 'targets_fitted': 1, 'folds': 4, 'alpha': 10, 'new_strategy_accounts': 0, 'parameter_searches': 0},
        'interpretation': 'Exploratory seen-development association, not new information, causal attribution, independent validation or executable PnL. Trade filtering changes future cash/positions. No new economic gates. Negative evidence is a valid completion; no automatic new label/feature search.',
        'missing_features': 'Exclude nonfinite required columns identically for both models and count; training std<1e-12 uses1 as in old implementation. Missing source observations fail, no imputation.',
        'resources': {'processes': 1, 'native_threads': 1},
        'sources': {k: r.to_dict() for k, r in refs.items()},
    }
    save(HERE/'protocols/fixed_contrast.json', protocol)
    save(HERE/'others/protocol_refs.json', {p.name: material(p).to_dict() for p in (HERE/'protocols/fixed_contrast.json', Path(__file__))})
    print('PROTOCOL_AND_SOURCE_PUBLISHED', flush=True)


def round_floor(v):
    return float((Decimal(str(v))/Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.001'))


def make_labels(refs):
    facts = read(refs['inputs'].resolve(ROOT))
    s = facts['daily_prepared']
    prepared = PreparedDataRef(UUID(s['space_id']), UUID(s['preparation_id']), s['manifest_sha256'])
    frames, identities = [], {}
    ctx = context()
    for ds in (Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY):
        value = ctx.data.fetch(DataRequest(ds, '159326.SZ', '2024-09-09', '2026-10-21', '2026-10-21', frequency='daily'), prepared=prepared)
        assert value.ready, value.error
        expected = facts['identities'][ds.value]['content_sha256']
        assert value.identity.content_sha256 == expected
        frames.append(value.dataframe.sort_values('Date').reset_index(drop=True))
        identities[ds.value] = expected
    adj, raw = frames
    assert len(adj) == len(raw) == 509
    assert list(adj.Date.astype(str)) == list(raw.Date.astype(str))
    dates = pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d')
    assert dates.iloc[75] == '2025-01-02' and dates.iloc[-1] == '2026-10-21'
    account = read(refs['account'].resolve(ROOT))
    rules = MarketExecutionRules.from_dict(account['request_identity']['market_rules'])
    assert rules.symbol == '159326.SZ' and account['request_identity']['pricing']['basis'] == 'HFQ_RESEARCH'
    fills = pd.DataFrame(account['runs'][0]['ledgers']['fills']['data'])
    buys = fills[fills.side.eq('BUY')].sort_values('fill_time').groupby('cycle_id', sort=False).head(1)
    first_dates = buys.signal_date.astype(str).str[:10]
    assert not first_dates.duplicated().any()
    labels = []
    for i in range(75, 509):
        j = i+1
        close = float(raw.Close.iloc[i])
        scale = float(adj.Close.iloc[i])/close
        limit = min(round_floor(close*1.01), round_floor(round_floor(close*1.1)-.001))*scale
        quantity = min(1000000, int(Decimal('100000')/(Decimal(str(limit))*Decimal('1.001')*100))*100)
        r = {'date': dates.iloc[i], 'signal_position': i, 'label_end_position': j,
             'entry_date': None, 'status': 'RIGHT_CENSORED', 'quantity': quantity, 'buy_limit': limit,
             'buy_price': None, 'close': None, 'gross': None, 'buy_fee': None, 'net_entry': None,
             'buy_trigger': None, 'C0031_first_entry': bool(dates.iloc[i] in set(first_dates))}
        if j < len(adj):
            day = pd.Timestamp(dates.iloc[j])
            q = adj.iloc[j]
            fill = resolve_fill(OrderSpec('BUY', 'LIMIT', quantity, limit), session_open=float(q.Open),
                session_time=day.replace(hour=9, minute=30).to_pydatetime(), intraday_touches=(),
                session_limits=rules.for_session(day.date()), daily_quote=DailyQuote(float(q.Low), float(q.High)))
            r.update(entry_date=dates.iloc[j], close=float(q.Close))
            if fill.filled:
                gross = quantity*(float(q.Close)-fill.price)/100000
                fee = quantity*fill.price*.001/100000
                r.update(status='FILLED', buy_price=fill.price, gross=gross, buy_fee=fee, net_entry=gross-fee, buy_trigger=fill.trigger)
                assert quantity % 100 == 0 and quantity*fill.price*1.001 <= 100000+1e-8
            else:
                r['status'] = 'BUY_UNFILLED'
        labels.append(r)
    labels = pd.DataFrame(labels)
    old = pd.read_csv(refs['old_labels'].resolve(ROOT))
    old = old[old.horizon.eq(1)].set_index('signal_date')
    both = labels.set_index('date').join(old[['status', 'quantity', 'buy_price', 'buy_limit']], rsuffix='_old')
    check = both[both.status_old.eq('FILLED')]
    assert check.status.eq('FILLED').all()
    for col in ('quantity', 'buy_price', 'buy_limit'):
        np.testing.assert_allclose(check[col], check[col+'_old'], rtol=0, atol=1e-12)
    assert both.loc[both.status_old.eq('BUY_UNFILLED'), 'status'].eq('BUY_UNFILLED').all()
    actual_map = []
    for row in buys.itertuples():
        day, signal = str(row.fill_time)[:10], str(row.signal_date)[:10]
        subset = labels[labels.date.eq(signal)]
        if subset.empty:
            actual_map.append({'signal_date': signal, 'entry_date': day, 'status': 'OUTSIDE_DECISION_WINDOW'})
        else:
            rr = subset.iloc[0]
            assert rr.status == 'FILLED' and rr.entry_date == day
            assert abs(rr.buy_price-row.price) < 1e-12
            actual_map.append({'signal_date': signal, 'entry_date': day, 'status': 'MATCHED_PRICE_AND_DAY',
                               'account_quantity': int(row.quantity), 'independent_quantity': int(rr.quantity)})
    save(HERE/'others/label_checks.json', {'status': 'PASS', 'data_hashes': identities,
        'overlapping_old_filled_labels': len(check), 'coverage': labels.status.value_counts().to_dict(),
        'actual_entry_mapping': actual_map, 'original_actual_cycles': len(buys)})
    return labels


def ridge(train, y, test):
    mean, sd = train.mean(0), train.std(0)
    sd = np.where(sd < 1e-12, 1, sd)
    a = (train-mean)/sd
    beta = np.linalg.solve(a.T@a+10*np.eye(a.shape[1]), a.T@(y-y.mean()))
    return y.mean()+((test-mean)/sd)@beta


def predict(x, labels):
    lab = labels.set_index('date').reindex(x.date)
    y, ends = lab.gross.to_numpy(float), lab.label_end_position.to_numpy(float)
    valid = np.isfinite(y) & np.isfinite(x[COLS['AllDaily']].to_numpy(float)).all(1) & lab.status.eq('FILLED').to_numpy()
    pos = np.arange(len(x))
    records, fits = [], []
    for fold, (left, right) in enumerate(FOLDS):
        start, stop = left+75, right+75
        train = np.flatnonzero(valid & (pos < start) & (ends < start))
        test = np.flatnonzero(valid & (pos >= start) & (pos < stop))
        assert len(train) > 80 and len(test) > 20
        predictions, groups = {}, {}
        fit = {'fold': fold, 'train_n': len(train), 'test_n': len(test), 'train_last_label_end': int(ends[train].max()), 'test_start': start}
        for model, columns in COLS.items():
            a = x[columns].to_numpy(float)
            train_pred = ridge(a[train], y[train], a[train])
            predictions[model] = ridge(a[train], y[train], a[test])
            q1, q2 = np.quantile(train_pred, [1/3, 2/3], method='linear')
            assert q1 < q2
            groups[model] = np.where(predictions[model] <= q1, -1, np.where(predictions[model] >= q2, 1, 0))
            fit[model] = {'q1': float(q1), 'q2': float(q2)}
        fits.append(fit)
        for j, p in enumerate(test):
            rr = lab.iloc[p]
            r = {'date': x.date.iloc[p], 'entry_date': rr.entry_date, 'fold': fold, 'gross': float(y[p]),
                 'buy_fee': float(rr.buy_fee), 'net_entry': float(rr.net_entry),
                 'C0031_first_entry': bool(rr.C0031_first_entry), 'mean_prediction': float(y[train].mean())}
            for model in COLS:
                r[model+'_prediction'] = float(predictions[model][j])
                r[model+'_group'] = int(groups[model][j])
            records.append(r)
    return pd.DataFrame(records), fits


def ratio(a, b):
    return float(a/b) if b else None


def opportunity(y, mask):
    y = np.asarray(y, float)
    selected = np.asarray(mask, bool)
    pos, neg = np.maximum(y, 0), np.maximum(-y, 0)
    return {'n': int(selected.sum()), 'positive_count': int(((y > 0)&selected).sum()),
        'negative_count': int(((y < 0)&selected).sum()), 'zero_count': int(((y == 0)&selected).sum()),
        'positive_yuan': float(pos[selected].sum()*100000), 'negative_yuan': float(neg[selected].sum()*100000),
        'signed_yuan': float(y[selected].sum()*100000),
        'missed_positive_fraction': ratio(pos[selected].sum(), pos.sum()),
        'captured_negative_fraction': ratio(neg[selected].sum(), neg.sum()),
        'loss_precision': ratio(((y < 0)&selected).sum(), selected.sum()),
        'loss_count_recall': ratio(((y < 0)&selected).sum(), (y < 0).sum())}


def summarize(g):
    if g.empty:
        return {'n': 0}
    y = g.gross.to_numpy()
    out = {'n': len(g), 'gross_total': opportunity(y, np.ones(len(g), bool)),
           'net_entry_total': opportunity(g.net_entry, np.ones(len(g), bool)),
           'mean_prediction_mse': float(((g.mean_prediction-y)**2).mean()), 'models': {}}
    losses = {}
    for model in COLS:
        pred = g[model+'_prediction'].to_numpy()
        losses[model] = (pred-y)**2
        label_loss, flag_loss = y < 0, pred < 0
        tpr, tnr = ratio((flag_loss&label_loss).sum(), label_loss.sum()), ratio((~flag_loss&~label_loss).sum(), (~label_loss).sum())
        groups = {str(k): {'gross': opportunity(y, g[model+'_group'].eq(k)),
                          'net_entry': opportunity(g.net_entry, g[model+'_group'].eq(k))} for k in (-1, 0, 1)}
        out['models'][model] = {'mse': float(losses[model].mean()),
            'gain_vs_mean': 1-float(losses[model].mean())/out['mean_prediction_mse'],
            'sign_accuracy_zero_threshold': float((flag_loss == label_loss).mean()),
            'balanced_accuracy_zero_threshold': (tpr+tnr)/2 if tpr is not None and tnr is not None else None,
            'groups': groups, 'exclusion_fraction': float(g[model+'_group'].eq(-1).mean())}
    out['AllDaily_gain_vs_PR'] = float(1-losses['AllDaily'].mean()/losses['PR'].mean())
    pr, added = g.PR_group.eq(-1), g.AllDaily_group.eq(-1)
    out['exclusion_transition'] = {name: {'gross': opportunity(g.gross, mask),
        'net_entry': opportunity(g.net_entry, mask)} for name,mask in {
        'common_low': pr & added, 'AllDaily_added_low': ~pr & added,
        'AllDaily_released_low': pr & ~added, 'neither_low': ~pr & ~added}.items()}
    return out


def intervals(g, block, subset=False):
    rng, n = np.random.default_rng(13), len(g)
    draws = []
    for _ in range(499):
        starts = rng.integers(0, n-block+1, size=int(np.ceil(n/block)))
        ids = np.concatenate([np.arange(s, s+block) for s in starts])[:n]
        chosen = g.iloc[ids]
        if subset:
            chosen = chosen[chosen.C0031_first_entry]
        s = summarize(chosen)
        if not s['n']:
            continue
        row = {'AllDaily_gain_vs_PR': s['AllDaily_gain_vs_PR']}
        for m in COLS:
            o = s['models'][m]['groups']['-1']['gross']
            if o['captured_negative_fraction'] is not None and o['missed_positive_fraction'] is not None:
                row[m+'_amount_fraction_spread'] = o['captured_negative_fraction']-o['missed_positive_fraction']
        draws.append(row)
    frame = pd.DataFrame(draws)
    return {c: {'interval': frame[c].dropna().quantile([.025,.975]).tolist(), 'valid_draws': int(frame[c].notna().sum())} for c in frame}


def run():
    assert not (HERE/'others/results.json').exists()
    prerefs = read(HERE/'others/protocol_refs.json')
    assert sha256(Path(__file__).read_bytes()).hexdigest() == prerefs[Path(__file__).name]['sha256']
    for r in prerefs.values():
        EvidenceRef.from_dict(r).resolve(ROOT)
    refs = sources()
    x = pd.read_csv(refs['features'].resolve(ROOT))
    assert len(x) == 509 and x.date.iloc[75] == '2025-01-02'
    labels = make_labels(refs)
    labels.to_csv(HERE/'others/entry_labels.csv', index=False, lineterminator='\n')
    g, fits = predict(x, labels)
    assert not g.date.duplicated().any() and g.date.max() <= '2026-10-21'
    assert all(f['train_last_label_end'] < f['test_start'] for f in fits)
    altered = labels.copy()
    altered.loc[altered.signal_position.ge(259), 'gross'] += .5
    changed, _ = predict(x, altered)
    changed_x = x.copy()
    changed_x.loc[259:, COLS['AllDaily']] += 5
    changed_features, _ = predict(changed_x, labels)
    columns = ['PR_prediction','AllDaily_prediction','PR_group','AllDaily_group','mean_prediction']
    for modified in (changed, changed_features):
        np.testing.assert_allclose(g.loc[g.fold.eq(0), columns], modified.loc[modified.fold.eq(0), columns], rtol=0, atol=0)
    np.testing.assert_allclose(g.net_entry, g.gross-g.buy_fee, atol=1e-14, rtol=0)
    g.to_csv(HERE/'others/forward_predictions.csv', index=False, lineterminator='\n')
    result = {'comparison': 'PR vs AllDaily; signed entry-to-close gross PnL', 'new_accounts': 0,
        'paired_conditions': 1, 'folds': fits, 'all': summarize(g),
        'years': {str(y): summarize(d) for y,d in g.groupby(g.date.str[:4])},
        'periods': {str(k): summarize(d) for k,d in g.groupby('fold')},
        'drop5_extreme': summarize(g.drop(g.gross.abs().nlargest(5).index)),
        'actual_C0031_first_entry': summarize(g[g.C0031_first_entry]),
        'actual_years': {str(y): summarize(d[d.C0031_first_entry]) for y,d in g.groupby(g.date.str[:4])},
        'actual_periods': {str(k): summarize(d[d.C0031_first_entry]) for k,d in g.groupby('fold')},
        'intervals': {str(b): intervals(g,b) for b in (10,20)},
        'actual_intervals': {str(b): intervals(g,b,True) for b in (10,20)}}
    save(HERE/'others/results.json', result)
    checks = {'status': 'PASS', 'input_hashes': 'PASS', 'source_identity': 'PASS', 'label_fill_equivalence': 'PASS',
        'training_only_scaling_and_terciles': 'SOURCE_CHECK', 'label_purge': 'PASS',
        'future_label_isolation': 'PASS', 'future_feature_isolation': 'PASS', 'fee_identity': 'PASS',
        'prediction_rows': len(g), 'actual_entry_rows': int(g.C0031_first_entry.sum()),
        'nonfinite_feature_rows_in_decision_window': int((~np.isfinite(x.loc[75:, COLS['AllDaily']].to_numpy(float)).all(1)).sum()),
        'paired_conditions': 1, 'new_accounts': 0, 'new_candidates': 0}
    for s in [result['all'],result['actual_C0031_first_entry']]:
        for model in COLS:
            for target,total in [('gross','gross_total'),('net_entry','net_entry_total')]:
                groups = [s['models'][model]['groups'][str(k)][target] for k in (-1,0,1)]
                for key in ('n','positive_yuan','negative_yuan','signed_yuan'):
                    assert abs(sum(z[key] for z in groups)-s[total][key]) < 1e-7
    checks['group_amount_reconciliation'] = 'PASS'
    save(HERE/'others/checks.json', checks)
    print({'n':len(g),'actual_n':int(g.C0031_first_entry.sum()),'gain':result['all']['AllDaily_gain_vs_PR'],
           'low':result['all']['models']['AllDaily']['groups']['-1']}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('prepare','run'))
    {'prepare':prepare, 'run':run}[p.parse_args().mode]()
