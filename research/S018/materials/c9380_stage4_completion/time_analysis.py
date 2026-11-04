"""C9380 continuous-ledger time, concentration and paired uncertainty diagnostics."""
from pathlib import Path
import os
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
OUT = Path(__file__).resolve().parent
SCRATCH = ROOT/'.tmp/s018-c9380-time-analysis'
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH/'pycache')
os.environ['TMP'] = os.environ['TEMP'] = str(SCRATCH)
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'

from dataclasses import asdict
from hashlib import sha256
import json
import math
from time import perf_counter
import numpy as np
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity, build_equity_assessment
from strategy_evaluator import paired_stationary_bootstrap
from strategy_evaluator.bootstrap import performance_metrics
from strategy_evaluator.equity_assessment import equity_concentration


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def main():
    begun = perf_counter()
    result_path = ROOT/'research/S018/experiments/EX064_20261104/others/recovery_01/results.json'
    result = read(result_path)
    assert result['status']=='COMPLETED'
    record = result['accounts']['CENTER']
    ref = d.EvidenceRef.from_dict(record['account_ref'])
    path = ref.resolve(ROOT)
    raw = path.read_bytes()
    assert sha256(raw).hexdigest()==ref.sha256
    envelope = json.loads(raw)
    assert envelope['request']['candidate_id']=='C9380'
    assert envelope['request']['fee_rate']==.001
    assert envelope['request']['scenario_id']=='STANDARD'
    assert envelope['request']['window_id']=='MU_DEVELOPMENT'
    assert envelope['request']['drawdown_basis']=='BAR_CLOSE'
    assert envelope['request']['concentration_basis']=='MAX_SINGLE'
    output = OUT/'time_analysis.json'
    protocol_path = OUT/'time_protocol.json'
    assert not output.exists() and not protocol_path.exists(), 'Do not overwrite prior diagnostics.'
    protocol = {'status':'DECLARED_BEFORE_COMPUTATION', 'candidate':'S018-C9380',
        'candidate_content_sha256':record['content_hash'], 'source_account':ref.to_dict(),
        'source_results':result_path.relative_to(ROOT).as_posix(),
        'source_results_sha256':sha256(result_path.read_bytes()).hexdigest(),
        'data_window':'2023-01-03 through 2026-10-30, previously used development pool',
        'annual_slices':'Actual calendar-year sessions; 2026 is observed YTD, not a full year. Report realized period return and annualized return separately.',
        'slice_opening':'Prior actual session closing equity, or original initial cash at first session; inherit original holdings and cash paths.',
        'drawdown':'Use all existing account_points. Local-window DD starts from prior close; also report continuous historical-high-water drawdown without resetting old peak.',
        'rolling':{'window_sessions':252,'step_sessions':21,'start_offset':0,'only_complete_windows':True,'append_off_grid_tail_window':False},
        'underperformance':'A window is behind on Calmar iff local BAR_CLOSE Calmar minus matched BuyHold Calmar is strictly negative; annualized return shortfall separately reported.',
        'concentration':'MAX_SINGLE: largest strictly positive closed-cycle net_pnl divided by sum of all strictly positive closed-cycle net_pnl; also top5 and open cycle state.',
        'bootstrap':{'api':'strategy_evaluator.paired_stationary_bootstrap','repetitions':10000,'mean_block_length':21,'seed':9380,
            'pairing':'Identical resampled day indices for strategy and BuyHold daily net returns.',
            'calmar_basis':'Daily-closing-equity returns, not simulated BAR_CLOSE strategy replay.',
            'interval':'Percentile 95%, fixed method; no multiple block-length scan.'},
        'hard_gates_added':False,'account_replays':0,'new_data':False,
        'limits':['Repeated development sample and adaptive research selection are not corrected by this bootstrap.',
            'Overlapping rolling windows are not independent market observations.',
            'Blocks only approximate local serial dependence; future structural changes and execution paths are not generated.',
            'No stage-five or production action.']}
    save(protocol_path,protocol)
    owned={envelope[k]['sha256'] for k in ('input_ref','candidate_ref','benchmark_ref')}
    def resolve(item):
        assert item['sha256'] in owned
        content=(path.parent/(item['sha256']+'.json')).read_bytes()
        assert sha256(content).hexdigest()==item['sha256']
        return content
    material=materialize_equity(raw,resolve)
    payload=material.payload
    runs=[payload['runs']['candidate'],payload['runs']['buy_hold']]
    sessions=[row['session'] for row in runs[0]['account_daily']]
    assert sessions==[row['session'] for row in runs[1]['account_daily']]
    assert len(sessions)==961 and sessions[0]=='2023-01-03' and sessions[-1]=='2026-10-30'
    initial=float(envelope['request']['initial_cash'])
    by_session=[]
    carry_peaks=[]
    for run in runs:
        groups={session:[] for session in sessions}
        for point in run['account_points']:
            groups[point['session']].append(point)
        assert all(groups.values())
        peaks=[]
        peak=initial
        for session in sessions:
            peaks.append(peak)
            peak=max(peak,*(p['equity'] for p in groups[session]))
        by_session.append(groups)
        carry_peaks.append(peaks)

    def sliced(start,count):
        metrics=[]
        for which,(run,groups) in enumerate(zip(runs,by_session,strict=True)):
            opening=initial if start==0 else run['account_daily'][start-1]['equity']
            peak=opening
            carried_peak=carry_peaks[which][start]
            dd=carry_dd=0.
            for session in sessions[start:start+count]:
                for point in groups[session]:
                    peak=max(peak,point['equity'])
                    carried_peak=max(carried_peak,point['equity'])
                    dd=max(dd,1-point['equity']/peak)
                    carry_dd=max(carry_dd,1-point['equity']/carried_peak)
            end=run['account_daily'][start+count-1]['equity']
            total=end/opening-1
            annual=(end/opening)**(252/count)-1
            metrics.append({'opening_equity':opening,'ending_equity':end,'total_return':total,
                'annualized_return':annual,'local_bar_drawdown':dd,
                'inherited_peak_drawdown':carry_dd,'calmar':annual/dd if dd>1e-12 else None})
        a,b=metrics
        return {'start_index':start,'start':sessions[start],'end':sessions[start+count-1],
            'session_count':count,'candidate':a,'benchmark':b,
            'excess_annualized_return':a['annualized_return']-b['annualized_return'],
            'excess_calmar':None if a['calmar'] is None or b['calmar'] is None else a['calmar']-b['calmar']}
    full=sliced(0,len(sessions))
    for which,name in enumerate(('candidate','benchmark')):
        expected=record[name]
        for k,source in (('annualized_return','annual'),('local_bar_drawdown','dd'),('calmar','calmar')):
            assert math.isclose(full[name][k],expected[source],rel_tol=1e-11,abs_tol=1e-11)
    years=[]
    for year in sorted({session[:4] for session in sessions}):
        positions=[i for i,s in enumerate(sessions) if s.startswith(year)]
        row=sliced(positions[0],len(positions))
        row.update(year=year,period_label=year+' YTD' if year=='2026' else year,partial_calendar_year=year=='2026')
        years.append(row)
    windows=[sliced(i,252) for i in range(0,len(sessions)-252+1,21)]
    assert len(windows)==34
    def streaks(field):
        groups=[]
        active=[]
        for i,row in enumerate(windows):
            if row[field] is not None and row[field]<0:
                active.append(i)
            elif active:
                groups.append(active)
                active=[]
        if active: groups.append(active)
        descriptions=[{'window_indices':g,'count':len(g),'first_window_start':windows[g[0]]['start'],
            'first_window_end':windows[g[0]]['end'],'last_window_start':windows[g[-1]]['start'],
            'last_window_end':windows[g[-1]]['end']} for g in groups]
        return {'negative_windows':sum(len(g) for g in groups),'total_windows':len(windows),
            'longest_consecutive_windows':max((len(g) for g in groups),default=0),'runs':descriptions}
    excess=[w['excess_calmar'] for w in windows]
    assert all(v is not None and math.isfinite(v) for v in excess)
    rolling={'window_days':252,'step_days':21,'count':len(windows),
        'last_window_end':windows[-1]['end'],'trailing_sessions_not_in_last_grid_window':len(sessions)-windows[-1]['start_index']-252,
        'excess_calmar_q10':float(np.quantile(excess,.1,method='linear')),
        'excess_annualized_return_q10':float(np.quantile([w['excess_annualized_return'] for w in windows],.1,method='linear')),
        'calmar_underperformance':streaks('excess_calmar'),
        'annualized_return_underperformance':streaks('excess_annualized_return'),
        'worst_calmar_window':min(windows,key=lambda w:w['excess_calmar']),
        'windows':windows}
    trades=runs[0]['trades']
    assert all(t['status']=='CLOSED' for t in trades)
    winners=sorted((t for t in trades if t['net_pnl']>0),key=lambda t:t['net_pnl'],reverse=True)
    losses=[t for t in trades if t['net_pnl']<0]
    denominator=sum(t['net_pnl'] for t in winners)
    largest=winners[0]['net_pnl']/denominator
    fact,=build_equity_assessment(material)
    assert math.isclose(equity_concentration(fact),largest,rel_tol=1e-12)
    concentration={'basis':'MAX_SINGLE','denominator':'sum of positive closed-cycle net_pnl',
        'closed_cycles':len(trades),'winning_cycles':len(winners),'losing_cycles':len(losses),
        'zero_pnl_cycles':sum(t['net_pnl']==0 for t in trades),'gross_positive_net_pnl':denominator,
        'gross_negative_net_pnl':sum(t['net_pnl'] for t in losses),'all_closed_net_pnl':sum(t['net_pnl'] for t in trades),
        'largest_positive_cycle_share':largest,
        'top5_positive_cycle_share':sum(t['net_pnl'] for t in winners[:5])/denominator,
        'top5_winning_cycles':winners[:5],
        'terminal_quantity':runs[0]['account_daily'][-1]['quantity'],
        'terminal_cycle_id':runs[0]['account_daily'][-1]['cycle_id'],
        'terminal_receivable':runs[0]['account_daily'][-1]['receivable'],
        'unclosed_cycle_at_cutoff':runs[0]['account_daily'][-1]['cycle_id'] is not None,
        'net_wealth_change':runs[0]['account_daily'][-1]['equity']-initial,
        'wealth_minus_closed_pnl':runs[0]['account_daily'][-1]['equity']-initial-sum(t['net_pnl'] for t in trades),
        'se_formula_reconciled':True}
    returns=[]
    daily_metrics=[]
    for run in runs:
        values=np.r_[initial,[p['equity'] for p in run['account_daily']]]
        values=values[1:]/values[:-1]-1
        returns.append(values)
        daily_metrics.append(asdict(performance_metrics(values)))
    boot=paired_stationary_bootstrap(returns[0],returns[1],champion_id='S018-C9380',comparator_id='MU_BUYHOLD',
        repetitions=10000,mean_block_length=21,seed=9380)
    value={'schema':'s018-c9380-time-concentration-uncertainty/v1','source_account':ref.to_dict(),
        'protocol_sha256':sha256(protocol_path.read_bytes()).hexdigest(),
        'observations':len(sessions),'full_window':full,'years':years,'rolling':rolling,
        'concentration':concentration,'paired_bootstrap':asdict(boot),'daily_metric_points':dict(zip(('candidate','benchmark'),daily_metrics)),
        'bootstrap_seed':9380,'bootstrap_calmar_basis':'daily_closing_equity_returns',
        'daily_and_bar_drawdown_equal_here':all(math.isclose(daily_metrics[i]['max_drawdown']*-1,full[n]['local_bar_drawdown'],abs_tol=1e-12) for i,n in enumerate(('candidate','benchmark'))),
        'bootstrap_limits':protocol['limits'],'account_replays':0,'elapsed_seconds':perf_counter()-begun}
    save(output,value)
    annual_rows='\n'.join('|'+ '|'.join([row['period_label'],str(row['session_count']),f"{row['candidate']['total_return']:.2%}",
        f"{row['benchmark']['total_return']:.2%}",f"{row['candidate']['local_bar_drawdown']:.2%}",
        f"{row['candidate']['inherited_peak_drawdown']:.2%}",f"{row['candidate']['calmar']:.3f}",f"{row['benchmark']['calmar']:.3f}"])+'|' for row in years)
    worst=rolling['worst_calmar_window']
    c=concentration
    report=f'''# C9380 时间稳定性、收益集中性与成对统计区间

本分析仅复用EX064已发布标准中心与同条件买持的961日连续账户，新增策略回放0次。方法在计算前写入[协议](time_protocol.json)，原账户、候选参数和硬门不变。

## 年度连续账户切片

|期间|实际交易日|策略区间收益|买持区间收益|策略局部DD|继承历史高点DD|策略年化卡玛|买持年化卡玛|
|---|---:|---:|---:|---:|---:|---:|---:|
{annual_rows}

2026仅截至10月30日，属于YTD，不是完整年度。区间收益不年化；卡玛分子按实际交易日年化，完整原值另见JSON。切片以此前交易日末净值为开头，继承原资金和持仓；局部DD的高水位从切片开头起算，另列继承研究期历史高水位的DD，不冒充独立重新投入本金的回测。

## 滚动252交易日

每21个实际交易日取一个完整252日窗口，共{len(windows)}个，超额卡玛Q10为{rolling['excess_calmar_q10']:.6f}。卡玛低于同窗买持的窗口{rolling['calmar_underperformance']['negative_windows']}/{len(windows)}，最长连续{rolling['calmar_underperformance']['longest_consecutive_windows']}个；年化收益低于买持的窗口{rolling['annualized_return_underperformance']['negative_windows']}/{len(windows)}，最长连续{rolling['annualized_return_underperformance']['longest_consecutive_windows']}个。最差超额卡玛窗口为{worst['start']}—{worst['end']}，策略{worst['candidate']['calmar']:.6f}、买持{worst['benchmark']['calmar']:.6f}，差{worst['excess_calmar']:.6f}。

最后一个固定步长窗口截至{rolling['last_window_end']}，之后{rolling['trailing_sessions_not_in_last_grid_window']}个交易日仍计入全期与年度切片，但未另加偏离固定步长的尾窗。窗口高度重叠，不是34个独立市场样本。连续落后的逐段起止与全部窗口见[分析JSON](time_analysis.json)；这些诊断没有新增逐年/逐窗胜出的硬门。

## 收益集中性

95个闭合周期中，盈利{c['winning_cycles']}个、亏损{c['losing_cycles']}个、持平{c['zero_pnl_cycles']}个。所有盈利周期净利润之和{c['gross_positive_net_pnl']:.2f}美元；最大盈利周期贡献{largest:.2%}，前5盈利周期贡献{c['top5_positive_cycle_share']:.2%}。分母是全部正盈利周期的净利润之和，不是亏损抵消后的总净利润；定义与SE MAX_SINGLE一致。最大盈利周期{winners[0]['entry_at'][:10]}—{winners[0]['exit_at'][:10]}，净利润{winners[0]['net_pnl']:.2f}美元。

截止日持仓{c['terminal_quantity']}股，未闭合周期={c['unclosed_cycle_at_cutoff']}，应收款{c['terminal_receivable']:.2f}美元。财富净增与闭合周期净利润之差{c['wealth_minus_closed_pnl']:.10f}美元。没有通过删除最大盈利交易重跑策略；贡献度是现有账本描述，不是删除交易后的可执行反事实。

## 成对stationary bootstrap

策略和买持按相同日期索引成对重抽样，10000次，平均连续块长21日，seed=9380。净年化差点估计{boot.cagr.point_difference*100:.2f}个百分点，95%区间[{boot.cagr.lower_95*100:.2f}, {boot.cagr.upper_95*100:.2f}]个百分点；日末净值卡玛差点估计{boot.calmar.point_difference:.6f}，95%区间[{boot.calmar.lower_95:.6f}, {boot.calmar.upper_95:.6f}]。

该接口按日末收益计算回撤及卡玛。本次原账的日末与BAR_CLOSE最大回撤恰好一致，但重抽样区间仍属于日末收益统计，不是重新运行策略或完整逐柱账户路径的区间。两项区间均未经全研究搜索选择偏差校正；区间正负不自动改变已确认硬门，不代表未来获利概率。重抽样近似已见样本中的局部序列相关，不能消除结构变化或重复开发样本带来的不确定性。

本分项已完成；完整阶段四还需汇总已完成的参数/费用检查及研究族选择偏差诊断，由RSCH形成综合结论。
'''
    (OUT/'time_summary.md').write_text(report,encoding='utf-8',newline='\n')
    print(json.dumps({'status':'COMPLETED','windows':len(windows),'rolling_calmar_q10':rolling['excess_calmar_q10'],
        'negative_calmar_windows':rolling['calmar_underperformance']['negative_windows'],
        'concentration_max':largest,'concentration_top5':c['top5_positive_cycle_share'],
        'bootstrap':asdict(boot),'seconds':value['elapsed_seconds']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
