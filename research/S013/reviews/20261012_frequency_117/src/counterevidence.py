"""Existing natural A/B ledgers and emitted trace interpretation, read only.

No re-entry replay, new signal/model, hypothetical return or evaluation. An
actual control trade at a rejection date is observed evidence, never the
profit that would be earned if that gate were removed from the other account.
"""
from collections import Counter
from hashlib import sha256
import json
from math import ceil
from pathlib import Path

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=Path(__file__).resolve().parent
REVIEW=ROOT/'.tmp/s013-new-four-203/results.json'
TOP=('C0507','C0509','C2008','C2009','C9029','C9030')
PAIRS=(('C2002','C2018','Original same route/range/regime with confirmation disabled vs enabled allscore-.2'),
       ('C2008','C2308','Same route/regime package: confirmation disabled vs turnover confirmation only after regime exit'),
       ('C2308','C3105','Exact original strategy plus ordinary bull entry complement confirmation allscore-.35'),
       ('C8880','C9070','Exact original boundary/recovery strategy plus current4-session OR alternative confirmation'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text('utf-8-sig'))


def signature(rows, fields):
    return sha256(json.dumps([{name:row[name] for name in fields} for row in rows],sort_keys=True,separators=(',',':')).encode()).hexdigest()


def native(row):
    path=ROOT/row['source']
    if digest(path)!=row['source_sha256']:
        raise ValueError('Latest reviewed native source SHA mismatch')
    value=read(path)
    if len(value['runs'])!=1:
        raise ValueError('Exactly one already published full baseline account required')
    return value['runs'][0]


def candidate(cid):
    registration=read(ROOT/'research/registrations/S013/candidates'/(cid+'.json'))['record']
    root=ROOT/'research/S013'
    payload_path=root/registration['payload']['path']
    if digest(payload_path)!=registration['payload']['sha256']:
        raise ValueError('Retained candidate payload SHA mismatch')
    return read(payload_path),root/registration['source_root']


def compact(row):
    e,g=row['economics'],row['gates_v2']
    return {'candidate':row['candidate_id'],'net_cagr':e['net_cagr'],'full_drawdown':e['full_drawdown'],
        'positive_closed_cycles':g['positive_closed_cycles'],'positive_sessions':g['positive_sessions'],
        'positive_frequency60':g['positive_frequency60'],'needed_closed_cycles':ceil(g['positive_sessions']/15),
        'shortfall':ceil(g['positive_sessions']/15)-g['positive_closed_cycles'],
        'annual':{year:{key:values[key] for key in ('return','drawdown','closed_cycles')} for year,values in e['annual'].items()},
        'gates_v2':g['gates'],'native_source':row['source'],'native_sha256':row['source_sha256']}


def closed_links(run):
    fills=run['ledgers']['fills']['data']
    trades={row['cycle_id']:row for row in run['ledgers']['trades']['data'] if row['status']=='CLOSED'}
    cash=Counter()
    for f in fills:
        cash[f['cycle_id']]+=(-1 if f['side']=='BUY' else 1)*f['quantity']*f['price']-f['fees']
    buys={}
    for f in fills:
        if f['side']=='BUY':
            buys.setdefault(f['signal_date'],set()).add(f['cycle_id'])
    return buys,trades,cash


def observed_rejection_links(control,treatment,positive_years):
    off=control['ledgers']['decisions']['data']
    on=treatment['ledgers']['decisions']['data']
    if [r['signal_date'] for r in off]!=[r['signal_date'] for r in on]:
        raise ValueError('Same full decision axis required')
    buy,trades,cash=closed_links(control)
    first=next((i for i,(a,b) in enumerate(zip(off,on)) if a['target_position']!=b['target_position']),None)
    links=[]
    for i,(a,b) in enumerate(zip(off,on)):
        rejected=b['signal_reason']=='confirmation_rejected' and b.get('confirmation_opportunity') is True
        if rejected and a['signal_reason']=='entry':
            for cycle in sorted(buy.get(a['signal_date'],())):
                if cycle not in trades:
                    continue
                trade=trades[cycle]
                links.append({'signal_date':a['signal_date'],'control_cycle':cycle,'actual_control_entry_date':trade['entry_date'],
                    'actual_control_exit_date':trade['exit_date'],'actual_control_net_return':trade['net_return'],
                    'actual_control_net_cash_pnl':cash[cycle],'exit_year_positiveBH_expost_only':int(trade['exit_date'][:4]) in positive_years,
                    'first_target_divergence':i==first,'treatment_regime':b.get('regime'),
                    'treatment_extra_confirmation_failed':b.get('opportunity_confirmation_pass') is False,
                    'preceding_exposure_same':i==0 or a.get('target_position')==b.get('target_position') or off[i-1]['target_position']==on[i-1]['target_position']})
    rejected=[r for r in on if r['signal_reason']=='confirmation_rejected' and r.get('confirmation_opportunity') is True]
    actualpositive=[r for r in links if r['actual_control_net_cash_pnl']>0]
    return {'first_target_divergence_signal':None if first is None else off[first]['signal_date'],
        'treatment_qualified_rejection_count':len(rejected),'observed_control_closed_trade_links':len(links),
        'observed_control_profitable_links':len(actualpositive),'observed_control_losing_links':sum(r['actual_control_net_cash_pnl']<0 for r in links),
        'positiveBH_exit_year_profitable_control_links':sum(r['exit_year_positiveBH_expost_only'] for r in actualpositive),
        'first_divergence_links':[r for r in links if r['first_target_divergence']],
        'links':links,'interpretation':'Actual existing control trades only. Not treatment counterfactual profits, additive missed PnL, or guaranteed additional closed cycles.'}


def alternative_links(run,positive_years):
    buys,trades,cash=closed_links(run)
    decision=run['ledgers']['decisions']['data']
    alt=[r for r in decision if r.get('alt_only_entry') is True and r['signal_reason']=='entry']
    cycles={cycle for r in alt for cycle in buys.get(r['signal_date'],())}
    closed=[{'cycle':cycle,'actual_exit':trades[cycle]['exit_date'],'actual_cash_pnl':cash[cycle],
             'positiveBH_exit_year_expost_only':int(trades[cycle]['exit_date'][:4]) in positive_years} for cycle in sorted(cycles) if cycle in trades]
    return {'emitted_alt_only_opportunity':sum(r.get('alt_only_opportunity') is True for r in decision),
        'emitted_alt_only_entry':len(alt),'alt_entry_actual_buy_cycles':len(cycles),'alt_entry_actual_closed_cycles':len(closed),
        'actual_closed_profitable':sum(r['actual_cash_pnl']>0 for r in closed),'actual_closed_losing':sum(r['actual_cash_pnl']<0 for r in closed),
        'positiveBH_exit_year_closed':sum(r['positiveBH_exit_year_expost_only'] for r in closed),'closed':closed,
        'interpretation':'Diagnostic opportunity flags precede BODY gate; entry flags still precede limit execution; observed actual cycles are not net incremental account benefit.'}


def run():
    review=read(REVIEW)
    rows={r['candidate_id']:r for r in review['rows']}
    ids=set(TOP)|{cid for a,b,_ in PAIRS for cid in (a,b)}
    saved={cid:native(rows[cid]) for cid in ids}
    signatures={}
    for cid in TOP:
        ledgers=saved[cid]['ledgers']
        signatures[cid]={
            'target_and_reason':signature(ledgers['decisions']['data'],('signal_date','target_position','signal_reason')),
            'full_cash_quantity_equity':signature(ledgers['account_daily']['data'],('date','cash','quantity','close','equity')),
            'actual_fills_without_identity':signature(ledgers['fills']['data'],('signal_date','fill_time','side','quantity','price','fees','trigger')),
            'actual_trades_without_identity':signature(ledgers['trades']['data'],('status','entry_date','exit_date','quantity','entry_price','exit_price','net_return'))}
    unique={name:len({v[name] for v in signatures.values()}) for name in next(iter(signatures.values()))}
    paired=[]
    sources={}
    for a,b,basis in PAIRS:
        ap,ar=candidate(a)
        bp,br=candidate(b)
        ae,be=compact(rows[a]),compact(rows[b])
        pyears=set(rows[a]['gates_v2']['positive_years'])
        paired.append({'control':ae,'treatment':be,'basis':basis,
            'parameter_payloads':{'control':ap['parameters'],'treatment':bp['parameters']},
            'delta':{'positive_closed_cycles':be['positive_closed_cycles']-ae['positive_closed_cycles'],
                'net_cagr':be['net_cagr']-ae['net_cagr'],
                'annual_return':{y:be['annual'][y]['return']-ae['annual'][y]['return'] for y in ae['annual']}},
            'observed_rejection_control_trades':observed_rejection_links(saved[a],saved[b],pyears),
            'observed_short_alternative':alternative_links(saved[b],pyears) if b=='C9070' else None})
        for cid,p,root in ((a,ap,ar),(b,bp,br)):
            for name in ('confirmed_range.py','reentry_confirmed_range.py','complement_confirmed_range.py','short_alternative_range.py'):
                path=root/'strategies'/name
                if path.exists():
                    sources[path.relative_to(ROOT).as_posix()]=digest(path)
    out={'status':'PASS','kind':'EXISTING_NATURAL_AB_LEDGER_DIAGNOSTICS_ONLY','new_accounts':0,'new_signals':0,
        'provider_calls':0,'new_experiments':0,'parameter_changes':0,'source_review':REVIEW.relative_to(ROOT).as_posix(),
        'source_review_sha256':digest(REVIEW),'top_six':{cid:compact(rows[cid]) for cid in TOP},
        'top_six_observed_behavior_unique_counts':unique,'top_six_signatures':signatures,
        'top_six_confirmation_disabled':'C0507/0509 AdaptiveRange; C9029/9030 exact adaptive derivations; C2008/2009 confirmation.enabled=False directly delegates AdaptiveRange',
        'pairs':paired,'source_code_sha256':sources,
        'limits':['BH yearly sign only ex-post exit-year diagnostics, never strategy signal.',
                  'False confirmation_pass alone is not a rejected opportunity: require reason plus flat eligible opportunity.',
                  'Target entry is not fill; partial/unfilled orders and real closed exit dates matter.',
                  'Different account clocks, exposure, cash and later opportunities prevent additive attribution or counterfactual return.',
                  'Six IDs with same observed path are not six independent confirmations; no claim of global logical equivalence.',
                  'Only frozen already registered candidate pairs; no hypothetical relaxed gate/signals, optimisation or new experiment.']}
    (WORK/'counterevidence.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('unique_top_six',unique)
    for pair in paired:
        r=pair['observed_rejection_control_trades']
        print(pair['control']['candidate'],pair['treatment']['candidate'],'delta',pair['delta']['positive_closed_cycles'],round(pair['delta']['net_cagr']*100,4),'rejectionlinks',r['observed_control_closed_trade_links'],'profitable',r['observed_control_profitable_links'],'first',r['first_divergence_links'])
        if pair['observed_short_alternative']:
            print('alternative',{k:v for k,v in pair['observed_short_alternative'].items() if k not in ('closed','interpretation')})


if __name__=='__main__':
    run()
