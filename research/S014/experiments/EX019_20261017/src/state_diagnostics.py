"""Fixed, close-known P/D states on every original H3 entry; offline paired labels."""
from datetime import datetime, time
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import requests
from czsc_trader.research_tools import EvidenceRef
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / 'research/S014/experiments/EX017_20261017'
sys.path.insert(0, str(OLD / 'src'))
from audit_accounts import FULL_INPUT_REFERENCE, frame, load_frames


def stats(values):
    v = pd.Series(values, dtype=float).dropna()
    v = v.mask(v.abs().lt(1e-12), 0.)
    tail_n = max(1, int(np.ceil(len(v)*.1)))
    return dict(n=len(v), mean=float(v.mean()) if len(v) else None,
                median=float(v.median()) if len(v) else None,
                positive=int(v.gt(0).sum()), negative=int(v.lt(0).sum()), zero=int(v.eq(0).sum()),
                negative_fraction=float(v.lt(0).mean()) if len(v) else None,
                positive_sum=float(v.clip(lower=0).sum()), negative_sum=float(v.clip(upper=0).sum()),
                positive_contribution_to_mean=float(v.clip(lower=0).mean()) if len(v) else None,
                negative_contribution_to_mean=float(v.clip(upper=0).mean()) if len(v) else None,
                min=float(v.min()) if len(v) else None,
                p10=float(v.quantile(.1)) if len(v) else None,
                worst_10pct_mean=float(v.nsmallest(tail_n).mean()) if len(v) else None,
                worst_10pct_n=tail_n if len(v) else 0,
                remove_top3_mean=float(v.sort_values().iloc[:-3].mean()) if len(v)>3 else None,
                remove_top5_mean=float(v.sort_values().iloc[:-5].mean()) if len(v)>5 else None)


def iso(day):
    return pd.Timestamp(day).date().isoformat() if day is not None else None


def main():
    output = EX / 'others/state_diagnostics_v2.json'
    if output.exists():
        raise RuntimeError('Preserve completed diagnostic evidence')
    requests.sessions.Session.request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Offline only'))
    prior = OLD / 'others/result.json'
    ref = EvidenceRef.from_dict(json.loads(prior.read_text(encoding='utf-8'))['evidence']['account-high-h3'])
    content = ref.resolve(ROOT).read_bytes()
    assert sha256(content).hexdigest() == ref.sha256
    evidence = json.loads(content)
    assert len(evidence['runs']) == 1
    tables = {k: frame(v) for k, v in evidence['runs'][0]['ledgers'].items()}
    daily = tables['account_daily'].copy()
    daily['date'] = pd.to_datetime(daily.date).dt.normalize()
    daily = daily.set_index('date').sort_index()
    fills = tables['fills'].copy()
    fills['day'] = pd.to_datetime(fills.fill_time).dt.normalize()
    inputs = load_frames()
    data_hashes = {k: sha256(v.to_json(orient='table', date_format='iso', double_precision=15).encode()).hexdigest() for k, v in inputs.items()}
    market, raw, limits, status = [inputs[k].set_index(pd.to_datetime(inputs[k].Date)).sort_index()
                                 for k in ('stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')]
    anchor = float(market.loc[daily.index[0], 'Close']/daily.close.iloc[0])
    scaled = market[['Open', 'High', 'Low', 'Close']]/anchor
    scales = market.Close/raw.Close/anchor
    assert np.allclose(scaled.loc[daily.index, 'Close'], daily.close, rtol=0, atol=1e-9)
    assert scales.gt(0).all() and len(daily)==1642
    trading = pd.DatetimeIndex(status.index[status.Status.eq('TRADING')])
    trading = trading[trading.isin(market.index)]
    assert daily.index.isin(trading).all()
    attempts = []

    def exit_label(start, quantity, cycle_id, horizon):
        if start >= len(trading):
            return None
        for j in range(start, len(trading)):
            day = trading[j]
            bar, bound = scaled.loc[day], limits.loc[day]
            result = resolve_fill(OrderSpec('SELL', 'MARKET', quantity),
                session_open=float(bar.Open), session_time=datetime.combine(day.date(), time(9,30)),
                intraday_touches=(), daily_quote=DailyQuote(float(bar.Low), float(bar.High)),
                session_limits=SessionPriceLimits(day.date(), float(bound.DownLimit*scales.loc[day]),
                    float(bound.UpLimit*scales.loc[day]), float(.01*scales.loc[day])))
            attempts.append(dict(cycle_id=cycle_id, horizon=horizon, day=iso(day),
                                 filled=bool(result.filled), price=float(result.price) if result.filled else None,
                                 raw_open=float(raw.loc[day,'Open']), normalized_open=float(bar.Open),
                                 price_scale=float(scales.loc[day]), tick=float(.01*scales.loc[day])))
            if result.filled:
                return dict(day=day, price=float(result.price), delay=j-start, precision=str(result.time_precision))
        return None

    rows = []
    original_checks = 0
    for t in tables['trades'].itertuples():
        entry = pd.Timestamp(t.entry_date).normalize()
        pos = int(trading.get_loc(entry))
        f = fills.loc[fills.cycle_id.eq(t.cycle_id)]
        buy = f.loc[f.side.eq('BUY')]
        sell = f.loc[f.side.eq('SELL')]
        assert len(buy)==1 and len(sell)<=1
        b = buy.iloc[0]
        outlay = float(b.quantity*b.price+b.fees)
        assert np.isclose(b.fees, b.quantity*b.price*.001, atol=1e-9)
        row = dict(cycle_id=t.cycle_id, original_status=t.status, entry_date=iso(entry), entry_year=entry.year,
                   quantity=int(b.quantity), entry_price=float(b.price), entry_outlay=outlay,
                   decision_date=None, previous_close_date=None, decision_close=None, previous_close=None,
                   P_value=None, D_value=None, P=None, D=None, state='DECISION_RIGHT_CENSORED',
                   original_target_exit=None, extended_target_exit=None, original_actual_exit=None,
                   extended_actual_exit=None, original_delay=None, extended_delay=None,
                   h3_net_return=None, h6_net_return=None, extension_increment=None,
                   actual_h3_exit_profitable=None, P_vs_actual_exit_mismatch=None, label_status='RIGHT_CENSORED')
        if pos+2 < len(trading):
            decision = trading[pos+2]
            prev = trading[pos+1]
            close = float(scaled.loc[decision,'Close'])
            previous = float(scaled.loc[prev,'Close'])
            p_value = close/(float(b.price)*1.001)-1
            d_value = close/previous-1
            p, d = bool(p_value>0), bool(d_value>0)
            assert entry <= prev < decision
            # The two state calculations use only recorded fill and completed closes.
            prefix = scaled.loc[:decision]
            assert p_value == float(prefix.iloc[-1].Close)/(float(b.price)*1.001)-1
            assert d_value == float(prefix.iloc[-1].Close)/float(prefix.loc[prev,'Close'])-1
            row.update(decision_date=iso(decision), previous_close_date=iso(prev), decision_close=close,
                       previous_close=previous, P_value=p_value, D_value=d_value, P=p, D=d,
                       state=f'P{int(p)}_D{int(d)}')
        h3 = exit_label(pos+3, int(b.quantity), t.cycle_id, 3)
        h6 = exit_label(pos+6, int(b.quantity), t.cycle_id, 6)
        for name, offset, label in [('original',3,h3),('extended',6,h6)]:
            row[name+'_target_exit'] = iso(trading[pos+offset]) if pos+offset<len(trading) else None
            if label is not None:
                row[name+'_actual_exit'] = iso(label['day'])
                row[name+'_delay'] = label['delay']
                assert pd.Timestamp(row['decision_date']) < label['day']
        if h3 is not None:
            assert len(sell)==1 and t.status=='CLOSED'
            s = sell.iloc[0]
            assert s.day == h3['day'] and np.isclose(float(s.price),h3['price'],rtol=0,atol=1e-9)
            assert np.isclose(s.fees,s.quantity*s.price*.001,atol=1e-9)
            h3_return = float((s.quantity*s.price-s.fees)/outlay-1)
            assert np.isclose(h3_return,t.net_return,atol=1e-12)
            row.update(h3_net_return=h3_return, actual_h3_exit_profitable=bool(h3_return>0),
                       P_vs_actual_exit_mismatch=bool(row['P'] != bool(h3_return>0)))
            original_checks += 1
        else:
            assert len(sell)==0 and t.status=='OPEN'
        if h3 is not None and h6 is not None:
            h6_return = float(b.quantity*h6['price']*.999/outlay-1)
            row.update(h6_net_return=h6_return, extension_increment=h6_return-row['h3_net_return'],label_status='OBSERVED')
        rows.append(row)
    members = pd.DataFrame(rows)
    assert len(members)==147 and original_checks==146
    assert members.state.ne('DECISION_RIGHT_CENSORED').sum()==146
    summaries, confusion, rules = [], [], []
    for scope in ['ALL','WITHOUT2026',*[str(y) for y in range(2020,2027)]]:
        cohort = (members if scope=='ALL' else members.loc[members.entry_year.le(2025)] if scope=='WITHOUT2026' else members.loc[members.entry_year.eq(int(scope))]).copy()
        cutoff = '2025-12-31' if scope=='WITHOUT2026' else '2026-10-15'
        # A state first observed in 2026 must remain unknown in the truncated view.
        cohort.loc[cohort.decision_date.isna() | cohort.decision_date.gt(cutoff), 'state'] = 'DECISION_RIGHT_CENSORED'
        eligible = cohort.loc[cohort.decision_date.notna() & cohort.decision_date.le(cutoff)]
        observed = eligible.loc[eligible.label_status.eq('OBSERVED') & eligible.extended_actual_exit.le(cutoff) & eligible.original_actual_exit.le(cutoff)]
        for state in ['ALL','P0_D0','P0_D1','P1_D0','P1_D1','DECISION_RIGHT_CENSORED']:
            c = cohort if state=='ALL' else cohort.loc[cohort.state.eq(state)]
            q = observed if state=='ALL' else observed.loc[observed.state.eq(state)]
            summaries.append(dict(scope=scope,state=state,entries=len(c),observed=len(q),right_censored=len(c)-len(q),
                                  extension=stats(q.extension_increment),h3_return=stats(q.h3_net_return),h6_return=stats(q.h6_net_return)))
        known_exit = eligible.loc[eligible.h3_net_return.notna() & eligible.original_actual_exit.le(cutoff)]
        for p in [False,True]:
            for realized in [False,True]:
                q = known_exit.loc[known_exit.P.eq(p) & known_exit.actual_h3_exit_profitable.eq(realized)]
                confusion.append(dict(scope=scope,P=p,actual_h3_exit_profitable=realized,n=len(q),
                                      mismatch=p!=realized,mean_h3_net_return=float(q.h3_net_return.mean()) if len(q) else None))
        for name, mask in [('P', observed.P.eq(True)),('D', observed.D.eq(True)),
                           ('P_AND_D',observed.P.eq(True)&observed.D.eq(True)),
                           ('P_OR_D',observed.P.eq(True)|observed.D.eq(True))]:
            q = observed.loc[mask]
            paired = observed.extension_increment.where(mask,0.)
            rules.append(dict(scope=scope,rule=name,observed_original_entries=len(observed),selected=len(q),
                              selected_extension=stats(q.extension_increment),
                              effective_increment_on_original_entry_set=stats(paired)))
        assert sum(r['observed'] for r in summaries if r['scope']==scope and r['state'] in ['P0_D0','P0_D1','P1_D0','P1_D1'])==len(observed)
    outputs = {'members':members,'summary':pd.json_normalize(summaries),
               'confusion':pd.DataFrame(confusion),'fixed_rules':pd.json_normalize(rules),
               'fill_attempts':pd.DataFrame(attempts)}
    fingerprints = {}
    for name, value in outputs.items():
        path = EX/f'others/state_diagnostics_v2_{name}.csv'
        if path.exists():
            raise RuntimeError('Preserve '+path.name)
        value.to_csv(path,index=False,lineterminator='\n')
        fingerprints[path.name]=sha256(path.read_bytes()).hexdigest()
    result = dict(status='PASS',source_calls=0,new_account_runs=0,account_evidence=ref.to_dict(),
                  correction='v2 marks the 2025-12-31 entry decision unknown at the WITHOUT2026 cutoff; its P1_D1 state is only observed on 2026-01-06. No return, rule, or confusion result changes. Initial output retained.',
                  account_result_hash=evidence['result_hash'],prepared_input=FULL_INPUT_REFERENCE,
                  source_frame_json_sha256=data_hashes,script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  method={'universe':'All 147 actual original highH3 entries: 146 CLOSED plus one terminal OPEN; no restriction to H6 common entries.',
                          'state':'At E+2 close, P=normalized close/(actual entry price*1.001)-1>0; D=close/prior tradable close-1>0. Exact zero thresholds fixed, no search; decision known after close.',
                          'label':'Same actual quantity sold at E+3 vs E+6 using public resolve_fill, blocked exits retried on later tradable sessions; both charge 0.001 sell fees. Existing buy outlay includes actual buy fee.',
                          'scope':'Annual cohorts use actual entry year, not annual account profit. WITHOUT2026 truncates observation at 2025-12-31 and explicitly censors labels not yet observable.',
                          'pnl_comparison':'Actual H3 exit profitability is future information relative to E+2; used solely for mismatch diagnostics.',
                          'fixed_rules':'P,D,P_AND_D,P_OR_D paired labels share original H3 entries. Unselected increment is zero; this is not a continuous account because extension can change later entry opportunities.',
                          'trimming':'Delete highest 3/5 individual increments or returns and recompute arithmetic mean; no executable counterfactual.',
                          'precision':'1e-12 tolerance only normalizes reported near-zero labels; P and D classifiers retain the specified strict >0.',
                          'censoring':'No invented post-window prices or terminal sell fees. The terminal OPEN lacks E+2 state and future exit labels.'},
                  price_scale_audit=dict(hfq_normalization_anchor=anchor,
                                         max_account_close_error=float(np.max(np.abs(scaled.loc[daily.index,'Close'].to_numpy()-daily.close.to_numpy()))),
                                         min_raw_to_normalized_scale=float(scales.min()),max_raw_to_normalized_scale=float(scales.max()),
                                         raw_limits_and_tick='Each execution date raw limits and 0.01 raw tick multiplied by contemporaneous normalized HFQ/raw close ratio.'),
                  checks=dict(all_entries=147,original_closed_exits_reproduced=original_checks,
                              full_observed_pairs=int(members.label_status.eq('OBSERVED').sum()),
                              decision_right_censored=int(members.state.eq('DECISION_RIGHT_CENSORED').sum()),
                              delayed_original_exits=int(members.original_delay.fillna(0).gt(0).sum()),
                              delayed_extended_exits=int(members.extended_delay.fillna(0).gt(0).sum()),
                              public_txe_used=True,source_evidence_sha256_verified=True,
                              close_prefix_equivalence=True,state_before_both_exit_labels=True,
                              four_states_disjoint_and_exhaustive=True),
                  summary=summaries,confusion=confusion,fixed_rules=rules,outputs=fingerprints)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':result['status'],'checks':result['checks'],
                      'summary':[r for r in summaries if r['scope'] in ['ALL','WITHOUT2026']],
                      'confusion':[r for r in confusion if r['scope'] in ['ALL','WITHOUT2026']]},indent=2))


if __name__=='__main__':
    main()
