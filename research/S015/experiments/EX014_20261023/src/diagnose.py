"""Read-only account arithmetic and declared retrospective mechanism diagnosis."""
# ruff: noqa: E402
import argparse
from collections import Counter
from datetime import date
import io
import json
import os
from pathlib import Path
import zipfile

for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[k] = '1'
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, diagnose_accounts
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef, MaterialEvidenceWrite,
    AccountDiagnosisRequest, AccountRunRef, EvaluationIdentity, EvaluationWindow,
)
from strategy_manager import CandidateKey

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX014_20261023')
HERE = EX.resolve(ROOT)
PREV = ROOT / 'research/S015/experiments/EX013_20261023'
REPS = ('C0031', 'C0228', 'C0307')
PARTS = ('new_entry', 'addition', 'holding', 'exit', 'fees', 'net_pnl')


def read(p):
    return json.loads(p.read_bytes())


def save(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))


def material(name, path):
    return publish_evidence(context(), MaterialEvidenceWrite(EX, name, path.read_bytes(),
        {'json': 'application/json', 'py': 'text/x-python', 'csv': 'text/csv'}[path.suffix[1:]], path.suffix[1:]))


def prior():
    pub = read(PREV / 'others/publication_validation.json')
    ref = EvidenceRef.from_dict(pub['materials']['dual_window_results.json'])
    return read(ref.resolve(ROOT)), ref


def prepare():
    assert not (HERE / 'protocols/diagnosis.json').exists()
    source, ref = prior()
    assert source['candidate_count'] == 86 and source['joint_pass'] == 0
    protocol = {
        'authorization': '用户同意收口当前候选路线，并继续执行研究诊断；只分析既有证据，提出下一步问题。',
        'source': ref.to_dict(), 'accounts': [r['evidence'] for r in source['rows']],
        'representatives': list(REPS),
        'selection': 'C0031 historical representative, C0228 minimum DD among return-pass candidates, C0307 minimum DD overall; all selected after EX013, not independent.',
        'scope': 'No new account, strategy, component/model experiment, tuning, data, acceptance gate, freeze or PTE.',
        'questions': ['Do86 maximum drawdowns share dates and entry/holding/exit accounting patterns?',
                      'Do representative actual entry ages differ materially from signal age?',
                      'After a timeout-only exit and no recovery to original0.005 exit threshold, do repeated actual entries carry disproportionate losses versus gains?'],
        'accounting': 'Newly bought shares*(close-buyprice); separate flat-account entry from additions; retained prior shares*(close-prevclose); sold prior shares*(sellprice-prevclose); subtract actual fees. Reconcile daily actual equity.',
        'repeat_definition': 'Actual new holding cycle after prior actual cycle closed by pure timeout (intent_age0, pressure<0.005 and previous decision age>=3), with no pressure>=0.005 from previous exit signal through new entry signal. Mixed/other/first-boundary separate. Fixed original thresholds, no new threshold selection.',
        'aggregation': 'All86 own peak-to-trough plus full account; reps full-history and entry-year closed-cycle groups, gains and losses both retained. Cohort sums are not counterfactual returns. Do not delete trades or compute changed NAV.',
        'public_diagnosis': 'Try public API once on exact C0031 common415 schema7. Preserve unsupported; RSCH arithmetic is explicitly separate from platform cycle diagnosis.',
        'limits': 'All history seen;86 correlated candidates are not86 independent market episodes. Account components do not establish causality or future predictability.',
        'resources': {'max_workers': 1, 'native_threads': 1},
    }
    save(HERE / 'protocols/diagnosis.json', protocol)
    refs = [material('diagnosis_protocol', HERE / 'protocols/diagnosis.json'), material('diagnosis_source', Path(__file__))]
    save(HERE / 'others/protocol_refs.json', [r.to_dict() for r in refs])
    print('DIAGNOSTIC_PROTOCOL_PUBLISHED', flush=True)


def normalize(tables):
    a, f, d, t = (tables[k].copy() for k in ('account_daily', 'fills', 'decisions', 'trades'))
    a['date'] = a.date.astype(str).str[:10]
    f['day'] = f.fill_time.astype(str).str[:10]
    d['day'] = d.signal_date.astype(str).str[:10]
    return a, f, d, t


def breakdown(tables):
    a, f, d, t = normalize(tables)
    assert len(a) == 415 and a.cash_before.iloc[0] == 100000 and a.quantity_before.iloc[0] == 0
    daily = []
    for i, r in a.iterrows():
        ff = f[f.day.eq(r.date)]
        b, s = ff[ff.side.eq('BUY')], ff[ff.side.eq('SELL')]
        sold = float(s.quantity.sum())
        assert sold <= r.quantity_before
        assert r.quantity == r.quantity_before + b.quantity.sum() - sold
        prevclose = float(a.close.iloc[i-1]) if i else float(r.close)
        bought = float((b.quantity * (r.close - b.price)).sum())
        before = float(a.equity.iloc[i-1]) if i else 100000.
        held = float((r.quantity_before-sold) * (r.close-prevclose))
        exit_pnl = float((s.quantity * (s.price-prevclose)).sum())
        fees, net = float(ff.fees.sum()), float(r.equity-before)
        residual = net - (bought+held+exit_pnl-fees)
        assert abs(residual) < 1e-7
        daily.append({'date': r.date, 'new_entry': bought if r.quantity_before == 0 else 0.,
                      'addition': bought if r.quantity_before != 0 else 0., 'holding': held,
                      'exit': exit_pnl, 'fees': fees, 'net_pnl': net, 'residual': residual,
                      'prior_equity': before, 'quantity_before': int(r.quantity_before), 'quantity': int(r.quantity)})
    daily = pd.DataFrame(daily)
    eq = np.r_[100000., a.equity.to_numpy(float)]
    high = np.maximum.accumulate(eq)
    trough = int(np.argmax(1-eq/high))
    peak = int(np.flatnonzero(eq[:trough+1] == high[trough])[-1])
    interval = daily.iloc[peak:trough]
    def sums(frame):
        return {k: float(frame[k].sum()) for k in PARTS}
    maximum = {'peak': 'INITIAL' if peak == 0 else a.date.iloc[peak-1], 'trough': a.date.iloc[trough-1],
               'sessions': trough-peak, 'magnitude': float(1-eq[trough]/eq[peak]),
               'peak_equity': float(eq[peak]), 'trough_equity': float(eq[trough]), 'pieces_yuan': sums(interval),
               'pieces_over_peak': {k: float(v/eq[peak]) for k, v in sums(interval).items()}}
    assert abs(maximum['pieces_yuan']['net_pnl']-(eq[trough]-eq[peak])) < 1e-7
    return {'maximum_drawdown': maximum, 'full_pieces_yuan': sums(daily),
            'max_residual': float(daily.residual.abs().max())}, daily


def cycle_groups(tables, daily):
    a, f, d, t = normalize(tables)
    d = d.sort_values('day').reset_index(drop=True)
    by_id = {r.decision_id: i for i, r in d.iterrows()}
    trade_by_id = t.set_index('cycle_id')
    cycles, previous_exit_index = [], None
    for cycle_id, ff in sorted(f.groupby('cycle_id'), key=lambda pair: pair[1].day.min()):
        ff = ff.sort_values('fill_time')
        b, s = ff[ff.side.eq('BUY')], ff[ff.side.eq('SELL')]
        first = b.iloc[0]
        entry_index = by_id[first.decision_id]
        closed = trade_by_id.loc[cycle_id, 'status'] == 'CLOSED'
        label = 'UNKNOWN_FIRST_BOUNDARY' if previous_exit_index is None else 'OTHER_ENTRY'
        if previous_exit_index is not None:
            prev = d.iloc[previous_exit_index]
            prior = d.iloc[previous_exit_index-1] if previous_exit_index else None
            pure_timeout = prev.intent_age == 0 and prev.pressure < .005 and prior is not None and prior.intent_age >= 3
            recovered = bool((d.iloc[previous_exit_index:entry_index+1].pressure >= .005).any())
            if pure_timeout and not recovered:
                label = 'UNRECOVERED_TIMEOUT_REENTRY'
        buy_value, sell_value = float((b.price*b.quantity).sum()), float((s.price*s.quantity).sum())
        remaining = float(b.quantity.sum()-s.quantity.sum())
        assert (remaining == 0) == closed
        pnl = sell_value-buy_value-float(ff.fees.sum())
        if not closed:
            pnl += remaining*float(a.close.iloc[-1])
        entry_row = a.index[a.date.eq(first.day)][0]
        capital = 100000. if entry_row == 0 else float(a.equity.iloc[entry_row-1])
        cycle = {'cycle_id': cycle_id, 'entry_day': first.day, 'entry_signal': d.day.iloc[entry_index],
                 'entry_signal_age': float(d.intent_age.iloc[entry_index]), 'class': label,
                 'closed': bool(closed), 'net_pnl': float(pnl), 'fees': float(ff.fees.sum()),
                 'pnl_over_entry_capital': float(pnl/capital), 'buy_value': buy_value,
                 'buy_fills': len(b), 'entry_day_pnl': float(daily.loc[daily.date.eq(first.day), 'new_entry'].iloc[0])}
        if closed:
            last = s.iloc[-1]
            cycle['exit_day'] = last.day
            cycle['holding_sessions'] = int(a.index[a.date.eq(last.day)][0]-entry_row)
            previous_exit_index = by_id[last.decision_id]
        cycles.append(cycle)
    assert abs(sum(c['net_pnl'] for c in cycles)-(float(a.equity.iloc[-1])-100000)) < 1e-7
    summary = []
    for period in ('ALL', '2025', '2026'):
        for label in ('UNKNOWN_FIRST_BOUNDARY', 'OTHER_ENTRY', 'UNRECOVERED_TIMEOUT_REENTRY'):
            chosen = [c for c in cycles if c['closed'] and c['class'] == label
                      and (period == 'ALL' or c['entry_day'].startswith(period))]
            summary.append({'entry_cohort': period, 'class': label, 'closed_count': len(chosen),
                'positive_cycles': sum(c['net_pnl'] > 0 for c in chosen),
                'positive_pnl': sum(max(0, c['net_pnl']) for c in chosen),
                'negative_pnl': sum(min(0, c['net_pnl']) for c in chosen),
                'net_pnl': sum(c['net_pnl'] for c in chosen), 'fees': sum(c['fees'] for c in chosen),
                'sum_pnl_over_entry_capital': sum(c['pnl_over_entry_capital'] for c in chosen)})
    return {'cycles': cycles, 'groups': summary, 'entry_age_above1': sum(c['entry_signal_age'] > 1 for c in cycles),
            'open_cycles': sum(not c['closed'] for c in cycles)}


def run():
    assert not (HERE / 'others/diagnosis_results.json').exists()
    source, ref = prior()
    protocol = read(HERE / 'protocols/diagnosis.json')
    assert protocol['source'] == ref.to_dict()
    archive_ref = EvidenceRef.from_dict(read(PREV/'protocols/fixed_set.json')['archive_reuse']['S011-v1'])
    with zipfile.ZipFile(archive_ref.resolve(ROOT)) as z:
        baseline = {k: pd.read_csv(io.BytesIO(z.read(k+'.csv')), float_precision='round_trip')
                    for k in ('account_daily', 'fills', 'decisions', 'trades')}
    results, representatives = {}, {}
    facts, daily = breakdown(baseline)
    results['S011-v1'] = facts
    daily.to_csv(HERE/'others/S011_daily.csv', index=False)
    for row in source['rows']:
        cid = row['candidate_id']
        value = read(EvidenceRef.from_dict(row['evidence']).resolve(ROOT))
        assert value['request_identity']['content_sha256'] == row['content_sha256']
        tables = {k: pd.DataFrame(v['data']) for k, v in value['runs'][0]['ledgers'].items()}
        facts, daily = breakdown(tables)
        assert abs(facts['maximum_drawdown']['magnitude']-row['maximum_drawdown']) < 1e-14
        results[cid] = {'source': row['evidence'], **facts}
        if cid in REPS:
            representatives[cid] = cycle_groups(tables, daily)
            daily.to_csv(HERE/'others'/f'{cid}_daily.csv', index=False)
        if cid == 'C0031':
            ident = value['runs'][0]['identity']
            identity = EvaluationIdentity(CandidateKey(**ident['candidate']), **{k: v for k, v in ident.items() if k != 'candidate'})
            public = diagnose_accounts(RepositoryContext.discover(ROOT), AccountDiagnosisRequest(
                AccountRunRef(EvidenceRef.from_dict(row['evidence']), identity), None,
                EvaluationWindow('s011_common', date(2025, 2, 6), date(2026, 10, 21))))
            save(HERE/'others/public_diagnosis.json', public.to_dict())
    troughs = Counter(r['maximum_drawdown']['trough'] for cid, r in results.items() if cid != 'S011-v1')
    result = {'status': 'COMPUTED_RSCH_ACCOUNTING_NOT_CAUSAL', 'source': ref.to_dict(),
        'baseline': archive_ref.to_dict(), 'accounts': results, 'representatives': representatives,
        'trough_counts_candidate_identities': dict(troughs), 'new_account_evaluations': 0,
        'public_diagnosis_status': public.status.value,
        'notes': ['No changed strategy or counterfactual NAV.', 'Representatives chosen after outcomes; descriptive only.',
                  'Cycle groups are selected by observable prior pressure/timeout state, not labels of current profit.',
                  'Exit-year or entry-cohort cycle PnL is not annual continuous account return.']}
    save(HERE/'others/diagnosis_results.json', result)
    print({'troughs': dict(troughs), 'public': public.status.value}, flush=True)
    for cid in REPS:
        print(cid, results[cid]['maximum_drawdown'],
              [g for g in representatives[cid]['groups'] if g['entry_cohort'] == 'ALL'], flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('prepare', 'run'))
    {'prepare': prepare, 'run': run}[p.parse_args().mode]()
