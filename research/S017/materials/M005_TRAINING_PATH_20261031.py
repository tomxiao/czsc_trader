import json
import os
import statistics as st
from pathlib import Path
from hashlib import sha256

ROOT = Path(__file__).resolve().parents[3]
os.environ['TEMP'] = os.environ['TMP'] = str(ROOT / '.tmp')
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity

record = json.loads((ROOT / 'research/S017/experiments/EX040_20261031/others/accounts.json').read_bytes())['C0077']
ref = EvidenceRef.from_dict(record['evidence'])
path = ref.resolve(ROOT)
content = path.read_bytes()
assert sha256(content).hexdigest() == ref.sha256
envelope = json.loads(content)
allowed = {(envelope[k]['kind'], envelope[k]['sha256']) for k in ('input_ref', 'candidate_ref', 'benchmark_ref')}

def resolve(item):
    assert (item['kind'], item['sha256']) in allowed
    raw = (path.parent / (item['sha256'] + '.json')).read_bytes()
    assert sha256(raw).hexdigest() == item['sha256']
    return raw

payload = materialize_equity(content, resolve).payload
run = payload['runs']['candidate']
if __name__ == '__main__':
    points = [p for p in run['account_points'] if '2024-01-02' <= p['session'] <= '2025-12-31']
    trades = [t for t in run['trades'] if '2024-01-02' <= t['entry_at'][:10] <= '2025-12-31']
    selected = [t for t in trades if t['status'] == 'CLOSED' and t['exit_at'][:10] <= '2025-12-31']
    fills = {f['cycle_id']: f for f in run['fills'] if f['side'] == 'BUY' and '2024-01-02' <= f['executed_at'][:10] <= '2025-12-31'}
    decisions = {d['execution_start']: d for d in run['decisions'] if d['side'] == 'BUY' and '2024-01-02' <= d['execution_start'][:10] <= '2025-12-31'}
    rows = []
    for t in selected:
        f = fills[t['cycle_id']]
        d = decisions[f['executed_at']]
        facts = {x['key']: x['text'] for x in d['explanation']['basis']}
        path_points = [p for p in points if p['cycle_id'] == t['cycle_id'] and p['quantity'] > 0]
        assert len(path_points) == 65, len(path_points)
        assert all(p['quantity'] == f['quantity'] for p in path_points)
        assert abs(f['quantity'] * f['price'] + f['fees'] - t['cost']) < 1e-6
        marks = {str(k): f['quantity'] * path_points[k-1]['close'] * .999 / t['cost'] - 1 for k in (1,13,26,39,52,65)}
        actual = t['income'] / t['cost'] - 1
        assert abs(actual-t['net_return']) < 1e-9
        row = {'entry_at':t['entry_at'],'exit_at':t['exit_at'],'cycle_id':t['cycle_id'],
            'year':t['entry_at'][:4], 'actual_net_return':actual, 'net_pnl':t['net_pnl'],
            'mark_net_returns':marks,'signal_previous_high':float(facts['previous_high']),
            'day1_close':path_points[12]['close'],
            'entry_close':float(facts['close']), 'entry_ma65':float(facts['ma65']),
            'entry_above_ma65':float(facts['close']) >= float(facts['ma65']),
            'day1_lost_reclaimed_high':path_points[12]['close'] < float(facts['previous_high']),
            'post_day1_contribution':actual-marks['13'],
            'close_mfe':max(p['close']*.999*f['quantity']/t['cost']-1 for p in path_points),
            'close_mae':min(p['close']*.999*f['quantity']/t['cost']-1 for p in path_points)}
        rows.append(row)
    def stats(items):
        if not items:
            return {'n':0}
        losses = sorted([r['actual_net_return'] for r in items if r['actual_net_return'] < 0])
        return {'n':len(items),'mean_net_return':st.mean(r['actual_net_return'] for r in items),
            'median_net_return':st.median(r['actual_net_return'] for r in items),
            'win_rate':st.mean(r['actual_net_return']>0 for r in items),
            'mean_marks':{str(k):st.mean(r['mark_net_returns'][str(k)] for r in items) for k in (1,13,26,39,52,65)},
            'post_day1_mean_contribution':st.mean(r['post_day1_contribution'] for r in items),
            'worst_five_share_of_equal_weight_losses':sum(losses[:5])/sum(losses) if losses else None,
            'mean_close_mfe':st.mean(r['close_mfe'] for r in items),'mean_close_mae':st.mean(r['close_mae'] for r in items)}
    result = {'status':'PASS','analysis_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'source_evidence':record['evidence'],
        'source_dependencies':{k:envelope[k] for k in ('input_ref','candidate_ref','benchmark_ref')},
        'window':['2024-01-02','2025-12-31'],'first_point_inherits_position':points[0]['quantity']>0,
        'entry_cohort_total':len(trades),'complete_trades':len(rows),'excluded_incomplete':len(trades)-len(rows),
        'all':stats(rows),'years':{y:stats([r for r in rows if r['year']==y]) for y in ('2024','2025')},
        'eventual_winners':stats([r for r in rows if r['actual_net_return']>0]),
        'eventual_nonwinners':stats([r for r in rows if r['actual_net_return']<=0]),
        'day1_lost_high':stats([r for r in rows if r['day1_lost_reclaimed_high']]),
        'day1_kept_high':stats([r for r in rows if not r['day1_lost_reclaimed_high']]),
        'day1_by_year':{y:{str(v):stats([r for r in rows if r['year']==y and r['day1_lost_reclaimed_high']==v]) for v in (True,False)} for y in ('2024','2025')},
        'entry_context_by_year':{y:{str(v):stats([r for r in rows if r['year']==y and r['entry_above_ma65']==v]) for v in (True,False)} for y in ('2024','2025')},
        'rows':rows,
        'scope':'Existing-account training-entry cohort only; not fresh-start training backtest. Mark returns assume liquidation at completed close less sell fee, not executable alternative accounts. First 13 completed held bars approximates one RTH session; not a calendar day. Eventual winners are hindsight descriptive groups. Day13 and entry MA65 groups are exploratory on reused training data, not independent validation; entry context was added after viewing path diagnostics. Equal-weight trade returns are not account returns; 43 executed trades do not describe all possible M005 signals. No new policy, account replay, test access or experiment round.'}
    out = Path(__file__).with_suffix('.json')
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','source_evidence','source_dependencies')},ensure_ascii=False,indent=2))
