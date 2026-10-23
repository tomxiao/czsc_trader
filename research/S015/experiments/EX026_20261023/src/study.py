"""Prospectively fixed continuation event study; not a strategy account."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
from multiprocessing import get_context
import os
from pathlib import Path
from uuid import UUID

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import EvidenceRef, ExecutionResources, ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparedDataRef
from trading_execution_engine import DailyQuote, MarketExecutionRules, OrderSpec, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parents[1]
EX = ExperimentRef('S015', HERE.name)
HORIZONS = (1, 3, 5)
TIMES = ('10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00')
SEGMENTS = ((0, 100), (100, 184), (184, 268), (268, 352), (352, 434))


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'), resources=ExecutionResources(3, 1, 13))


def material(path):
    return publish_evidence(context(), MaterialEvidenceWrite(EX, path.stem, path.read_bytes(),
        {'.py': 'text/x-python', '.md': 'text/markdown', '.json': 'application/json', '.csv': 'text/csv'}[path.suffix], path.suffix[1:]))


def sources():
    base = ROOT/'research/S015/experiments'
    refs = [EvidenceRef.from_dict(x) for x in read(base/'EX011_20261023/others/published_refs.json')['references']]
    out = {'inputs': next(r for r in refs if r.name == 'input_facts' and r.experiment.experiment_id == 'EX010_20261023')}
    old = read(base/'EX015_20261023/others/delivery_validation.json')
    out['entry_labels'] = EvidenceRef.from_dict(old['materials']['entry_labels.csv'])
    out['old_event_labels'] = next(r for r in refs if r.name == 'event_labels' and r.experiment.experiment_id == 'EX010_20261023')
    rows = read(ROOT/'research/S015/assets/runs/EX003_20261021/strategy_study/grid_results.json')
    out['execution_contract'] = EvidenceRef.from_dict(next(r for r in rows if r['candidate_id'] == 'C0031')['evidence'])
    for name in ('EX013_20261023', 'EX015_20261023', 'EX024_20261023'):
        out[name] = EvidenceRef.from_dict(read(base/name/'report_ref.json')['report'])
    for r in out.values():
        r.resolve(ROOT)
    return out


def inputs(refs):
    facts = read(refs['inputs'].resolve(ROOT))
    frames, identities = {}, {}
    ctx = context()
    for dataset in (Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY):
        minute = dataset == Dataset.ETF_UNADJUSTED_INTRADAY
        p = facts['minute_prepared' if minute else 'daily_prepared']
        prepared = PreparedDataRef(UUID(p['space_id']), UUID(p['preparation_id']), p['manifest_sha256'])
        req = DataRequest(dataset, '159326.SZ', '2025-01-02' if minute else '2024-09-09', '2026-10-21', '2026-10-21', frequency='30m' if minute else 'daily')
        result = ctx.data.fetch(req, prepared=prepared)
        assert result.ready, result.error
        assert result.identity.content_sha256 == facts['identities'][dataset.value]['content_sha256']
        frames[dataset] = result.dataframe.sort_values('Date').reset_index(drop=True)
        identities[dataset.value] = result.identity.content_sha256
    adj, raw, bars = (frames[k] for k in (Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY))
    assert len(adj) == len(raw) == 509 and len(bars) == 3472
    assert adj.Date.equals(raw.Date) and not adj.Date.duplicated().any()
    assert str(pd.Timestamp(adj.Date.iloc[75]).date()) == '2025-01-02'
    assert str(pd.Timestamp(adj.Date.iloc[-1]).date()) == '2026-10-21'
    for frame in (adj, raw, bars):
        assert np.isfinite(frame[['Open', 'High', 'Low', 'Close']]).all().all()
        assert (frame[['Open', 'High', 'Low', 'Close']] > 0).all().all()
    account = read(refs['execution_contract'].resolve(ROOT))
    assert account['request_identity']['pricing']['basis'] == 'HFQ_RESEARCH'
    rules = account['request_identity']['market_rules']
    assert MarketExecutionRules.from_dict(rules).symbol == '159326.SZ'
    return adj, raw, bars, rules, identities


def features(raw, bars):
    c = raw.Close.astype(float)
    amp = (raw.High-raw.Low)/c
    previous_high = c.shift(1).rolling(20).max()
    range5, range20 = amp.rolling(5).mean().shift(1), amp.rolling(20).mean().shift(1)
    b = bars.copy()
    b['date'] = pd.to_datetime(b.Date).dt.strftime('%Y-%m-%d')
    minutes = []
    for day, g in b.groupby('date', sort=True):
        assert tuple(pd.to_datetime(g.Date).dt.strftime('%H:%M')) == TIMES, day
        first, middle, last = float(g.Open.iloc[0]), float(g.Close.iloc[4]), float(g.Close.iloc[7])
        minutes.append({'date': day, 'first_open': first, 'close_1330': middle, 'close_1500': last,
                        'C': middle > first and last > middle})
    x = pd.DataFrame({'date': pd.to_datetime(raw.Date).dt.strftime('%Y-%m-%d'), 'close': c,
        'prior_high20': previous_high, 'prior_range5': range5, 'prior_range20': range20,
        'pressure': c/(raw.Amount/raw.Volume)-1})
    x = x.iloc[75:].reset_index(drop=True)
    x['A'] = x.close > x.prior_high20
    x['B'] = x.A & (x.prior_range5 < x.prior_range20)
    x = x.merge(pd.DataFrame(minutes), on='date', how='left', validate='one_to_one')
    assert len(x) == len(raw)-75 and not x.isna().any().any()
    x['P'] = x.pressure >= 0
    x['P25'] = x.pressure >= .0025
    x['position'] = np.arange(len(x))
    assert not (x.B & ~x.A).any()
    return x


def floor_tick(value):
    return float((Decimal(str(value))/Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.001'))


def fill(order, frame, pos, rules):
    q = frame.iloc[pos]
    day = pd.Timestamp(q.Date)
    return resolve_fill(order, session_open=float(q.Open), session_time=day.replace(hour=9, minute=30).to_pydatetime(),
        intraday_touches=(), session_limits=rules.for_session(day.date()), daily_quote=DailyQuote(float(q.Low), float(q.High)))


def events(args):
    adj, raw, rule_dict, horizon, positions = args
    rules = MarketExecutionRules.from_dict(rule_dict)
    output = []
    for i in positions:
        signal = pd.Timestamp(adj.Date.iloc[i]).strftime('%Y-%m-%d')
        j, k = i+1, i+horizon+1
        raw_close = float(raw.Close.iloc[i])
        scale = float(adj.Close.iloc[i])/raw_close
        limit = min(floor_tick(raw_close*1.01), floor_tick(floor_tick(raw_close*1.1)-.001))*scale
        quantity = min(1000000, int(Decimal('100000')/(Decimal(str(limit))*Decimal('1.001')*100))*100)
        row = dict(date=signal, position=i-75, horizon=horizon, status='NO_NEXT_SESSION', quantity=quantity,
            buy_limit=limit, buy_price=None, entry_date=None, planned_exit_date=None, actual_exit_date=None,
            sell_price=None, buy_fee=None, sell_fee=None, gross=None, net=None, before_entry_change=None,
            entry_gross=None, entry_net=None, subsequent_gross=None, exit_delay=None, end_mark_net=None,
            buy_trigger=None, buy_reason=None, buy_time_precision=None, exit_attempts='[]')
        if k < len(adj):
            row['planned_exit_date'] = str(pd.Timestamp(adj.Date.iloc[k]).date())
        if j >= len(adj):
            output.append(row)
            continue
        buy = fill(OrderSpec('BUY', 'LIMIT', quantity, limit), adj, j, rules)
        row.update(entry_date=str(pd.Timestamp(adj.Date.iloc[j]).date()), buy_trigger=buy.trigger,
            buy_reason=buy.reason, buy_time_precision=str(buy.time_precision))
        if not buy.filled:
            row['status'] = 'BUY_UNFILLED'
            output.append(row)
            continue
        fee = quantity*buy.price*.001
        entry = quantity*(float(adj.Close.iloc[j])-buy.price)
        assert quantity > 0 and quantity % 100 == 0 and quantity*buy.price+fee <= 100000+1e-8
        row.update(buy_price=buy.price, buy_fee=fee, before_entry_change=buy.price/float(adj.Close.iloc[i])-1,
            entry_gross=entry, entry_net=entry-fee, status='EXIT_RIGHT_CENSORED',
            end_mark_net=quantity*(float(adj.Close.iloc[-1])-buy.price)-fee)
        attempts = []
        for s in range(k, len(adj)):
            sell = fill(OrderSpec('SELL', 'MARKET', quantity, None), adj, s, rules)
            attempts.append({'date': str(pd.Timestamp(adj.Date.iloc[s]).date()), 'filled': bool(sell.filled),
                'trigger': sell.trigger, 'reason': sell.reason, 'time_precision': str(sell.time_precision)})
            if sell.filled:
                sell_fee = quantity*sell.price*.001
                gross = quantity*(sell.price-buy.price)
                row.update(status='CLOSED', actual_exit_date=attempts[-1]['date'], sell_price=sell.price,
                    sell_fee=sell_fee, gross=gross, net=gross-fee-sell_fee,
                    subsequent_gross=gross-entry, exit_delay=s-k, end_mark_net=None)
                break
        if attempts and row['status'] != 'CLOSED':
            row['status'] = 'SELL_UNFILLED_AT_END'
        row['exit_attempts'] = json.dumps(attempts, ensure_ascii=False)
        output.append(row)
    return output


def stats(frame):
    n = len(frame)
    if not n:
        return {'n': 0}
    y = frame.net.to_numpy(float)
    positive = float(np.maximum(y, 0).sum())
    best = frame.nlargest(min(5, n), 'net')
    best = best[best.net > 0]
    return {'n': n, 'net_mean_return': float(y.mean()/100000), 'net_median_return': float(np.median(y)/100000),
        'positive_n': int((y > 0).sum()), 'negative_n': int((y < 0).sum()), 'zero_n': int((y == 0).sum()),
        'positive_yuan': positive, 'negative_yuan': float(-np.minimum(y, 0).sum()), 'net_yuan': float(y.sum()),
        'gross_yuan': float(frame.gross.sum()), 'fees_yuan': float(frame.buy_fee.sum()+frame.sell_fee.sum()),
        'before_entry_mean_change': float(frame.before_entry_change.mean()),
        'entry_gross_yuan': float(frame.entry_gross.sum()), 'entry_net_yuan': float(frame.entry_net.sum()),
        'subsequent_gross_yuan': float(frame.subsequent_gross.sum()),
        'top1_positive_fraction': float(best.net.iloc[0]/positive) if positive else None,
        'top5_positive_fraction': float(best.net.sum()/positive) if positive else None,
        'top5_events': best[['date', 'net']].to_dict('records')}


def ratio(a, b):
    return float(a/b) if b else None


def comparisons(frame):
    result = {}
    good = frame[frame.status.eq('CLOSED')]
    allstat = stats(good)
    for name in ('A', 'B', 'C'):
        selected, excluded = good[good[name]], good[~good[name]]
        ss, es = stats(selected), stats(excluded)
        ss.update(captured_positive_fraction=ratio(ss.get('positive_yuan', 0), allstat.get('positive_yuan', 0)),
            borne_negative_fraction=ratio(ss.get('negative_yuan', 0), allstat.get('negative_yuan', 0)),
            missed_positive_yuan=es.get('positive_yuan', 0),
            missed_positive_fraction=ratio(es.get('positive_yuan', 0), allstat.get('positive_yuan', 0)))
        result[name] = {'all': allstat, 'in': ss, 'out': es,
            'net_mean_difference': ss['net_mean_return']-es['net_mean_return'] if len(selected) and len(excluded) else None,
            'signal_n': int(frame[name].sum()), 'status_in': frame[frame[name]].status.value_counts().to_dict(),
            'periods': {f'{left}:{right}': stats(selected[selected.position.ge(left)&selected.position.lt(right)]) for left, right in SEGMENTS}}
    result['B_increment'] = {'B': stats(good[good.B]), 'A_not_B': stats(good[good.A & ~good.B])}
    result['C_pressure_cells'] = {p: {f'C{int(c)}_P{int(v)}': stats(good[good.C.eq(c)&good[p].eq(v)])
        for c in (False, True) for v in (False, True)} for p in ('P', 'P25')}
    return result


def intervals(frame):
    assert len(frame) == 434 and list(frame.position) == list(range(434))
    y = frame.net.to_numpy(float)/100000
    valid = frame.status.eq('CLOSED').to_numpy()
    masks = {name: frame[name].to_numpy(bool) for name in ('A', 'B', 'C')}
    contrasts = {name: (v, ~v) for name, v in masks.items()}
    contrasts['B_vs_A_not_B'] = (masks['B'], masks['A'] & ~masks['B'])
    result = {}
    for block in (10, 20):
        rng = np.random.default_rng(13)
        draws = {name: [] for name in contrasts}
        for _ in range(499):
            starts = rng.integers(0, len(frame)-block+1, size=int(np.ceil(len(frame)/block)))
            idx = np.concatenate([np.arange(s, s+block) for s in starts])[:len(frame)]
            for name, (yes, no) in contrasts.items():
                a, b = y[idx][(yes & valid)[idx]], y[idx][(no & valid)[idx]]
                if len(a) and len(b):
                    draws[name].append(float(a.mean()-b.mean()))
        result[str(block)] = {name: {'valid_draws': len(v), 'empty_group_draws': 499-len(v),
            'interval95': np.quantile(v, [.025, .975]).tolist() if v else None} for name, v in draws.items()}
    return result


def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    refs = sources()
    adj, raw, bars, rules, identities = inputs(refs)
    # Data and timestamp inventory only, no conditions/outcomes examined before publication.
    assert tuple(sorted(pd.to_datetime(bars.Date).dt.strftime('%H:%M').unique())) == TIMES
    assert (bars.groupby(pd.to_datetime(bars.Date).dt.date).size() == 8).all()
    protocol = {'authorization': '用户批准方案后回复：同意，请继续。新增1轮阶段二固定诊断。',
        'proposal_sha256': sha256((ROOT/'research/S015/materials/mechanism_reorientation_20261023.md').read_bytes()).hexdigest(),
        'mandate': 'MANDATE/3 unchanged; current qualified candidates=0',
        'definitions': {'A': 'Close[T]>max(Close[T-20:T]) excluding T',
            'B': 'A and mean((High-Low)/Close,T-5:T)<mean((High-Low)/Close,T-20:T), excluding T',
            'C': '30m13:30Close>10:00barOpen AND 15:00Close>13:30Close'},
        'horizons': HORIZONS, 'buy': 'T+1 only, no retry. Signal raw close+1%, original tick/lot/upper-guard/fee sizing and HFQ scaling, public resolve_fill DAILY_RANGE_V3.',
        'sell': 'Decision T+h; first attempt T+h+1, then daily market reissue until filled/end. Buy processed before exit censoring. h1 cannot sell buy day.',
        'capital': 100000, 'fee_per_side': .001, 'new_continuous_strategy_accounts': 0,
        'event_design_cells': 9, 'unique_daily_horizon_rows': 434*3,
        'coverage': 'NO_NEXT_SESSION, BUY_UNFILLED, EXIT_RIGHT_CENSORED, SELL_UNFILLED_AT_END, CLOSED separately; entry mark remains for bought censored events; completed labels use CLOSED only.',
        'statistics': 'Unweighted independent100k events; net=quantity*(sell-buy)-bothfees. Gross entry and subsequent separated. Preentry return is not profit. All/in/out, B vs A-notB, C vs prior pressure>=0 fourcells; pressure>=.0025 separate historical threshold diagnostic only.',
        'segments': SEGMENTS, 'bootstrap': {'axis': 'all434 actual trading days with masks and missing values', 'blocks': [10,20], 'draws': 499, 'seed': 13, 'interval': [.025,.975], 'contrasts': ['A-out','B-out','C-out','B-A_notB'], 'inference': 'exploratory uncorrected; no economic gate'},
        'resources': {'processes':3,'native_threads':1,'seed':13},
        'verification': 'Prefix truncation and future perturbation at every decision day; independent feature/label arithmetic; historical h1/h3 overlapping labels; synthetic fill edge cases; serial vs spawned worker precheck.',
        'data': identities, 'publication_limits': 'Historical vendor availability by17:30 and adjusted-price publication clock not certified; daily range fill model without volume capacity. No new source/refresh/window.',
        'sources': {k:v.to_dict() for k,v in refs.items()}}
    save(HERE/'protocols/fixed_mechanisms.json', protocol)
    paths = [HERE/'protocols/fixed_mechanisms.json', Path(__file__), ROOT/'research/S015/materials/mechanism_reorientation_20261023.md']
    save(HERE/'others/protocol_refs.json', {p.name:material(p).to_dict() for p in paths})
    print('PROTOCOL_AND_SOURCE_PUBLISHED', flush=True)


def run():
    assert not (HERE/'others/results.json').exists()
    pre = read(HERE/'others/protocol_refs.json')
    source = EvidenceRef.from_dict(pre['study.py'])
    assert source.resolve(ROOT).read_bytes() == Path(__file__).read_bytes()
    refs = sources()
    adj, raw, bars, rules, identities = inputs(refs)
    x = features(raw, bars)
    x.to_csv(HERE/'others/features.csv', index=False)
    small = [(adj,raw,rules,h,range(75,79)) for h in HORIZONS]
    serial = [events(t) for t in small]
    with ProcessPoolExecutor(max_workers=3, mp_context=get_context('spawn')) as pool:
        parallel = list(pool.map(events, small))
        assert serial == parallel
        batches = list(pool.map(events, [(adj,raw,rules,h,range(75,509)) for h in HORIZONS]))
    labels = pd.DataFrame([row for batch in batches for row in batch]).merge(x, on=['date','position'], validate='many_to_one')
    assert len(labels) == 1302
    labels.to_csv(HERE/'others/events.csv', index=False)
    result = {'qualified_candidates': 0, 'completed_rounds': 1, 'remaining_rounds': 0, 'new_continuous_accounts': 0,
        'design_cells': 9, 'event_rows':1302,'technical_precheck_event_rows':24,
        'data_identities':identities,'horizons': {}}
    for h in HORIZONS:
        frame = labels[labels.horizon.eq(h)].sort_values('position')
        result['horizons'][str(h)] = {'coverage': frame.status.value_counts().to_dict(),
            'delayed_exits': int(frame.exit_delay.gt(0).sum()), 'comparisons': comparisons(frame), 'intervals': intervals(frame)}
    save(HERE/'others/results.json', result)
    save(HERE/'others/execution_checks.json', {'status':'PASS','serial_spawn_equivalent':True,
        'precheck_tasks':3,'precheck_rows_each_path':12,'workers':3,'native_threads':1,'data_identities':identities})
    print(json.dumps({h:{'coverage':r['coverage'],'means':{k:v['in']['net_mean_return'] for k,v in r['comparisons'].items() if k in ('A','B','C')}} for h,r in result['horizons'].items()}),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare','run'))
    {'prepare':prepare,'run':run}[parser.parse_args().action]()
