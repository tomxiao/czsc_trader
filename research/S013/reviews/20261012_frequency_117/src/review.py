"""Read-only ranking and recorded-event frequency review, no policy replay.

Forward OPEN windows are hindsight price descriptions at existing H4/H8,
never counterfactual strategy signals/accounts or ex-ante profitable forecasts.
"""
from collections import Counter, defaultdict
from hashlib import sha256
from math import floor
from pathlib import Path
import json

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-frequency-117'
INPUT=ROOT/'research/S013/reviews/20261012_new_four_203/results.json'
DEEP=('C0507','C0509','C2008','C2009','C9029','C9030','C9070','C3105','C8880')

def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))

def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()

def signature(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')

def native(row):
    path=ROOT/row['source']
    assert digest(path)==row['source_sha256']
    data=read(path)
    assert len(data['runs'])==1
    return data['runs'][0]['replay_evidence']

def payload(cid):
    rec=read(ROOT/f'research/registrations/S013/candidates/{cid}.json')['record']
    path=ROOT/'research/S013'/rec['payload']['path']
    assert digest(path)==rec['payload']['sha256']
    for ref in rec['source_files']:
        assert digest(ROOT/'research/S013'/ref['path'])==ref['sha256']
    return read(path),rec

def economic_path(replay):
    return signature({'account':[{k:r[k] for k in ('date','cash','quantity','equity','close')} for r in replay['account_daily']],
        'fills':[{k:r[k] for k in ('fill_time','side','price','quantity','fees')} for r in replay['fills']],
        'targets':[(d['signal_date'],int(d['target_position'])) for d in replay['decisions']]})

def deep(row,years):
    re=native(row)
    params,rec=payload(row['candidate_id'])
    p=params['parameters']
    days=re['execution_daily']
    date_index={r['date'][:10]:i for i,r in enumerate(days)}
    accounts={r['date'][:10]:r for r in re['account_daily']}
    actual_fills={f['fill_time'][:10] for f in re['fills']}
    fills_by_decision=defaultdict(list)
    for f in re['fills']:
        fills_by_decision[f['decision_id']].append(f)
    before_signal=False
    counts=Counter()
    prices=defaultdict(list)
    events=[]
    for decision in re['decisions']:
        entry=decision['valid_session'][:10]
        t=decision['signal_date'][:10]
        account=accounts[entry]
        reason=decision['signal_reason']
        actual_held=account['quantity_before']>0
        regime=decision['regime']
        rp=p[regime]
        range_value=decision['bull_range_position'] if regime=='bull' else decision['bear_range_position']
        range_pass=range_value<=rp['entry']
        acf_value=decision.get('entry_acf_value',decision['acf1'])
        raw_acf_pass=rp['acf_min'] is None or acf_value>=rp['acf_min']
        eligible=decision.get('entry_eligible',range_pass and raw_acf_pass)
        if actual_held:
            category='ACTUAL_POSITION_OCCUPIED'
        elif before_signal:
            category='SIGNAL_HOLD_WITH_EMPTY_ACCOUNT'
        elif reason=='entry':
            category='ACCEPTED_ENTRY'
        elif reason=='confirmation_rejected':
            category='CONFIRMATION_REJECTED'
        elif reason=='entry_direction_rejected':
            category='DIRECTION_REJECTED'
        elif reason in ('time','range','regime','loss','trailing'):
            category='EXIT_SAME_T_NO_REENTRY'
        elif reason=='flat' and not range_pass and not raw_acf_pass:
            category='RANGE_AND_RAW_ACF_REJECTED'
        elif reason=='flat' and not range_pass:
            category='RANGE_REJECTED'
        elif reason=='flat' and not raw_acf_pass:
            category='RAW_ACF_REJECTED'
        elif reason=='flat' and eligible:
            category='FLAT_OTHER_RECORDED_RULE'
        else:
            category='OTHER_RECORDED_STATE'
        positive_entry=int(entry[:4]) in years
        if positive_entry:
            counts[category]+=1
        end_position=date_index[entry]+rp['max_hold']
        info={'candidate_id':row['candidate_id'],'signal_date':t,'entry_session':entry,'signal_reason':reason,
            'category':category,'regime':regime,'range_value':range_value,'range_pass':range_pass,
            'raw_acf_value':acf_value,'raw_acf_pass':raw_acf_pass,'recorded_entry_eligible':bool(eligible),
            'actual_position_before':account['quantity_before'],'prior_signal_holding':before_signal,
            'positive_entry_year':positive_entry,'H':rp['max_hold'],
            'proxy_exit_session':None,'proxy_net_open_return':None,'proxy_exit_positive_year':False,
            'open_within_known_limit':None,'whole_interval_actual_flat':False,'greedy_hindsight_selected':False}
        if end_position<len(days):
            end=days[end_position]['date'][:10]
            opening=days[date_index[entry]]['open']
            value=days[end_position]['open']/opening*(.999/1.001)-1
            scale=days[date_index[t]]['price_scale']
            tick=.001*scale
            limit=floor(days[date_index[t]]['close']*(1+rp['limit_premium'])/tick+1e-10)*tick
            interval=[r['date'][:10] for r in days[date_index[entry]:end_position+1]]
            flat=all(accounts[s]['quantity_before']==0 and accounts[s]['quantity']==0 and s not in actual_fills for s in interval)
            info.update(proxy_exit_session=end,proxy_net_open_return=value,
                proxy_exit_positive_year=int(end[:4]) in years,open_within_known_limit=opening<=limit+1e-12,
                whole_interval_actual_flat=flat)
            if positive_entry:
                prices[category].append(value)
        events.append(info)
        before_signal=bool(decision['target_position'])
    # Descriptive interval packing restricted to observed untouched cash gaps.
    # Future-positive selection is hindsight: no new orders or account path.
    windows=[e for e in events if e['category'].endswith('REJECTED') and e['proxy_exit_positive_year']
       and e['whole_interval_actual_flat'] and e['open_within_known_limit'] and e['proxy_net_open_return']>0]
    chosen=[]
    last_end=''
    for e in sorted(windows,key=lambda x:(x['proxy_exit_session'],x['entry_session'])):
        if e['entry_session']>last_end:
            e['greedy_hindsight_selected']=True
            chosen.append(e)
            last_end=e['proxy_exit_session']
    distributions={k:{'n':len(v),'positive':sum(x>0 for x in v),'mean_net_open_return':sum(v)/len(v)} for k,v in prices.items()}
    assert sum(counts.values())==1152
    return {'candidate_id':row['candidate_id'],'parameters':p,'runtime':params['runtime'],
        'source':row['source'],'source_sha256':row['source_sha256'],'source_refs':rec['source_files'],
        'positive_entry_year_category_counts':dict(counts),'hindsight_price_distributions':distributions,
        'rejected_profitable_actual_cash_gap_windows':len(windows),'nonoverlapping_hindsight_gap_windows':len(chosen),
        'economic_path_sha256':economic_path(re),'actual_buy_order_count':sum(o['side']=='BUY' for o in re['orders']),
        'actual_order_statuses':dict(Counter(o['status'] for o in re['orders'])),
        'positive_quantity_before_days':sum(r['quantity_before']>0 for r in re['account_daily'] if int(r['date'][:4]) in years),
        'actual_closed_trades':row['economics']['closed_trades'],'events':events}

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    data=read(INPUT)
    years=set(data['rows'][0]['gates_v2']['positive_years'])
    rows=[r for r in data['rows'] if all(v for k,v in r['gates_v2']['gates'].items() if k!='positive_buyhold_year_frequency')]
    assert len(rows)==117 and all(not r['gates_v2']['qualified'] for r in rows)
    rows.sort(key=lambda r:(-r['gates_v2']['positive_closed_cycles'],-r['economics']['net_cagr'],r['candidate_id']))
    profiles=defaultdict(list)
    ranking=[]
    for row in rows:
        re=native(row)
        key=economic_path(re)
        profiles[key].append(row['candidate_id'])
        e,v=row['economics'],row['gates_v2']
        reason_counts=Counter(d['signal_reason'] for d in re['decisions'] if int(d['valid_session'][:4]) in years)
        ranking.append({'candidate_id':row['candidate_id'],'positive_closed_trades':v['positive_closed_cycles'],
            'frequency60':v['positive_frequency60'],'missing_closed_trades':77-v['positive_closed_cycles'],
            'net_cagr':e['net_cagr'],'return_gate_margin_pp':100*(e['net_cagr']-1.5*data['benchmark']['benchmark_cagr']),
            'full_drawdown':e['full_drawdown'],'annual':e['annual'],
            'minimum_negative_year_return':min(e['annual'][str(y)]['return'] for y,s in data['benchmark']['benchmark_annual'].items() if s['return']<0),
            'economic_path_sha256':key,'reason_counts_positive_entry_years':dict(reason_counts),
            'source':row['source'],'source_sha256':row['source_sha256']})
        if len(ranking)%30==0:
            print({'ranked':len(ranking),'total':117},flush=True)
    detail=[deep(next(r for r in rows if r['candidate_id']==cid),years) for cid in DEEP]
    out={'kind':'READ_ONLY_117_FREQUENCY_SHORTFALL_REVIEW','source':INPUT.relative_to(ROOT).as_posix(),
        'input_sha256':digest(INPUT),'source_sha256':digest(Path(__file__)),'candidate_count':117,
        'threshold_closed_trades':77,'positive_sessions':1152,'positive_years':sorted(years),
        'distinct_economic_paths':len(profiles),'ranking':ranking,'economic_path_groups':dict(profiles),
        'nearest_ids':[r['candidate_id'] for r in ranking if r['positive_closed_trades']==ranking[0]['positive_closed_trades']],
        'detailed_recorded_event_review':detail,
        'resources':{'new_experiments':0,'new_strategy_runs':0,'new_accounts':0,'new_parameters':0,'new_market_data':0},
        'limits':['排序按真实退出所属盈利年份计数；日级诊断按入场执行日所属年份，不能相加充当真实闭合数',
          '仅读取保存的决策字段，未重建策略/生成新signals，持仓和规则分类取自原实际路径',
          'H4/H8价格窗口只作事后描述，未模拟范围/状态退出、整手与资金复利，也不是当时可识别信号',
          '现金空隙只计算固定窗口在历史实际空仓且不替换旧成交的价格片段；事后筛正和不重叠挑选不是可执行新增交易',
          'opening within known grid limit是开盘必要可行性诊断，不重新下单/撮合/计算新账本；独立审核须核对原真实限价网格']}
    write(WORK/'review.json',out)
    print({'ranked':117,'distinct_economic_paths':len(profiles),'nearest_ids':out['nearest_ids'],
        'deep':[{k:x[k] for k in ('candidate_id','positive_entry_year_category_counts','nonoverlapping_hindsight_gap_windows','rejected_profitable_actual_cash_gap_windows')} for x in detail]},flush=True)

if __name__=='__main__':
    main()
