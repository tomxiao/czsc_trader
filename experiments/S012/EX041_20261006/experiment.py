"""Native availability and matched-calendar opportunity attribution, not accounts."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import json
import numpy as np
import pandas as pd
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentDependency, ExperimentPrecheckResult,
    ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentCapability,
)

EID = 'EX041_20261006'
INPUTS = {
    'daily': ('EX038_20261006','daily.parquet'),
    'features': ('EX038_20261006','features.parquet'),
    'old': ('EX038_20261006','signals.parquet'),
    'old_valid': ('EX038_20261006','valids.parquet'),
    'native': ('EX036_20261006','signals.parquet'),
    'native_valid': ('EX036_20261006','valids.parquet'),
}
PAIRS = (
    ('M05_SCOPE','m05_common','m05','m05_common'),
    ('MOM_SCOPE','momentum_common','momentum','momentum_common'),
    ('O01_M05','o01','union','o01_m05_common'),
    ('MOM_ADD','momentum','momentum_union','all_common'),
    ('Q07','o01','o01_q07','o01'),
    ('N09_GATE','momentum','n09','momentum_common'),
)

def build(d,f,old,ov,native,nv):
    if any(not x.index.equals(d.index) for x in (f,old,ov,native,nv)):
        raise ValueError('source calendars differ')
    s=pd.DataFrame(index=d.index);v=pd.DataFrame(index=d.index)
    for key,sc,vc,ss,vv in (
        ('o01','L01','L01',old,ov),('o01_q07','L03','L03',old,ov),
        ('n09','L02','L02',old,ov),('m05_common','C_M05','C_M05',old,ov),
        ('m05','R01','R01',native,nv),
        ('momentum_common','C_MOMPOS','C_MOMPOS',old,ov),
    ):
        v[key]=vv[vc].astype(bool);s[key]=ss[sc].astype(bool)&v[key]
    v['momentum']=f.etf3.notna()
    s['momentum']=(f.etf3>0)&v.momentum
    s['union']=s.o01|s.m05
    # A true branch is known despite another branch being unknown. False requires both known.
    v['union']=(v.o01&v.m05)|s.union
    s['momentum_union']=s.momentum|s.union
    v['momentum_union']=(v.momentum&v['union'])|s.momentum_union
    v['o01_m05_common']=v.o01&v.m05
    v['all_common']=v.o01&v.m05&v.momentum
    return s,v

def labels(d,h,delay,fee):
    entry=d.Open.shift(-1-delay);exit_=d.Open.shift(-1-delay-h)
    limit=np.floor((d.Close+1e-10)/.001)*.001
    buy=entry.where(entry<=limit,limit.where(d.Low.shift(-1-delay)<=limit))
    return pd.DataFrame({'net':exit_/entry*(1-fee)/(1+fee)-1,
                         'limit_net':exit_/buy*(1-fee)/(1+fee)-1},index=d.index)

def mean(x):
    a=np.asarray(x,dtype=float);a=a[np.isfinite(a)]
    return float(a.mean()) if len(a) else None

def schedule(mask,gap):
    out=[];next_=0
    for pos in np.flatnonzero(mask):
        if pos>=next_:out.append(pos);next_=pos+gap
    return np.array(out,dtype=int)

def analyze(d,s,v):
    rows=[];annual=[];pairs=[];cal=np.arange(len(d));label_frames=[]
    for h in (1,3,5,10):
      for delay in (0,1,2):
       for fee in (.001,.002):
        p=labels(d,h,delay,fee);label_frames.append(p.add_prefix(f'h{h}_d{delay}_f{fee}__'))
        mature=p.net.notna().to_numpy();y=p.net.to_numpy();ly=p.limit_net.to_numpy()
        for key in s:
            valid=v[key].to_numpy()&mature;hit=valid&s[key].to_numpy()
            ids=schedule(hit,h+1);fill=ids[np.isfinite(ly[ids])]
            item={'signal':key,'horizon':h,'delay':delay,'fee':fee,
                  'eligible_days':int(valid.sum()),'events':int(hit.sum()),
                  'net_mean':mean(y[hit]),'same_window_mean':mean(y[valid]),
                  'potential_events':len(ids),'potential_fills':len(fill),
                  'potential_limit_net':mean(ly[fill]),'potential_per60':len(fill)*60/1535}
            rows.append(item)
            for year in range(2020,2027):
                hm=hit&(d.index.year==year);fm=fill[d.index[fill].year==year]
                annual.append({**{k:item[k] for k in ('signal','horizon','delay','fee')},
                    'year':year,'events':int(hm.sum()),'net_mean':mean(y[hm]),
                    'potential_fills':len(fm),'potential_limit_net':mean(ly[fm])})
        for name,before,after,common in PAIRS:
            # Both sides share the same calendar, labels, costs and all phases. No best phase selection.
            valid=v[common].to_numpy()&v[before].to_numpy()&v[after].to_numpy()&mature
            for phase in range(h+1):
                ids=np.flatnonzero(valid&(cal%(h+1)==phase));ret=np.nan_to_num(ly[ids],nan=0)
                a=np.where(s[before].to_numpy()[ids],ret,0)
                b=np.where(s[after].to_numpy()[ids],ret,0)
                for omit in (None,*range(2020,2027)):
                    keep=np.ones(len(ids),bool) if omit is None else d.index[ids].year!=omit
                    pairs.append({'comparison':name,'horizon':h,'delay':delay,'fee':fee,
                        'phase':phase,'omitted_year':omit,'slots':int(keep.sum()),
                        'before_limit':mean(a[keep]),'after_limit':mean(b[keep]),
                        'marginal_limit':mean((b-a)[keep]),
                        'before_fills':int((s[before].to_numpy()[ids]&np.isfinite(ly[ids])&keep).sum()),
                        'after_fills':int((s[after].to_numpy()[ids]&np.isfinite(ly[ids])&keep).sum())})
    return rows,annual,pairs,pd.concat(label_frames,axis=1)

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2,EID,'S012',ExperimentMode.FORMAL,
            '原生M05与全域纯动量的收益是否只是共同有效域变化，推荐O01/M05有何同窗口增量？',
            '把有效域和信号门分开归因；原生信号继承，不以高事件均值推导账户收益。',
            ('同窗口贡献转负或年度/费用集中时，限制新机会推荐。',),
            date(2026,9,30),12041,('etf.unadjusted_daily',),
            ExperimentProtocol(ExperimentStage.MECHANISM_DISCOVERY,
                ('当前用户授权自主阶段二收益挖掘；不进入策略账户搜索。',),
                ('完整M05与共同域；全域纯动量与共同域；O01/M05和纯动量互补；Q07/N09删门控制。',),
                ('M05精确继承EX036 R01，O01/N09/Q07和旧共同域继承EX038；etf3仅当日已知。',),
                ('主5日；1/3/5/10日×延迟0/1/2×每侧10/20bp；不选最优期限或相位。',),
                ('所有h+1个固定相位、原1535日位置、去单年及年度；无未来异常质量筛选。',
                 '事件标签仅分析成熟样本，信号保留未成熟尾部；零填无触价；潜在触价不等于成交或闭合。',
                 '两有效域对照在共同域必须完全相等；域外收益独立显示，不能算为删门增量。',
                 '全开发池与前驱已见；不新增硬门，不新增数据。'),
                predecessor_experiment_ids=('EX038_20261006','EX036_20261006')),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),
            dependencies=tuple(ExperimentDependency(k,version(k)) for k in ('numpy','pandas')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,selects_parameters=False))

    def synthetic_precheck(self):
        ix=pd.bdate_range('2020-06-05',periods=60);t=np.arange(60);price=5+.01*t+.1*np.sin(t)
        d=pd.DataFrame({'Open':price,'Close':price,'Low':price-.05},index=ix)
        f=pd.DataFrame({'etf3':d.Close.pct_change(3,fill_method=None)},index=ix)
        old=pd.DataFrame(False,index=ix,columns=['L01','L03','L02','C_M05','C_MOMPOS'])
        ov=old.copy();ov[:]=True;ov.loc[ix[:20],['C_MOMPOS','C_M05']]=False
        old.C_MOMPOS=(f.etf3>0)&ov.C_MOMPOS;old.C_M05=(t%7==0)&ov.C_M05
        n=pd.DataFrame({'R01':t%7==0},index=ix);nv=pd.DataFrame({'R01':True},index=ix)
        s,v=build(d,f,old,ov,n,nv);sp,vp=build(d.iloc[:40],f.iloc[:40],old.iloc[:40],ov.iloc[:40],n.iloc[:40],nv.iloc[:40])
        pd.testing.assert_frame_equal(s.iloc[:40],sp);pd.testing.assert_frame_equal(v.iloc[:40],vp)
        assert (s.momentum[ov.C_MOMPOS]==s.momentum_common[ov.C_MOMPOS]).all()
        assert (s.m05[ov.C_M05]==s.m05_common[ov.C_M05]).all()
        np.testing.assert_array_equal(np.sort(np.concatenate([np.flatnonzero(t%6==p) for p in range(6)])),t)
        return ExperimentPrecheckResult(tuple(ExperimentPreflightCheck(k,ExperimentPreflightStatus.PASS,'合成边界核验')
            for k in ('PREFIX','COMMON_DOMAIN','ALL_PHASES')),ExperimentResult(ExperimentOutcome.PASS,{'checks':3},{}))

    def execute(self,context):
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        base=Path(__file__).resolve().parents[1];frames={};hashes={};artifacts=[]
        for key,(eid,name) in INPUTS.items():
            source=base/eid/'artifacts/rex'/name
            expected={a.path:a.sha256 for a in context.predecessors[eid].artifacts}
            digest=sha256(source.read_bytes()).hexdigest()
            if digest!=expected[name]:raise ValueError('changed predecessor '+eid+'/'+name)
            frames[key]=pd.read_parquet(source);frames[key].attrs={}
            hashes[key]={'experiment_id':eid,'artifact':name,'sha256':digest}
        d=frames['daily'];s,v=build(d,frames['features'],frames['old'],frames['old_valid'],frames['native'],frames['native_valid'])
        if len(d)!=1535:raise ValueError('window differs')
        rows,annual,pairs,lab=analyze(d,s,v)
        for key in ('m05_common','momentum_common'):
            full='m05' if key=='m05_common' else 'momentum'
            assert (s.loc[v[key],key]==s.loc[v[key],full]).all()
        coverage={'sessions':len(d),'paths':len(rows),'annual_rows':len(annual),'phase_rows':len(pairs),
                  'signals':{k:{'valid_days':int(v[k].sum()),'active_days':int(s[k].sum()),
                               'first_valid':str(d.index[v[k]][0].date())} for k in s},
                  'selection_history':'全部开发池已见；期限及相位不择优；非完整账户'}
        for name,value in (('source_hashes.json',hashes),('opportunities.json',rows),('annual.json',annual),
                            ('phase_comparisons.json',pairs),('coverage.json',coverage)):
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
            artifacts.append(context.workspace.register_artifact(name,'mechanism'))
        for name,frame in (('daily',d),('signals',s),('valids',v),('labels',lab)):
            frame.to_parquet(context.workspace.path(name+'.parquet'))
            artifacts.append(context.workspace.register_artifact(name+'.parquet','mechanism'))
        return ExperimentResult(ExperimentOutcome.INCONCLUSIVE,{'paths':len(rows),'annual_rows':len(annual),'phase_rows':len(pairs)},
                                {'scope':'阶段二原生/共同域收益归因，真实成交与账户目标待阶段三'},tuple(artifacts))
