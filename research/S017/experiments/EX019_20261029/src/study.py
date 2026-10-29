"""Fixed-horizon information/one-share price labels, never a portfolio backtest."""
# ruff: noqa: E402
# Bound native worker threads before importing numeric libraries, including under spawn.
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import importlib.util
import gzip
import json
import multiprocessing as mp
import os
from pathlib import Path
from uuid import UUID

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
import numpy as np
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct,
    EquityQuery, InstrumentId, MarketId, PreparedDataRef, ProviderConfig, SourceRef)
from strategy_runtime import (ResearchExecutionSpec, UsEquitySpec, AccountPolicy,
    CashAvailabilityPolicy, ExecutionResources)
from trading_execution_engine import OrderSpec, resolve_fill
from czsc_trader.application import (RepositoryContext, create_research_context,
    publish_evidence, validate_experiment)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope)

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OLD = ROOT/'research/S017/experiments/EX018_20261029'
PREP = ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json'
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', WORK.name)
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
PAT_SHA = 'fc668744f569c9a19610a18b4573de80c07a6936b220c116d698b910dd613f4c'
HORIZONS = (3, 13, 26)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str,
                               allow_nan=False), encoding='utf-8')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def context():
    scratch = ROOT/'.tmp/s017-event-study'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(scratch)
    return create_research_context(REPOSITORY, ResearchBatchRef('S017'),
        providers=ProviderConfig(bindings={}), execution_spec=SPEC,
        resources=ExecutionResources(max_workers=2, native_threads_per_worker=1, random_seed=17))


def pat_function():
    path = OLD/'src/strategy.py'
    if digest(path) != PAT_SHA:
        raise ValueError('Original PAT source changed')
    spec = importlib.util.spec_from_file_location('original_pat', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.pat_entry


def scan_chunk(args):
    bars, indices = args
    pat = pat_function()
    result = []
    for i in indices:
        # The authorized preparation requires complete observed bars and close-time availability.
        trigger, facts = pat(bars.iloc[max(0, i-260):i+1])
        result.append((int(i), bool(trigger), facts.get('pat_l2_at')))
    return result


def price_at(bar, constraint, side, limit=None):
    if bar['BarStatus'] != 'OBSERVED':
        return None, str(bar['BarStatus'])
    if bool(bar['ExecutionBlocked']):
        return None, 'KNOWN_INTERRUPTION'
    if not bool(constraint['Tradable']):
        return None, 'NOT_TRADABLE'
    if float(bar['Volume']) < 1:
        return None, 'INSUFFICIENT_SINGLE_SHARE_VOLUME'
    fill = resolve_fill(OrderSpec(side, 'LIMIT' if side == 'BUY' else 'MARKET', 1, limit),
        session_open=float(bar['Open']), session_time=bar['BarStart'].to_pydatetime(),
        intraday_touches=((bar['Date'].to_pydatetime(), float(bar['Low'] if side == 'BUY' else bar['High'])),),
        slippage_bp=0., inclusive_touch=False)
    if not fill.filled:
        return None, fill.reason
    return float(fill.price), 'BAR_INTERVAL' if fill.trigger == 'INTRADAY_LIMIT' else 'MODEL_BAR_OPEN'


def label(bars, constraints, i, n):
    row = {'i': int(i), 'n': n, 'information_return': None, 'price_net_return': None,
           'entry_price': None, 'exit_price': None, 'close_path_min': None,
           'close_path_max': None, 'entry_status': 'NOT_OBSERVED', 'exit_status': 'NOT_OBSERVED'}
    if i+n < len(bars) and bars.iloc[i+n].BarStatus == 'OBSERVED':
        row['information_return'] = float(bars.iloc[i+n].Close/bars.iloc[i].Close-1)
    if i+1 >= len(bars):
        row['status'] = 'RIGHT_CENSORED_ENTRY'
        return row
    limit = float((Decimal(str(float(bars.iloc[i].Close)))*Decimal('1.01')/Decimal('.01'))
                  .to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01'))
    row['limit_price'] = limit
    entry, reason = price_at(bars.iloc[i+1], constraints.iloc[i+1], 'BUY', limit)
    row.update(entry_price=entry, entry_status=reason)
    if entry is None:
        row['status'] = 'NO_ENTRY'
        return row
    if i+n+1 >= len(bars):
        row['status'] = 'RIGHT_CENSORED_EXIT'
        return row
    held = bars.iloc[i+1:i+n+1]
    if not held.BarStatus.eq('OBSERVED').all():
        row['status'] = 'PATH_UNOBSERVED'
        return row
    path = held.Close/entry-1
    row.update(close_path_min=float(min(0., path.min())), close_path_max=float(max(0., path.max())))
    sell, reason = price_at(bars.iloc[i+n+1], constraints.iloc[i+n+1], 'SELL')
    row.update(exit_price=sell, exit_status=reason)
    if sell is None:
        row['status'] = 'NO_EXIT'
        return row
    row.update(status='COMPLETE', price_net_return=sell*.999/(entry*1.001)-1)
    return row


def nonoverlap(indices, n):
    selected, end = [], -1
    for i in indices:
        if i > end:
            selected.append(i)
            end = i+n+1
    return set(selected)


def stats(values):
    a = np.array([v for v in values if v is not None], dtype=float)
    if not len(a):
        return {'count': 0}
    wins, losses = a[a>0], a[a<0]
    return {'count': len(a), 'mean': float(a.mean()), 'median': float(np.median(a)),
        'win_rate': float(np.mean(a>0)), 'flat_rate': float(np.mean(a==0)),
        'average_win': float(wins.mean()) if len(wins) else None,
        'average_loss_magnitude': float(-losses.mean()) if len(losses) else None,
        'payoff_ratio': float(wins.mean()/-losses.mean()) if len(wins) and len(losses) else None,
        'q10': float(np.quantile(a,.1)), 'q90': float(np.quantile(a,.9))}


def summarize(rows):
    return {'events': len(rows), 'signal_days': len({r['date'] for r in rows}),
        'status': dict(Counter(r['status'] for r in rows)),
        'entry_status': dict(Counter(r['entry_status'] for r in rows)),
        'exit_status': dict(Counter(r['exit_status'] for r in rows)),
        'information': stats([r['information_return'] for r in rows]),
        'price': stats([r['price_net_return'] for r in rows]),
        'close_path_min': stats([r['close_path_min'] for r in rows]),
        'close_path_max': stats([r['close_path_max'] for r in rows])}


def matched(rows, signals):
    groups = {}
    for row in rows:
        if row['price_net_return'] is not None:
            groups.setdefault(row['stratum'], []).append(row['price_net_return'])
    means = {key: float(np.mean(v)) for key,v in groups.items()}
    paired = []
    for row in signals:
        if row['price_net_return'] is not None:
            if row['stratum'] not in means:
                raise ValueError('Complete signal has no same-population control')
            paired.append({'month': row['month'], 'signal_return': row['price_net_return'],
                           'control_return': means[row['stratum']],
                           'difference': row['price_net_return']-means[row['stratum']]})
    return {'count': len(paired), 'unmatched_complete': 0,
        'signal': stats([r['signal_return'] for r in paired]),
        'control': stats([r['control_return'] for r in paired]),
        'difference': stats([r['difference'] for r in paired])}, paired


def bootstrap(pairs):
    months = sorted({p['month'] for p in pairs})
    if not months:
        return {'status': 'NO_COMPLETE_PAIRS'}
    blocks = [np.array([r['difference'] for r in pairs if r['month']==m]) for m in months]
    rng = np.random.default_rng(17)
    values = []
    for _ in range(1000):
        chosen = [blocks[i] for i in rng.integers(0, len(blocks), len(blocks))]
        values.append(float(np.concatenate(chosen).mean()))
    return {'status': 'DESCRIPTIVE', 'months': len(months), 'replicates': 1000,
        'seed': 17, 'interval_95': [float(x) for x in np.quantile(values,[.025,.975])],
        'limits': 'Fixed control estimates; serial dependence across months and adaptive selection not covered.'}


def fetch(research):
    saved = read(PREP)
    value = saved['reference']
    ref = PreparedDataRef(UUID(value['space_id']), UUID(value['preparation_id']), value['manifest_sha256'])
    expected = {r['product']: r['sha256'] for r in saved['items']}
    frames, identities = {}, {}
    for product in EquityProduct:
        request = EquityDataRequest(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'),
            SourceRef('futu','s017-development-gap-known-interruptions-v1-20261028'),
            EquityQuery(product, date(2018,11,1), date(2025,12,31), BarFrequency.M30))
        item = research.data.fetch(request, prepared=ref)
        if not item.ready or item.identity.content_sha256 != expected[product.value]:
            raise ValueError('Original prepared product unavailable or changed: '+product.value)
        frames[product.name] = item.dataframe
        identities[product.name] = {'rows': len(item.dataframe), 'sha256':item.identity.content_sha256}
    bars, constraints = frames['BARS'], frames['CONSTRAINTS']
    if (not bars.BarStatus.eq('OBSERVED').all() or not bars.AvailableDate.eq(bars.Date).all()
            or not bars.Date.is_monotonic_increasing or bars.Date.duplicated().any()
            or not frames['ACTIONS'].Kind.eq('NONE').all()
            or not bars.BarStart.reset_index(drop=True).equals(constraints.Date.reset_index(drop=True))
            or not (constraints.AvailableDate <= constraints.Date).all()
            or not constraints.QuantityStep.eq(1).all() or not constraints.PriceTick.eq(.01).all()
            or bars.Date.dt.tz_convert('America/New_York').max().date() > date(2025,12,31)):
        raise ValueError('Input contract needs review; no fallback or silent filtering')
    return bars.reset_index(drop=True), constraints.reset_index(drop=True), identities


def materials(research, pairs):
    return {name: publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name,
        path.read_bytes(), {'.json':'application/json','.gz':'application/gzip'}.get(path.suffix,'text/plain'),
        path.suffix[1:])).to_dict() for name,path in pairs}


def run():
    research = context()
    check = read(WORK/'others/checks.json')
    if (check['status'] != 'PASS' or check['study_sha256'] != digest(Path(__file__))
            or check['check_sha256'] != digest(WORK/'src/check.py')):
        raise ValueError('Run checks on exact source first')
    pre = materials(research, [('design',WORK/'protocols/design.md'),
        ('authorization',WORK/'protocols/authorization.md'), ('study-source',Path(__file__)),
        ('checks',WORK/'others/checks.json'), ('check-source',WORK/'src/check.py'),
        ('verification-source',WORK/'src/verify.py'),
        ('original-pat',OLD/'src/strategy.py'), ('prepared-reference',PREP)])
    save(WORK/'others/pre_run_evidence.json', pre)
    print('DESIGN_AND_SOURCE_PUBLISHED', flush=True)
    bars, constraints, identities = fetch(research)
    print('INPUTS_AUTHENTICATED', identities, flush=True)
    eligible = [i for i in range(260,len(bars)-1)
        if bars.iloc[i+1].BarStart.tz_convert('America/New_York').date() >= date(2019,1,2)]
    chunks = np.array_split(np.array(eligible),2)
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        scanned = sorted(sum(pool.map(scan_chunk, [(bars, x.tolist()) for x in chunks]), []))
    signal = {i for i,flag,_ in scanned if flag}
    print('SIGNALS', len(signal), 'OF', len(eligible), flush=True)
    allrows, summaries = [], {}
    for n in HORIZONS:
        sparse = nonoverlap(sorted(signal), n)
        rows = []
        for i in eligible:
            row = label(bars,constraints,i,n)
            at = bars.iloc[i+1].BarStart.tz_convert('America/New_York')
            row.update(signal=i in signal, nonoverlap=i in sparse, date=str(at.date()),
                month=at.strftime('%Y-%m'), stratum=at.strftime('%Y-%m|%H:%M'),
                signal_at=bars.iloc[i].Date.isoformat(), entry_at=bars.iloc[i+1].BarStart.isoformat())
            rows.append(row)
        chosen = [r for r in rows if r['signal']]
        reduced = [r for r in rows if r['nonoverlap']]
        match_all,_ = matched(rows, chosen)
        match_reduced,pairs = matched(rows,reduced)
        summaries[str(n)] = {'all':summarize(rows), 'pat':summarize(chosen),
            'nonoverlap_pat':summarize(reduced), 'matched_pat':match_all,
            'matched_nonoverlap_pat':match_reduced}
        if n == 13:
            summaries[str(n)]['monthly_block_bootstrap'] = bootstrap(pairs)
            summaries[str(n)]['years'] = {}
            for year in range(2019,2026):
                subset = [r for r in rows if r['date'].startswith(str(year))]
                part = [r for r in subset if r['signal']]
                summaries[str(n)]['years'][str(year)] = {'all':summarize(subset),
                    'pat':summarize(part), 'matched':matched(subset,part)[0]}
        allrows.extend(rows)
        print('HORIZON', n, json.dumps({k:v['price'] for k,v in summaries[str(n)].items()
              if k in ('all','pat','nonoverlap_pat')}), flush=True)
    event_bytes = json.dumps(allrows, ensure_ascii=False, default=str, allow_nan=False).encode('utf-8')
    (WORK/'others/events.json.gz').write_bytes(gzip.compress(event_bytes, mtime=0))
    save(WORK/'others/analysis.json', {'schema':'s017-pat-event-diagnosis/v1',
        'experiment':EXPERIMENT.to_dict(), 'prepared':read(PREP)['reference'],
        'inputs':identities, 'original_pat_sha256':PAT_SHA, 'study_sha256':digest(Path(__file__)),
        'protocol_sha256':digest(WORK/'protocols/design.md'), 'events_sha256':digest(WORK/'others/events.json.gz'),
        'eligible':len(eligible), 'pat_signals':len(signal), 'horizons':summaries,
        'new_strategy_configurations':0,'new_accounts':0,'reserved_2026_used':False,
        'scope':'Information and independent single-share price labels; not account performance.'})


def publish():
    research = context()
    pre = read(WORK/'others/pre_run_evidence.json')
    for ref in pre.values():
        EvidenceRef.from_dict(ref).resolve(ROOT)
    for name,path in [('design',WORK/'protocols/design.md'),('study-source',Path(__file__)),
                      ('checks',WORK/'others/checks.json'),('check-source',WORK/'src/check.py')]:
        if pre[name]['sha256'] != digest(path):
            raise ValueError('Pre-run material changed: '+name)
    analysis = read(WORK/'others/analysis.json')
    if analysis['events_sha256'] != digest(WORK/'others/events.json.gz'):
        raise ValueError('Event table changed')
    if (analysis['study_sha256'] != digest(Path(__file__))
            or analysis['protocol_sha256'] != digest(WORK/'protocols/design.md')):
        raise ValueError('Analysis source/protocol identity changed')
    judgment = read(WORK/'others/judgment.json')
    validation = read(WORK/'others/result_validation.json')
    if (judgment['analysis_sha256'] != digest(WORK/'others/analysis.json')
            or validation['status'] != 'PASS'
            or validation['analysis_sha256'] != digest(WORK/'others/analysis.json')
            or validation['events_sha256'] != analysis['events_sha256']
            or validation['verification_source_sha256'] != digest(WORK/'src/verify.py')
            or pre['verification-source']['sha256'] != digest(WORK/'src/verify.py')):
        raise ValueError('Judgment or result verification is stale/incomplete')
    extra = materials(research, [('analysis',WORK/'others/analysis.json'),
        ('events',WORK/'others/events.json.gz'), ('judgment',WORK/'others/judgment.json'),
        ('result-validation',WORK/'others/result_validation.json')])
    refs = tuple(EvidenceRef.from_dict(r) for r in [*pre.values(),*extra.values()])
    ref = publish_evidence(research, ExperimentReportWrite(EXPERIMENT,
        digest(WORK/'report.md'), ExperimentOutcome.COMPLETED, refs))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'report':ref.to_dict(),'validation':validation.to_dict(),
         'materials':extra,'new_accounts':0,'panel_published':False})
    if validation.status.value != 'PASS':
        raise RuntimeError('Publication validation failed')
    print('REPORT_PUBLICATION PASS', ref.to_dict(), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run','publish'])
    action = parser.parse_args().action
    run() if action == 'run' else publish()
