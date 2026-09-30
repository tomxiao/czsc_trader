"""Package the two freshly executed public SRT/TXE replays and comparison view."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import argparse
import json
import shutil
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
SOURCE=Path(__file__).resolve().parent
LEDGERS=('decisions','orders','fills','account_daily','trades')
INITIAL=1_000_000.
CASES={'S011-CFG-000618':'EX24T003','S011-CFG-000621':'EX24T007'}

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def dump(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')

def summarize(a,t,f=None):
    equity=a.equity.to_numpy(float);closed=t[t.status.eq('CLOSED')]
    peak=np.maximum.accumulate(np.r_[INITIAL,equity])[1:];drawdown=equity/peak-1
    assert len(a)==403 and a.date.iloc[0]=='2025-02-06' and a.date.iloc[-1]=='2026-09-28'
    np.testing.assert_allclose(a.cash+a.quantity*a.close,a.equity,atol=1e-7,rtol=0)
    result={'total_return':float(equity[-1]/INITIAL-1),'cagr':float((equity[-1]/INITIAL)**(252/len(a))-1),
        'max_drawdown_magnitude':float(-drawdown.min()),'max_drawdown_trough_date':str(a.date.iloc[drawdown.argmin()]),
        'ending_equity':float(equity[-1]),'net_profit':float(equity[-1]-INITIAL),'sessions':len(a),
        'closed_trades':len(closed),'trades_per_60_sessions':60*len(closed)/len(a),
        'closed_trade_win_rate':float(closed.net_return.gt(0).mean()) if len(closed) else None,
        'end_of_day_invested_session_share':float(a.quantity.gt(0).mean()),
        'ending_quantity':int(a.quantity.iloc[-1]),'open_trades':int(t.status.ne('CLOSED').sum()),
        'fees':None if f is None else float(f.fees.sum())}
    return result,drawdown

def main(replays,output):
    if output.exists() or not output.is_relative_to(ROOT/'.tmp'):raise ValueError('fresh .tmp output required')
    output.mkdir(parents=True)
    (output/'src').mkdir();shutil.copyfile(Path(__file__),output/'src/build_report.py')
    registry=read(ROOT/'research/S011/stage4/iteration_04/configurations.json')
    configs={c['config_id']:c for c in registry['configurations'] if c['config_id'] in CASES}
    source_hashes={};summary=[];curves=[];periods=[];verification=[]
    def record(p):source_hashes[p.relative_to(ROOT).as_posix()]=digest(p);return p
    record(ROOT/'research/S011/stage4/iteration_04/manifest.json')
    record(ROOT/'research/S011/stage4/iteration_03/src/replay.py')
    for name in ('execution_daily.csv.gz','execution_intraday.csv.gz'):
        record(ROOT/'experiments/S011/20260930_S011_EX15/artifacts'/name)
    for cid,ref in CASES.items():
        short='CFG'+cid.rsplit('-',1)[1];folder=replays/short;target=output/short;target.mkdir()
        proof=read(folder/'verification.json');assert proof['status']=='PASS' and proof['config_id']==cid and proof['all_five_ledgers_equal']
        frames={name:pd.read_parquet(folder/(name+'.parquet')) for name in LEDGERS}
        source=ROOT/f'experiments/S011/20260930_S011_EX24/artifacts/trials/T{ref[-3:]}'
        for name,frame in frames.items():
            old=pd.read_csv(record(source/(name+'.csv.gz')))
            pd.testing.assert_frame_equal(frame,old,check_exact=False,rtol=1e-12,atol=1e-8)
            shutil.copyfile(folder/(name+'.parquet'),target/(name+'.parquet'))
        for name in ('trades','account_daily'):
            frames[name].to_csv(target/(name+'.csv'),index=False,encoding='utf-8-sig')
        # Archive exact managed inputs as evidence, never transplant them into a runtime cache.
        managed=ROOT/f'.tmp/s011-ex24-execution/S011{ref}_159326_260930'
        preparation=managed/'preparations/20250206_20260928'
        snapshot=target/'input_snapshot';snapshot.mkdir()
        for p in [managed/'strategy-space.json',*sorted(preparation.iterdir())]:
            if p.is_file():shutil.copyfile(p,snapshot/p.name)
        identity=read(snapshot/'strategy-space.json');assert identity['reference_id']=='S011-'+ref
        for file in configs[cid]['definition']['runtime']['source_files']:record(ROOT/configs[cid]['source_root']/file)
        a,t,f=frames['account_daily'],frames['trades'],frames['fills']
        values,dd=summarize(a,t,f);values['config_id']=cid;values['source_candidate_id']=ref
        orders=frames['orders'];values['orders']=len(orders);values['fills']=len(f)
        values['order_status_counts']={str(k):int(v) for k,v in orders.status.value_counts().items()}
        summary.append(values);verification.append(proof)
        daily=pd.DataFrame({'config_id':cid,'date':a.date,'equity':a.equity,'nav':a.equity/INITIAL,'drawdown':dd})
        curves.append(daily)
        for year,g in a.assign(year=pd.to_datetime(a.date).dt.year).groupby('year'):
            first=int(g.index[0]);base=INITIAL if first==0 else float(a.equity.iloc[first-1])
            periods.append({'config_id':cid,'year':int(year),'start':g.date.iloc[0],'end':g.date.iloc[-1],
                'sessions':len(g),'period_return':float(g.equity.iloc[-1]/base-1),'partial_calendar_year':True})
        dump(target/'metrics.json',values);dump(target/'configuration.json',configs[cid]);dump(target/'verification.json',proof)
    benchmark_root=ROOT/'experiments/S011/20260930_S011_EX16/artifacts'
    ba=pd.read_csv(record(benchmark_root/'benchmark_account_daily.csv.gz'));bt=pd.read_csv(record(benchmark_root/'benchmark_trades.csv.gz'))
    bm,bd=summarize(ba,bt);bm['evidence_role']='INHERITED_SAME_CONTRACT_BENCHMARK_NOT_RERUN'
    dump(output/'benchmark.json',bm)
    curves.append(pd.DataFrame({'config_id':'BUY_HOLD','date':ba.date,'equity':ba.equity,'nav':ba.equity/INITIAL,'drawdown':bd}))
    curve=pd.concat(curves,ignore_index=True);curve.to_parquet(output/'equity_comparison.parquet',index=False)
    pd.DataFrame(periods).to_parquet(output/'period_returns.parquet',index=False)
    dump(output/'summary.json',{'status':'COMPLETE','window':['2025-02-06','2026-09-28'],'initial_cash':INITIAL,
        'one_way_cost':.001,'strategy_backtests_executed':2,'records':summary,'benchmark':bm,
        'interpretation':'Same-input development-pool replay, not independent or forward validation. No parameter search or promotion.'})
    dump(output/'verification.json',{'status':'PASS','cases':verification,'ledger_comparison_rtol':1e-12,'ledger_comparison_atol':1e-8,
        'account_cash_inventory_reconciliation':True,'all_five_ledgers_equal_for_both':True})
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for cid,label,color in [('S011-CFG-000618','CFG 000618','#2563eb'),('S011-CFG-000621','CFG 000621','#a855f7'),('BUY_HOLD','Buy & hold (archived)','#8a919c')]:
        c=curve[curve.config_id.eq(cid)];dates=pd.to_datetime(c.date)
        axes[0].plot(dates,c.nav,label=label,color=color,linewidth=1.6)
        axes[1].plot(dates,c.drawdown*100,color=color,linewidth=1.3)
    axes[0].set_ylabel('Net asset value (initial = 1)');axes[1].set_ylabel('Drawdown (%)')
    axes[0].set_title('S011 | 159326.SZ | Development-pool replay | 2025-02-06 to 2026-09-28')
    axes[0].legend(loc='upper left');axes[1].set_xlabel('Date')
    for ax in axes:ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(output/'equity_drawdown.png',dpi=160);plt.close(fig)
    a,b=summary
    lines=['# 618与621开发池完整账户回测','',
        '本次通过公共SRT/TXE分别重新计算两个固定配置。窗口2025-02-06至2026-09-28，共403个交易日；初始现金100万元、初始空仓，单边成本10bp，买入LIMIT、卖出MARKET。各自复用同身份受管输入，结果另存。','',
        '| 指标 | 000618 | 000621 | 同口径买入持有 |','| --- | ---: | ---: | ---: |']
    for key,title in [('total_return','累计收益'),('cagr','年化收益'),('max_drawdown_magnitude','最大回撤')]:
        lines.append(f'| {title} | {a[key]:.2%} | {b[key]:.2%} | {bm[key]:.2%} |')
    lines.extend([f"| 期末权益（元） | {a['ending_equity']:,.2f} | {b['ending_equity']:,.2f} | {bm['ending_equity']:,.2f} |",
        f"| 闭合交易笔数 | {a['closed_trades']} | {b['closed_trades']} | — |",
        f"| 每60交易日频率 | {a['trades_per_60_sessions']:.3f} | {b['trades_per_60_sessions']:.3f} | — |",
        f"| 闭合交易胜率 | {a['closed_trade_win_rate']:.2%} | {b['closed_trade_win_rate']:.2%} | — |",
        f"| 累计费用（元） | {a['fees']:,.2f} | {b['fees']:,.2f} | — |",'',
        '买入持有引用既有同窗口、同资金及同成本账户，本轮只重跑两个指定配置。','',
        '![净值与回撤](equity_drawdown.png)','',
        '两个配置的决策、订单、成交、资金和交易五张账本分别与EX24 T003/T007一致，数值容差见verification.json；账户现金与持仓估值对账通过。期末均为空仓。','',
        '- [618逐笔交易](CFG000618/trades.csv) · [618每日账户](CFG000618/account_daily.csv) · [618指标](CFG000618/metrics.json)',
        '- [621逐笔交易](CFG000621/trades.csv) · [621每日账户](CFG000621/account_daily.csv) · [621指标](CFG000621/metrics.json)',
        '- [结构化汇总](summary.json) · [核验](verification.json) · [输入与文件清单](manifest.json)','',
        '可重执行入口为research/S011/stage4/iteration_03/src/replay.py；分别传入--config-id、该身份的--data-dir和新的.tmp目录--output。原EX24 T003/T007受管目录是显式运行依赖；input_snapshot只作归档证据，禁止移植成其他身份的缓存。若本机受管目录被清理，需通过公共数据准备入口重新准备并核验身份。','',
        '这是已见开发池的同输入复算，验证可复现性；不增加独立样本，也不改变参数扰动与搜索偏差结论。当前仍待用户决定是否晋升。'])
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    files={p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()}
    dump(output/'manifest.json',{'schema_version':1,'status':'COMPLETE','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'files':files,'source_hashes':source_hashes,'new_backtests':2,'new_configurations':0,'promotion':False,
        'replay_entry':'research/S011/stage4/iteration_03/src/replay.py','report_entry':'src/build_report.py',
        'data_policy':'Exact original same-candidate managed preparations; copied input snapshots are archival evidence only.'})
    print(json.dumps({'status':'PASS','records':summary,'files':len(files)},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--replays',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();main(args.replays.resolve(),args.output.resolve())
