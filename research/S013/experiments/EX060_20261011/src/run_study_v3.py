"""Authorized S013 phase-two study through public TDR/DFLS; no accounts."""
# ruff: noqa: E402
from datetime import date
from dataclasses import fields
from hashlib import sha256
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'research/S013/experiments/EX058_20261011/src'))
import common
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from component_definitions import intraday_downside_energy, overnight_downside_risk, short_horizon_labels
from component_statistics import analyze


def plain(value):
    return json.loads(json.dumps(value, default=dict, ensure_ascii=False, allow_nan=False))


def put(ctx, exp, name, path, media='application/json', suffix='json'):
    ref = publish_evidence(ctx, MaterialEvidenceWrite(exp, name, path.read_bytes(), media, suffix))
    assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256
    return ref.to_dict()


def declare():
    assert not (WORK / 'experiment.json').exists()
    ctx = common.context(1)
    exp = create_experiment(ctx, ExperimentRequest('扰动绝对绩效优先：短期风险组件重新发现',
        '30分钟下行路径与隔夜下跌能否提供超出原方向、波动及买入确认的风险信息？', date(2026, 10, 11)))
    plan = {
        'experiment': exp.to_dict(), 'role': 'RSCH', 'phase': 2,
        'authorization': ['我更看重扰动后的绝对收益和回撤，达标且稳健的策略才是我追求的结果。如果你判断当前策略表达不足以达成要求，可以重新做设计和验证，甚至可以回到阶段二重新挖掘组件。',
                          '先改善收益Q10和回撤Q90，并报告32点逐项达标率；暂不新增硬门'],
        'economic_targets': '原四项目标不变；Q10收益越高、Q90全区间回撤越低优先；中心相对退化仅诊断，不要求同步改善',
        'original_account_period': ['2020-01-02', '2026-09-30', 1636],
        'component_signal_grid': ['2020-01-02', '2026-09-29', 1635],
        'grid_reason': '沿用C8880原生决策日期并排除开发池前2019-12-31；最后2026-09-30仅用于价格标签，不新增未计算确认分的信号；不是缩短账户验收区间',
        'data': '仅S013已经固定的daily/30m/calendar公开DFLS资产；截止2026-09-30；禁止外部provider',
        'warmup': 'daily原180+确认120历史；30m资产始于2020-01-02，无更早30m；首19日组件保持缺失，不补造',
        'pricing': '原HFQ_RESEARCH/2019-12-31 anchor；公开ExecutionPricing重新转换并与原生执行数据核对；不另加现金分红',
        'controls': {'momentum20': 'Close/Close.shift(20)-1', 'range_position60':'(Close-minLow60)/(maxHigh60-minLow60)',
                     'acf1':'原S013 Close simple pct_change rolling20 mean-centered unbiased lag1 divided by population variance',
                     'volatility20':'Close simple pct_change rolling20 sample standard deviation ddof1',
                     'intraday_return':'Close/Open-1', 'overnight_gap':'log(Open/Close.shift(1))',
                     'intraday_energy20':'sqrt(rolling20 mean(sum of squared within-day 30m log returns))',
                     'intraday_rms20':'sqrt(rolling20 mean(log(Close/Open)^2))',
                     'confirmation_score':'EX058 N0/C8880 authenticated unchanged original decision field'},
        'opportunity':'原C8880事前entry_eligible；仅辅助组内诊断，受旧持仓状态路径影响，不按盈利样本筛选',
        'availability': 'T日全部8根30m完结/日线T17政策；T+1执行。历史发布及修订的真实时间未独立验证',
        'known_quality': '旧5个30m High/Low偏差原样保留；新组件只用Open/Close，标签用原daily Low；核对每日首Open/末Close一致',
        'scope': '固定2组件、5标签、9controls、4模型；不优化窗长/权重，不启动新机制账户。组件判断充分后才决定策略表达。',
        'stop': '若新增信息不稳定/只是已知波动或方向重复，则关闭这两条路线，避免用门槛扫参挽救弱证据',
        'limitations': '已见开发池；逐年训练预测是开发池时间顺序检验，非独立封存验证；价格标签不是费用后限价成交账户收益',
        'source_hashes': {n: sha256((WORK/n).read_bytes()).hexdigest() for n in
            ('component_definitions.py','component_statistics.py','component_checks.py','component_statistics_focused.py','run_study.py')},
    }
    common.write(WORK / 'plan.json', plan)
    refs = {}
    for name in ('plan.json','absolute_audit.json','component_method.json','component_statistics_method.json',
                 'component_review.json','component_checks.json','component_statistics_focused.json'):
        refs[name] = put(ctx, exp, name.replace('_','-').removesuffix('.json'), WORK/name)
    for name in ('component_definitions.py','component_statistics.py','component_checks.py','component_statistics_focused.py','run_study.py'):
        refs[name] = put(ctx,exp,name.removesuffix('.py').replace('_','-'),WORK/name,'text/x-python','py')
    path = exp.resolve(ROOT)
    for name in ('component_definitions.py','component_statistics.py','component_checks.py','component_statistics_focused.py','run_study.py'):
        (path/'src'/name).write_bytes((WORK/name).read_bytes())
    common.write(path/'protocols/plan.json',plan)
    common.write(path/'protocols/method_references.json',refs)
    common.write(WORK/'experiment.json', exp.to_dict())
    print({'prospective_method_published': exp.experiment_id, 'references':len(refs)},flush=True)


def study():
    exp = ExperimentRef.from_dict(common.read(WORK/'experiment.json'))
    plan = common.read(WORK/'plan.json')
    for name, digest in plan['source_hashes'].items():
        assert sha256((WORK/name).read_bytes()).hexdigest() == digest, name
    assert not (WORK/'statistics.json').exists()
    ctx = common.context(1)
    bound, result = common.cache_read(common.CACHE/'N0.pkl.gz')
    ref = EvidenceRef.from_dict(common.read(common.RUNS/'account_references.json')['N0'])
    assert serialize_evaluation_evidence(bound,result) == common.read(ref.resolve(ROOT))
    assert bound.strategy.candidate_id == 'C8880'
    identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
    assert identity.content_sha256 == result.runs[0].identity.content_sha256
    ed = bound.execution_data
    fetched = {}
    metadata = {}
    for key, request in ed.requests.items():
        got = ctx.data.fetch(request, prepared=ed.prepared)
        assert got.ready, key
        fetched[key] = got.dataframe.copy()
        metadata[key] = {'request': str(request), 'identity': plain({f.name:getattr(got.identity,f.name) for f in fields(got.identity)})}
        print({'fetched':key,'shape':got.dataframe.shape,'columns':got.dataframe.columns.tolist()},flush=True)
    binding = bound.input_bindings['full']
    got = ctx.data.fetch(binding.plan.requests['daily'],prepared=binding.prepared)
    assert got.ready
    daily_input = got.dataframe.copy()
    metadata['srt_daily_input'] = {'request':str(binding.plan.requests['daily']), 'identity':plain({f.name:getattr(got.identity,f.name) for f in fields(got.identity)})}
    common.cache_write(WORK/'admitted.pkl.gz', (bound,result,fetched,daily_input,metadata))
    print({'admitted_and_authenticated':True,'daily_columns':daily_input.columns.tolist()},flush=True)
    compute(exp,ctx,bound,result,fetched,daily_input,metadata)


def numerical(df, symbol=False):
    rename = {'Date':'dt','Open':'open','High':'high','Low':'low','Close':'close','Volume':'vol','Amount':'amount','Symbol':'symbol'}
    result = df.rename(columns=rename).copy()
    if symbol:
        assert 'symbol' not in result
        result['symbol'] = '510500.SH'  # Explicit admitted DataRequest identity, not a guessed dataframe field.
    columns = ['dt',*(['symbol'] if symbol else []),'open','high','low','close','vol','amount']
    result = result.loc[:,columns].copy()
    result.dt = pd.to_datetime(result.dt)
    result.attrs = {}
    return result


def compute(exp,ctx,bound,result,fetched,daily_input,metadata):
    ed = bound.execution_data
    adjusted = numerical(fetched['adjusted_daily'],symbol=True)
    raw = numerical(fetched['execution_daily'])
    intraday_raw = numerical(fetched['execution_30m'])
    daily = ed.pricing.apply(raw,raw_daily=raw,adjusted_daily=adjusted)
    intraday = ed.pricing.apply(intraday_raw,raw_daily=raw,adjusted_daily=adjusted)
    for actual, expected in ((adjusted,ed.adjusted_daily),(raw,ed.raw_execution_daily),(daily,ed.execution_daily),(intraday,ed.execution_intraday)):
        a,b = actual.reset_index(drop=True).copy(),expected.reset_index(drop=True).copy()
        a.attrs,b.attrs = {},{}
        pd.testing.assert_frame_equal(a,b,check_exact=True)
    calendar = fetched['trading_calendar']
    print({'calendar_columns':calendar.columns.tolist()},flush=True)
    sessions = pd.DatetimeIndex(pd.to_datetime(ed.evaluation_sessions)).normalize()
    assert len(sessions)==1636 and sessions[0]==pd.Timestamp('2020-01-02') and sessions[-1]==pd.Timestamp('2026-09-30')
    assert calendar.IsOpen.isin([0,1]).all()
    open_sessions = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1),'Date'])).normalize()
    pd.testing.assert_index_equal(open_sessions,sessions,check_names=False)
    for frame in (fetched['adjusted_daily'],daily_input):
        available = pd.to_datetime(frame.AvailableDate)
        assert available.dt.normalize().equals(pd.to_datetime(frame.Date).dt.normalize())
        assert available.dt.hour.eq(17).all()
    available = pd.to_datetime(fetched['execution_30m'].AvailableDate)
    assert available.ge(pd.to_datetime(fetched['execution_30m'].Date)).all()
    counts = intraday.groupby(intraday.dt.dt.normalize()).size()
    pd.testing.assert_index_equal(counts.index,sessions,check_names=False)
    assert counts.eq(8).all()
    expected_times = ['10:00','10:30','11:00','11:30','13:30','14:00','14:30','15:00']
    assert all(list(group.dt.dt.strftime('%H:%M'))==expected_times for _,group in intraday.groupby(intraday.dt.dt.normalize()))
    dayindexed = daily.set_index('dt')
    first = intraday.groupby(intraday.dt.dt.normalize()).first()
    last = intraday.groupby(intraday.dt.dt.normalize()).last()
    np.testing.assert_allclose(first.open,dayindexed.loc[sessions,'open'],rtol=1e-12,atol=1e-12)
    np.testing.assert_allclose(last.close,dayindexed.loc[sessions,'close'],rtol=1e-12,atol=1e-12)
    decisions = result.runs[0].execution.decisions.copy()
    decisions.index = pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).normalize()
    grid = decisions.index[decisions.index>=pd.Timestamp('2020-01-02')]
    assert len(grid)==1635 and grid[-1]==pd.Timestamp('2026-09-29')
    pd.testing.assert_index_equal(grid,sessions[:-1],check_names=False)
    assert decisions.loc[grid,'confirmation_score'].notna().all()
    lower = {'dt':'Date','open':'Open','high':'High','low':'Low','close':'Close','vol':'Volume','amount':'Amount'}
    daily_pure = daily.rename(columns=lower)
    intra_pure = intraday.rename(columns=lower)
    intra = intraday_downside_energy(intra_pure)
    overnight = overnight_downside_risk(daily_pure)
    controls = daily_input.copy()
    controls.index = pd.DatetimeIndex(pd.to_datetime(controls.Date)).normalize()
    c = controls.Close.astype(float)
    change = c.pct_change(fill_method=None)
    feature = pd.DataFrame(index=controls.index)
    feature['momentum20'] = c/c.shift(20)-1
    feature['range_position60'] = (c-controls.Low.rolling(60).min())/(controls.High.rolling(60).max()-controls.Low.rolling(60).min())
    def acf(x):
        centered = x-x.mean()
        variance = np.mean(centered**2)
        return np.nan if np.isclose(variance,0) else float(np.dot(centered[1:],centered[:-1])/19/variance)
    feature['acf1'] = change.rolling(20).apply(acf,raw=True)
    feature['volatility20'] = change.rolling(20).std(ddof=1)
    feature['intraday_return'] = c/controls.Open-1
    feature = feature.reindex(grid)
    for name in ('momentum20','acf1'):
        np.testing.assert_allclose(feature[name],decisions.loc[grid,name],rtol=0,atol=0,equal_nan=True)
    feature['confirmation_score'] = decisions.loc[grid,'confirmation_score']
    feature = feature.join(intra[['feature_intraday_down_energy20','intraday_energy20']]).join(overnight[['feature_overnight_down_energy20','intraday_rms20','overnight_gap']])
    labels = short_horizon_labels(daily_pure).reindex(grid)
    out = pd.DataFrame(index=grid)
    for h in (3,5):
        out[f'return_{h}'] = labels[f'return_h{h}']
        out[f'downside_{h}'] = labels[f'risk_h{h}']
        for name in (f'return_{h}',f'downside_{h}'):
            out[f'label_end_{name}'] = labels[f'label_exit_h{h}']
    next_open = dayindexed.open.shift(-1)
    next_date = pd.Series(dayindexed.index,index=dayindexed.index).shift(-1)
    out['negative_gap_next'] = (next_open < dayindexed.close).astype(float).reindex(grid)
    out['label_end_negative_gap_next'] = next_date.reindex(grid)
    assert out.label_end_negative_gap_next.notna().all()
    opportunity = decisions.loc[grid,'entry_eligible'].astype(bool)
    assert not common.SOURCE_CALLS
    metadata.update(original_account=ref_dict(),original_account_cache='EXACT_EQUAL',runtime_content_sha256=result.runs[0].identity.content_sha256,
                    pricing=ed.pricing.to_dict(),source_calls=common.SOURCE_CALLS,
                    input_checks={'sessions':len(sessions),'signal_n':len(grid),'30m_rows':len(intraday),'8_per_session':True,'first_open_last_close':True,'reconverted_native_exact':True,
                                  'daily_available_date_policy': '17:00, historical actual timestamps unverified', 'feature_missing': feature.isna().sum().to_dict(), 'opportunity_n':int(opportunity.sum())})
    common.write(WORK/'input_checks.json',plain(metadata))
    feature.to_csv(WORK/'features.csv',float_format='%.17g',index_label='signal_date')
    out.to_csv(WORK/'labels.csv',float_format='%.17g',index_label='signal_date')
    opportunity.to_csv(WORK/'opportunity.csv',index_label='signal_date')
    refs = common.read(exp.resolve(ROOT)/'protocols/method_references.json')
    for name in ('input_checks.json','features.csv','labels.csv','opportunity.csv'):
        refs[name]=put(ctx,exp,name.replace('_','-').split('.')[0],WORK/name,'text/csv' if name.endswith('csv') else 'application/json','csv' if name.endswith('csv') else 'json')
    common.write(exp.resolve(ROOT)/'protocols/input_references.json',refs)
    print({'component_inputs_published':True,'features':feature.shape,'label_counts':out[['return_3','return_5','downside_3','downside_5','negative_gap_next']].notna().sum().to_dict()},flush=True)
    stats = analyze(feature,out,opportunity)
    common.write(WORK/'statistics.json',stats)
    refs['statistics.json']=put(ctx,exp,'fixed-component-statistics',WORK/'statistics.json')
    common.write(exp.resolve(ROOT)/'protocols/result_references.json',refs)
    print({'component_statistics':'COMPLETE','experiment':exp.experiment_id,'signal_n':stats['signal_n']},flush=True)


def ref_dict():
    return common.read(common.RUNS/'account_references.json')['N0']


if __name__=='__main__':
    {'declare':declare,'study':study}[sys.argv[1]]()
