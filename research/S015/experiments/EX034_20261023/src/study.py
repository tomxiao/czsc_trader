"""One fixed price-path component experiment; independent events, not accounts."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'): os.environ[k]='1'
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite

ROOT=Path(__file__).resolve().parents[5]; HERE=Path(__file__).resolve().parents[1]; BASE=HERE.parent
EX=ExperimentRef('S015',HERE.name)
SEGMENTS=((0,100),(100,184),(184,268),(268,352),(352,434))
def read(p): return json.loads(p.read_bytes())
def save(p,v): p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def context(): return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(p): return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def module(p,name):
    spec=importlib.util.spec_from_file_location(name,p); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def old_module():
    refs=read(BASE/'EX026_20261023/others/protocol_refs.json')
    ref=EvidenceRef.from_dict(refs['study.py']);ref.resolve(ROOT)
    path=BASE/'EX026_20261023/src/study.py';assert sha256(path.read_bytes()).hexdigest()==ref.sha256
    return module(path,'ex026_events'),ref

def features(adj):
    """T=b+2; every b crossing the previous 20-session HIGH is one anchor."""
    c=adj.Close.astype(float);h=adj.High.astype(float);lo=adj.Low.astype(float)
    tr=pd.concat([h-lo,(h-c.shift()).abs(),(lo-c.shift()).abs()],axis=1).max(axis=1)
    boundary=h.shift().rolling(20).max();atr=tr.shift().rolling(20).mean()
    br=c>boundary;bound=boundary.shift(2);anchor=br.shift(2,fill_value=False)
    accepted=anchor & c.shift().gt(bound) & c.gt(bound)
    retest=accepted & pd.concat([lo.shift(),lo],axis=1).min(axis=1).le(bound+.25*atr.shift(2)) & c.gt(c.shift())
    x=pd.DataFrame({'date':pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d'),'anchor_date':pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d').shift(2),
      'anchor':anchor,'accepted':accepted,'rejected':anchor & ~accepted,'retest':retest,'boundary':bound,'atr_anchor':atr.shift(2),
      'close':c,'r5':c/c.shift(5)-1,'vol20':c.pct_change().rolling(20).std(ddof=1),
      'confirmation_change':c/c.shift(2)-1,'breakout_stretch':(c.shift(2)-bound)/atr.shift(2)})
    x=x.iloc[75:].reset_index(drop=True);x['position']=np.arange(len(x));x['period']=np.searchsorted([100,184,268,352],x.position,side='right')
    return x

def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    _,oldref=old_module()
    eventref=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/delivery_validation.json')['materials']['events.csv']);eventref.resolve(ROOT)
    protocol={
      'authorization':'用户同意新增1轮阶段二价格路径固定对照，先冻结定义再执行；无阶段三账户或搜索授权。',
      'budget':{'rounds':1,'parameter_searches':0,'continuous_accounts':0,'new_external_sources':0},
      'scope':'原S015 MANDATE/3、159326.SZ、75日预热及434日开发池至2026-10-21；415日门槛不变，本轮不验收账户。已反复观察的开发池，不是独立验证。',
      'mechanism':'突破既有价格边界后得到接受，可能有尚未完成的向上重新定价；跌回原区间为竞争解释。价格不能证明参与者身份或资金因果。',
      'features':'使用认证HFQ日OHLC保持分红前后边界一致。b收盘严格高于b之前20日High最大值U，b为突破；T=b+2统一观察完成。T-1和T两次收盘都>U为accepted，否则rejected，等于U视为跌回。每个b独立标记，不事后挑选、不因后续突破重置旧U；相邻锚点可能同一行情。',
      'retest':'accepted且min(Low[b+1],Low[b+2])<=U+0.25*ATR20[b之前]，且Close[T]>Close[T-1]；仅预声明次级子集。ATR为此前20日TR均值，TR=max(H-L,abs(H-prevC),abs(L-prevC))。',
      'labels':'复用EX026已认证独立10万元事件，T+1原1%限价买，双侧0.1%费、原tick/lot/HFQ/DAILY_RANGE_V3/卖出重试。主h3；h1/h5为固定期限诊断；入场日唯一h1有成交标记的entry_net，仅扣买费。未成交、右截尾单列。',
      'structure_exit':'仅accepted事件：T+1起每日收盘检查Close<U或等于U，首次失效当晚决定次日市场卖；最迟T+5决定T+6卖，最多5日。未到失效/最长观察则沿用h5右截尾。与同事件h5配对；不在买入日即时止损。新h2/h4仅用于补齐原公共TXE事件标签，不构建连续账户。',
      'contrasts':['accepted-rejected at h3 primary','accepted-rejected at h1/h5 and entry mark','retest-(accepted without retest) secondary, same four targets','accepted structure_exit-h5 paired secondary'],
      'matching':'每个accepted在同一个固定时间段的rejected中找最近对照；要求abs(r5差)<=0.05且vol20比在[0.5,2]，距离=(r5差/0.05)^2+(log(vol比)/log(2))^2；平局较早position；允许复用并报告独立对照数。只使用双方标签有效样本，按accepted等权；不匹配结果，不足不填补。另报告r5/vol20/确认涨幅/突破幅度平衡，不能主张因果。',
      'statistics':'全期及原5固定段；损益金额及笔数分别报告。过滤掉rejected的亏损识别/盈利遗漏以全部anchor为分母；另报只选accepted/retest相对全434日的机会代价。事件重叠，金额不能作为账户损益。主对比和结构配对在完整434日轴上作20日块499次bootstrap seed13；区间不作为经济硬门，不校正历史选择。',
      'frequency':'按各期限真实事件入/退出日，在每个滚动60日窗口的退出事件中，以最早退出贪心求互不重叠区间最大数量；允许同日卖后买作为乐观上界。非连续账户，不宣称真实频率达标。',
      'segments':SEGMENTS,'verification':'全部434日前缀特征核对；旧h1/h3/h5所选事件逐字段复算；独立审计状态、损益、结构退出、匹配、频率；源代码先发布后计算。',
      'limitations':'HFQ历史修订和17:30供应商历史可得性未认证；日区间撮合无容量。没有新资金输入或源查询；结构和阈值选择属于开发选择历史。',
      'prior_source':oldref.to_dict(),'prior_labels':eventref.to_dict()}
    save(HERE/'protocols/price_path.json',protocol)
    save(HERE/'others/protocol_refs.json',{p.name:material(p).to_dict() for p in (HERE/'protocols/price_path.json',Path(__file__))})
    print('PROTOCOL_SOURCE_FROZEN',flush=True)

def summary(g,label='net'):
    y=g[label].dropna().to_numpy(float);pos=np.maximum(y,0).sum();neg=-np.minimum(y,0).sum()
    return {'n':len(y),'mean_return':float(y.mean()/100000) if len(y) else None,'positive_n':int((y>0).sum()),'negative_n':int((y<0).sum()),
      'positive_yuan':float(pos),'negative_yuan':float(neg),'net_yuan':float(y.sum())}
def rate(a,b):return float(a/b) if b else None
def comparison(g,yes,no,label):
    a=summary(g[g[yes]],label);b=summary(g[g[no]],label)
    return {'in':a,'out':b,'delta':a['mean_return']-b['mean_return'] if a['n'] and b['n'] else None,
      'rejected_loss_fraction':rate(b['negative_yuan'],a['negative_yuan']+b['negative_yuan']),
      'missed_profit_fraction':rate(b['positive_yuan'],a['positive_yuan']+b['positive_yuan']),
      'rejected_loss_count_fraction':rate(b['negative_n'],a['negative_n']+b['negative_n']),
      'missed_profit_count_fraction':rate(b['positive_n'],a['positive_n']+b['positive_n'])}
def matching(g,label):
    valid=g[g[label].notna()];pairs=[]
    for a in valid[valid.accepted].itertuples():
        pool=valid[valid.rejected & valid.period.eq(a.period)].copy()
        pool=pool[(pool.r5-a.r5).abs().le(.05)&(pool.vol20/a.vol20).between(.5,2)]
        if pool.empty:continue
        pool['distance']=((pool.r5-a.r5)/.05)**2+(np.log(pool.vol20/a.vol20)/np.log(2))**2
        b=pool.sort_values(['distance','position']).iloc[0]
        p={'accepted_position':int(a.position),'rejected_position':int(b.position),'difference':float(getattr(a,label)-b[label])/100000,'distance':float(b.distance)}
        for c in ('r5','vol20','confirmation_change','breakout_stretch'):p[c+'_difference']=float(getattr(a,c)-b[c])
        pairs.append(p)
    return {'matched_accepted_n':len(pairs),'eligible_accepted_n':int(valid.accepted.sum()),'unique_rejected_n':len({p['rejected_position'] for p in pairs}),
      'delta':float(np.mean([p['difference'] for p in pairs])) if pairs else None,
      'balance':{c:float(np.mean([p[c+'_difference'] for p in pairs])) if pairs else None for c in ('r5','vol20','confirmation_change','breakout_stretch')},'pairs':pairs}
def bootstrap(g,label,yes,no):
    y=g[label].to_numpy(float)/100000;a=g[yes].to_numpy(bool);b=g[no].to_numpy(bool);rng=np.random.default_rng(13);v=[]
    assert len(y)==434
    for _ in range(499):
        ix=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,size=22)])[:434]
        aa=y[ix][a[ix]&np.isfinite(y[ix])];bb=y[ix][b[ix]&np.isfinite(y[ix])]
        if len(aa) and len(bb):v.append(float(aa.mean()-bb.mean()))
    return {'valid_draws':len(v),'ci95':np.quantile(v,[.025,.975]).tolist() if v else None}
def frequency(g,mask,dates):
    ids={d:i for i,d in enumerate(dates)};events=g[g[mask]&g.status.eq('CLOSED')]
    intervals=sorted([(ids[r.entry_date],ids[r.actual_exit_date]) for r in events.itertuples()],key=lambda a:(a[1],a[0]));counts=[]
    for end in range(59,434):
        last=-1;n=0
        for start,stop in intervals:
            if end-59<=stop<=end and start>=last:n+=1;last=stop
        counts.append(n)
    return {'max_nonoverlap_median':float(np.median(counts)),'windows_at_least3':sum(n>=3 for n in counts),'total_windows':375,'counts':counts,
      'not_ruled_out_by_bound':bool(np.median(counts)>=6 and sum(n>=3 for n in counts)>=338)}

def run():
    assert not (HERE/'others/results.json').exists()
    frozen=read(HERE/'others/protocol_refs.json')
    for name,sub in [('study.py','src'),('price_path.json','protocols')]:assert EvidenceRef.from_dict(frozen[name]).resolve(ROOT).read_bytes()==(HERE/sub/name).read_bytes()
    old,sr=old_module();refs=old.sources();adj,raw,bars,rules,identities=old.inputs(refs)
    for frame in (adj,raw,bars):frame.attrs={}
    x=features(adj);assert len(x)==434 and not x.isna().any().any()
    checks=0
    for i in range(434):
        a=features(adj.iloc[:76+i]).iloc[-1];b=x.iloc[i]
        pd.testing.assert_series_equal(a,b,check_names=False);checks+=1
    x.to_csv(HERE/'others/features.csv',index=False)
    adj.to_csv(HERE/'others/adjusted_prices.csv',index=False)
    proto=read(HERE/'protocols/price_path.json');er=EvidenceRef.from_dict(proto['prior_labels']);events=pd.read_csv(er.resolve(ROOT))
    allpos=x.loc[x.anchor,'position'].astype(int).tolist();reproduced=0
    for h in (1,3,5):
        rr=pd.DataFrame(old.events((adj,raw,rules,h,[p+75 for p in allpos])))
        orig=events[events.horizon.eq(h)&events.position.isin(allpos)].reset_index(drop=True)
        for c in rr.columns:
            if c in ('quantity','position','horizon') or pd.api.types.is_numeric_dtype(orig[c]):
                np.testing.assert_allclose(pd.to_numeric(rr[c]),pd.to_numeric(orig[c]),rtol=1e-11,atol=1e-8,equal_nan=True)
            else:assert rr[c].fillna('').astype(str).tolist()==orig[c].fillna('').astype(str).tolist(),c
        reproduced+=len(rr)
    new=[]
    for h in (2,4):new.extend(old.events((adj,raw,rules,h,[p+75 for p in allpos])))
    new=pd.DataFrame(new);new.to_csv(HERE/'others/additional_events.csv',index=False)
    structure=[]
    for f in x[x.accepted].itertuples():
        horizon=5;invalid_date=None
        for k in range(1,6):
            j=75+f.position+k
            if j<len(adj) and float(adj.Close.iloc[j])<=f.boundary:
                horizon=k;invalid_date=str(pd.Timestamp(adj.Date.iloc[j]).date());break
        pool=new if horizon in (2,4) else events
        r=pool[pool.position.eq(f.position)&pool.horizon.eq(horizon)].iloc[0].to_dict()
        r.update(invalidation_date=invalid_date,structural_horizon=horizon);structure.append(r)
    st=pd.DataFrame(structure);st.to_csv(HERE/'others/structure_events.csv',index=False)
    results={'signal_counts':{c:int(x[c].sum()) for c in ('anchor','accepted','rejected','retest')},'targets':{},'structure':{},'frequency':{}}
    merged=[]
    for label,h in [('net',1),('net',3),('net',5),('entry_net',1)]:
        key=f'{label}_h{h}';ee=events[events.horizon.eq(h)].copy()
        ee=ee.drop(columns=[c for c in x.columns if c in ee.columns and c not in ('date','position')])
        g=x.merge(ee,on=['date','position'],validate='one_to_one');g['accepted_no_retest']=g.accepted&~g.retest
        if label=='net':g.loc[~g.status.eq('CLOSED'),label]=np.nan
        z={'acceptance':comparison(g,'accepted','rejected',label),'retest':comparison(g,'retest','accepted_no_retest',label),
          'matched':matching(g,label),'acceptance_bootstrap':bootstrap(g,label,'accepted','rejected'),
          'retest_bootstrap':bootstrap(g,label,'retest','accepted_no_retest'),'all_days':summary(g,label),'periods':{},'selection':{}}
        for a,b in SEGMENTS:z['periods'][f'{a}:{b}']=comparison(g[g.position.ge(a)&g.position.lt(b)],'accepted','rejected',label)
        total=summary(g,label)
        for mask in ('accepted','retest'):
            rejected=summary(g[~g[mask]],label);selected=summary(g[g[mask]],label)
            z['selection'][mask]={'selected':selected,'not_selected':rejected,'caught_loss_fraction':rate(rejected['negative_yuan'],total['negative_yuan']),
              'missed_profit_fraction':rate(rejected['positive_yuan'],total['positive_yuan']),'status':g[g[mask]].status.value_counts().to_dict()}
        results['targets'][key]=z
        if label=='net':
            results['frequency'][f'h{h}']={m:frequency(g,m,x.date.tolist()) for m in ('anchor','accepted','retest')}
            g['label_key']=key;merged.append(g)
    five=events[events.horizon.eq(5)][['position','net','status']].rename(columns={'net':'fixed_net','status':'fixed_status'})
    pair=st.merge(five,on='position',validate='one_to_one')
    pair['valid_pair']=pair.status.eq('CLOSED')&pair.fixed_status.eq('CLOSED')
    pair['delta_yuan']=(pair.net-pair.fixed_net).where(pair.valid_pair);pair.to_csv(HERE/'others/exit_pairs.csv',index=False)
    p=pair[pair.valid_pair];results['structure']={'n':len(p),'structure':summary(p),'fixed5':summary(p.rename(columns={'net':'structure_net','fixed_net':'net'})),
      'mean_delta':float(p.delta_yuan.mean()/100000) if len(p) else None,'improved_n':int((p.delta_yuan>0).sum()),'worsened_n':int((p.delta_yuan<0).sum()),
      'early_exit_n':int((p.structural_horizon<5).sum()),'status':st.status.value_counts().to_dict()}
    aligned=x[['position']].merge(pair[['position','delta_yuan']],on='position',how='left');y=aligned.delta_yuan.to_numpy(float)/100000;bs=[];rng=np.random.default_rng(13)
    for _ in range(499):
        ix=np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,size=22)])[:434];v=y[ix];v=v[np.isfinite(v)]
        if len(v):bs.append(float(v.mean()))
    results['structure']['bootstrap']={'valid_draws':len(bs),'ci95':np.quantile(bs,[.025,.975]).tolist() if bs else None}
    sg=st.merge(x[['position','accepted','retest']],on='position',validate='one_to_one')
    results['frequency']['structure']={m:frequency(sg,m,x.date.tolist()) for m in ('accepted','retest')}
    pd.concat(merged,ignore_index=True).to_csv(HERE/'others/labeled_events.csv',index=False)
    save(HERE/'others/input_refs.json',{'prior_source':sr.to_dict(),'prior_labels':er.to_dict(),'source_inputs':{k:v.to_dict() for k,v in refs.items()},'data_identities':identities})
    save(HERE/'others/checks.json',{'status':'PASS','prefix_checks':checks,'old_events_reproduced':reproduced,'new_h2_h4_events':len(new),'continuous_accounts':0})
    save(HERE/'others/results.json',results)
    print(json.dumps({'counts':results['signal_counts'],'primary':results['targets']['net_h3']['acceptance'],'structure':results['structure']},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);{'prepare':prepare,'run':run}[p.parse_args().mode]()
