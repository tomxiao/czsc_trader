"""Outcome-blind tsfresh census followed by one fixed role-validation family."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
import argparse
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,validate_experiment
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope
from dataflows import DataRequest,Dataset,PreparedDataRef
import extract_path as ep

ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;EX=ExperimentRef('S015',HERE.name)
TARGETS=['net3','entry','loss3']


def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(2,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def module(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def dependency(ex,key):
    return read(BASE/ex/'others/published_refs.json')['materials'][key]


def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    assert read(HERE/'others/api_preflight.json')['status']=='PASS'
    prior=read(BASE/'EX039_20261023/others/input_refs.json')
    dependencies={
      'ridge_source':prior['EX036_20261023/src/validate.py'],
      'utility_source':prior['EX038_20261023/src/attribution.py'],
      'interval_source':dependency('EX039_20261023','src/standalone.py'),
      'model_features':prior['EX036_20261023/others/model_features.csv'],
      'labels':prior['EX036_20261023/others/labels.csv'],
      'baseline_predictions':dependency('EX039_20261023','others/predictions.csv'),
      'price_census':dependency('EX035_20261023','others/features.csv'),
      'price_input_refs':dependency('EX035_20261023','others/input_refs.json'),
    }
    definitions={
      'return_autocorrelation1':'Eight log-close increments u: lag1 centered autocovariance divided by variance, tsfresh exact implementation. Adds magnitude-sensitive serial dependence beyond sign persistence.',
      'return_roughness':'cid_ce(normalize=True) on u: norm of adjacent standardized-return changes. Describes roughness in return acceleration; unsigned risk/state information.',
      'return_zero_crossings':'number_crossing_m(m=0) on u: changes of strict-positive indicator between adjacent steps, including equality on nonpositive side. Discloses library equality convention; not inferred tick crossings.',
      'afternoon_energy_share':'energy_ratio_by_chunks(num_segments=2,segment_focus=1) on eight u: last four squared moves / all eight squared moves. Unsigned timing concentration, distinct from signed halfday balance but possibly redundant.',
      'open_reference_crossings':'number_crossing_m(m=0) on q=log(eight closes/day open). Repeated sign-side changes around opening reference; eight snapshots only, not all intrabar crossings.',
      'path_roughness':'cid_ce(normalize=True) on eight q: norm of adjacent standardized cumulative-price changes. Omits open-to-first-close in the difference, follows the fixed library formula, not an interpolated path.',
    }
    protocol={
      'authorization':'User approved first-principles price census and unlimited stage-two component rounds; EX041 fills applicable actual tsfresh-tool census and roughness coverage. No new dependency/source/date/funding model, no stage-three account.',
      'reason_for_tool':'An ordered eight-observation session path is a short time series; tsfresh provides inspectable fixed serial-dependence, roughness, crossing and energy-timing expressions. EX035 used custom expressions only, so this is a documented supplement, not a retroactive claim it used tsfresh.',
      'settings':ep.SETTINGS,'columns':ep.COLUMNS,'family':'tsfresh_roughness6','definitions':definitions,
      'input':'Existing authenticated raw 159326.SZ 30-minute snapshot, 434 dates through 2026-10-21, exactly eight times as EX035. u[0]=log(first close/day open), u[i]=log(close[i]/close[i-1]); q[i]=log(close[i]/day open). Entire day is observed at T decision; no within-bar high-low ordering.',
      'library':'Installed tsfresh 0.21.1; extract_features uses exactly the six specified calculators, n_jobs=2, native threads=1, no imputer. Frozen preflight records API/source identities and serial-parallel equality on three synthetic paths.',
      'undefined':'Library undefined outputs remain NaN. A six-feature complete-case cohort is frozen before labels are read; report all missingness and dates. All four comparison models train/test on the SAME complete-case rows; no zero fill, no silently dropped expressions. Synthetic flat-series undefined autocorrelation and energy are preserved.',
      'census':'Extract once with two workers; independently call the fixed calculators on every isolated day, compare 434x6 cells; three chronological prefix checks (1,100,434 days). Correlations with all 24 prior price expressions report redundancy, not an automatic efficacy gate.',
      'validation':'One six-expression family, no expression/parameter search. Targets net3,entry,loss3 exactly EX039 authenticated labels. Four purged expanding folds and linear Ridge alpha10 exactly old helper. Models constant, legacy=old PRICE+pressure, tsfresh=six new columns, legacy_tsfresh=legacy+six. Entry costs only buy fee; net3 includes original both-side fees; risk payoff is same-row net3.',
      'purge':'position<test start and actual known_date strictly before first test date; same complete-case cohort for all models. All preprocessing/standardization train-only. This already-seen pool is NOT independent validation.',
      'participation':'Signed net3/entry prediction>=0. loss3 model prediction <= median of SAME MODEL training fitted predictions, fixed per fold. No held-position/exit claim and no test-ranking calibration.',
      'diagnostics':'All models and four folds: MSE, gains versus constant/legacy, actual retained/excluded event amounts and counts, loss caught/profit missed, paired full-axis block20 499 draws seed13 intervals for MSE reduction and retained payoff increment. Also omit five largest abs payoff events. Intervals/report diagnostics are not new user acceptance gates.',
      'verification':'Original-path dependency modules loaded only after byte equality to authenticated EvidenceRef. Independently refit predictions via augmented least-squares Ridge rather than normal-equation helper, check purging/thresholds/utility and regenerate summaries. Source hash verified before every mode.',
      'limits':'Eight observations have coarse resolution; high correlation/redundant transformations do not add economic information. Single cutoff/current HFQ-publication limitations unchanged. Overlapping events cannot be summed into account returns. No new candidates/continuous accounts.',
      'dependencies':dependencies,
    }
    save(HERE/'protocols/tsfresh_plan.json',protocol)
    paths=[HERE/'protocols/tsfresh_plan.json',HERE/'src/extract_path.py',Path(__file__),HERE/'others/api_preflight.json']
    save(HERE/'others/protocol_refs.json',{p.name:material(p).to_dict() for p in paths})
    print('EX041_PROTOCOL_SOURCE_FROZEN',flush=True)


def frozen():
    refs=read(HERE/'others/protocol_refs.json')
    for filename,folder in [('tsfresh_plan.json','protocols'),('extract_path.py','src'),('study.py','src'),('api_preflight.json','others')]:
        assert EvidenceRef.from_dict(refs[filename]).resolve(ROOT).read_bytes()==(HERE/folder/filename).read_bytes()
    return read(HERE/'protocols/tsfresh_plan.json')


def resolve(name):
    ref=EvidenceRef.from_dict(read(HERE/'protocols/tsfresh_plan.json')['dependencies'][name]);return ref.resolve(ROOT)


def helpers():
    modules=[]
    for key,ex,name in [('ridge_source','EX036_20261023','validate.py'),('utility_source','EX038_20261023','attribution.py'),('interval_source','EX039_20261023','standalone.py')]:
        original=BASE/ex/'src'/name;assert original.read_bytes()==resolve(key).read_bytes()
        modules.append(module(original,'verified_41_'+key))
    return modules


def census():
    frozen();assert not (HERE/'others/census.json').exists()
    inputs=read(resolve('price_input_refs'));ref=EvidenceRef.from_dict(inputs['source_inputs']['inputs'])
    facts=read(ref.resolve(ROOT));p=facts['minute_prepared'];prep=PreparedDataRef(UUID(p['space_id']),UUID(p['preparation_id']),p['manifest_sha256'])
    req=DataRequest(Dataset.ETF_UNADJUSTED_INTRADAY,'159326.SZ','2025-01-02','2026-10-21','2026-10-21',frequency='30m')
    fetched=context().data.fetch(req,prepared=prep);assert fetched.ready,fetched.error
    assert fetched.identity.content_sha256==facts['identities'][Dataset.ETF_UNADJUSTED_INTRADAY.value]['content_sha256']
    bars=fetched.dataframe.sort_values('Date').reset_index(drop=True);bars.attrs={}
    long,dates=ep.encode(bars);assert len(dates)==434
    x=ep.extract(long,2);assert x.index.tolist()==list(range(434))
    direct=[]
    for pos,g in long.groupby('position',sort=True):
        values={kind:z.sort_values('step').value.to_numpy(float) for kind,z in g.groupby('kind')}
        direct.append(ep.direct(values))
    np.testing.assert_allclose(x,np.asarray(direct),rtol=1e-12,atol=1e-12,equal_nan=True)
    for n in (1,100,434):
        prefix=ep.extract(long[long.position.lt(n)],2)
        np.testing.assert_allclose(prefix,x.iloc[:n],rtol=1e-12,atol=1e-12,equal_nan=True)
    x.insert(0,'position',x.index);x.insert(0,'date',dates);x=x.reset_index(drop=True)
    old=pd.read_csv(resolve('price_census'));assert old.date.tolist()==dates
    pairs=[]
    for a in ep.FEATURES:
        for b in [c for c in old if c not in ('date','position')]:
            valid=x[a].notna()&old[b].notna();v=x.loc[valid,a].corr(old.loc[valid,b],method='spearman')
            pairs.append({'new':a,'old':b,'n':int(valid.sum()),'spearman':float(v) if pd.notna(v) else None})
    pairs.sort(key=lambda r:abs(r['spearman']) if r['spearman'] is not None else -1,reverse=True)
    complete=np.isfinite(x[ep.FEATURES]).all(axis=1)
    result={'rows':len(x),'new_expressions':6,'settings':ep.SETTINGS,'missing':{c:int(x[c].isna().sum()) for c in ep.FEATURES},
      'undefined_dates':{c:x.loc[x[c].isna(),'date'].tolist() for c in ep.FEATURES},'complete_case_n':int(complete.sum()),
      'complete_positions':x.loc[complete,'position'].astype(int).tolist(),'columns':{c:{'unique_n':int(x[c].nunique()),'min':float(x[c].min()),'max':float(x[c].max())} for c in ep.FEATURES},
      'correlations':pairs,'isolated_day_calculator_checks':434,'isolated_calculator_cells':2604,'prefix_lengths':[1,100,434],
      'outcome_reads':0,'data_identity':fetched.identity.content_sha256,'interpretation':'New computational expressions, not six independent or effective economic components. No selection based on return labels.'}
    x.to_csv(HERE/'others/features.csv',index=False);save(HERE/'others/census.json',result)
    save(HERE/'others/input_refs.json',{'dependencies':read(HERE/'protocols/tsfresh_plan.json')['dependencies'],'raw_data_identity':fetched.identity.content_sha256,'price_input_facts':ref.to_dict()})
    print(json.dumps({'complete_case_n':int(complete.sum()),'missing':result['missing'],'top_correlations':pairs[:6]}),flush=True)


def summarize(p,models,old,attr,prior):
    results={}
    for name in models:
        loss=(p[name]-p.y)**2
        z={'n':len(p),'mse':float(loss.mean()),'utility':attr.utility(p,name,old),'folds':{},'all_events':old.amount(p.payoff)}
        for baseline in ('constant','legacy'):
            bl=(p[baseline]-p.y)**2;gain=(p['keep/'+name].astype(int)-p['keep/'+baseline].astype(int))*p.payoff
            z['mse_gain_vs_'+baseline]=float(1-loss.mean()/bl.mean())
            z['mse_delta_ci_vs_'+baseline]=prior.interval(p,bl-loss)
            z['retained_increment_vs_'+baseline]={'mean_per_event':float(gain.mean()),'ci95':prior.interval(p,gain)}
        for fold,g in p.groupby('fold'):
            z['folds'][str(fold)]={'n':len(g),'utility':attr.utility(g,name,old),
              'mse_gain_vs_constant':float(1-((g[name]-g.y)**2).mean()/((g.constant-g.y)**2).mean()),
              'mse_gain_vs_legacy':float(1-((g[name]-g.y)**2).mean()/((g.legacy-g.y)**2).mean())}
        z['omit_largest5_utility']=attr.utility(p.drop(p.payoff.abs().nlargest(5).index),name,old)
        results[name]=z
    return results


def validation_inputs():
    old,attr,prior=helpers();base=pd.read_csv(resolve('model_features'));labels=pd.read_csv(resolve('labels'))
    features=pd.read_csv(HERE/'others/features.csv');x=base.merge(features,on=['date','position'],validate='one_to_one')
    models={'constant':[],'legacy':old.PRICE+['pressure'],'tsfresh':ep.FEATURES,'legacy_tsfresh':old.PRICE+['pressure']+ep.FEATURES}
    return old,attr,prior,x,labels,models


def validate():
    frozen();assert not (HERE/'others/results.json').exists()
    old,attr,prior,x,labels,models=validation_inputs();previous=pd.read_csv(resolve('baseline_predictions'))
    complete=set(read(HERE/'others/census.json')['complete_positions']);net3=labels[labels.target.eq('net3')].set_index('position').y
    results={};allpred=[];meta=[];baseline_checks=0
    for target in TARGETS:
        g=x.merge(labels[labels.target.eq(target)].drop(columns=['date']),on='position',validate='one_to_one')
        g['payoff']=g.position.map(net3) if target=='loss3' else g.y;parts=[]
        for fold,(lo,hi) in enumerate(old.FOLDS):
            start=g.date.iloc[lo];train=g[g.position.lt(lo)&g.y.notna()&(g.known_date<start)&g.position.isin(complete)].copy()
            test=g[g.position.between(lo,hi-1)&g.y.notna()&g.position.isin(complete)].copy()
            if train.empty or test.empty:raise ValueError('Predeclared fold lacks complete-case evidence')
            p=test[['date','position','known_date','y','payoff']].copy();p['target']=target;p['fold']=fold
            before=previous[previous.target.eq(target)&previous.fold.eq(fold)].set_index('position')
            for name,cols in models.items():
                p[name]=old.ridge(train,test,cols);threshold=float(np.median(old.ridge(train,train,cols))) if target=='loss3' else 0.
                p['keep/'+name]=p[name]<=threshold if target=='loss3' else p[name]>=threshold
                if len(complete)==434 and name in ('constant','legacy'):
                    np.testing.assert_allclose(p[name],before.loc[p.position,name],rtol=1e-9,atol=1e-12);baseline_checks+=len(p)
                meta.append({'target':target,'fold':fold,'model':name,'columns':cols,'threshold':threshold,'train_n':len(train),'test_n':len(test),'test_start':start,'max_train_known_date':train.known_date.max()})
            parts.append(p)
        p=pd.concat(parts,ignore_index=True);allpred.append(p);results[target]=summarize(p,models,old,attr,prior)
        print(target,'fixed tsfresh roles complete',flush=True)
    pd.concat(allpred,ignore_index=True).to_csv(HERE/'others/predictions.csv',index=False)
    save(HERE/'others/thresholds.json',meta);save(HERE/'others/results.json',results)
    save(HERE/'others/design_counts.json',{'new_family':1,'new_expressions':6,'targets':3,'new_model_specs':6,'baseline_model_specs':6,'new_fold_fits':24,'baseline_fold_fits':24,'training_threshold_refits':16,'baseline_reproduced_prediction_cells':baseline_checks,'continuous_accounts':0,'new_candidates':0,'parameter_search':0,'tsfresh_workers':2,'native_threads':1,'small_ridge_fits':'serial deterministic closed-form, no nested worker pools'})


def audit():
    frozen();old,attr,prior,x,labels,models=validation_inputs()
    predicted=pd.read_csv(HERE/'others/predictions.csv');meta=read(HERE/'others/thresholds.json');results=read(HERE/'others/results.json')
    complete=set(read(HERE/'others/census.json')['complete_positions']);checks=0
    def fit(train,test,cols):
        if not cols:return np.repeat(train.y.mean(),len(test))
        a=train[cols].to_numpy(float);b=test[cols].to_numpy(float);center=np.mean(a,axis=0);scale=np.std(a,axis=0);scale[scale==0]=1
        a=np.column_stack([np.ones(len(a)),(a-center)/scale]);b=np.column_stack([np.ones(len(b)),(b-center)/scale])
        penalty=np.diag(np.r_[0.,np.repeat(np.sqrt(10),len(cols))]);aug=np.vstack([a,penalty]);y=np.r_[train.y.to_numpy(float),np.zeros(len(cols)+1)]
        return b@np.linalg.lstsq(aug,y,rcond=None)[0]
    for target in TARGETS:
        g=x.merge(labels[labels.target.eq(target)].drop(columns=['date']),on='position',validate='one_to_one')
        for fold,(lo,hi) in enumerate(old.FOLDS):
            start=g.date.iloc[lo];train=g[g.position.lt(lo)&g.y.notna()&(g.known_date<start)&g.position.isin(complete)]
            test=g[g.position.between(lo,hi-1)&g.y.notna()&g.position.isin(complete)]
            p=predicted[predicted.target.eq(target)&predicted.fold.eq(fold)]
            assert p.position.tolist()==test.position.tolist();checks+=len(p)
            assert train.known_date.max()<start
            for name,cols in models.items():
                values=fit(train,test,cols);np.testing.assert_allclose(values,p[name],rtol=1e-9,atol=1e-12);checks+=len(p)
                threshold=float(np.median(fit(train,train,cols))) if target=='loss3' else 0.
                m=next(z for z in meta if z['target']==target and z['fold']==fold and z['model']==name)
                assert abs(threshold-m['threshold'])<1e-12
                keep=values<=threshold if target=='loss3' else values>=0
                np.testing.assert_array_equal(keep,p['keep/'+name]);checks+=len(p)
        p=predicted[predicted.target.eq(target)]
        # Recompute payoff utility independently from sum identities.
        for name in models:
            y=p.payoff.to_numpy(float);keep=p['keep/'+name].to_numpy(bool);u=results[target][name]['utility']
            assert int(keep.sum())==u['selected']['n'];checks+=1
            np.testing.assert_allclose([y[keep].sum(),np.maximum(-y[~keep],0).sum()/np.maximum(-y,0).sum(),np.maximum(y[~keep],0).sum()/np.maximum(y,0).sum()],
              [u['retained_event_sum'],u['caught_loss_fraction'],u['missed_profit_fraction']],rtol=1e-10,atol=1e-12);checks+=3
        regenerated=summarize(p,models,old,attr,prior)
        def compare(a,b):
            nonlocal checks
            if isinstance(a,dict):
                assert set(a)==set(b)
                for k in a:compare(a[k],b[k])
            elif isinstance(a,list):
                assert len(a)==len(b)
                for aa,bb in zip(a,b):compare(aa,bb)
            elif a is None:assert b is None;checks+=1
            else:np.testing.assert_allclose(a,b,rtol=1e-9,atol=1e-12);checks+=1
        compare(regenerated,results[target])
    save(HERE/'others/independent_audit.json',{'status':'PASS','checks':checks,'method':'Independent augmented least-squares Ridge refits all 48 fold/model predictions and risk thresholds; explicit utility sums; complete recursive regeneration of results including block intervals. Same agent performed separate-algorithm audit; not an independent analyst review.','source_hashes':{p.name:sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),HERE/'src/extract_path.py')}})
    print('EX041_RECOMPUTE_PASS',checks,flush=True)


def report():
    frozen();assert read(HERE/'others/independent_audit.json')['status']=='PASS'
    c=read(HERE/'others/census.json');r=read(HERE/'others/results.json');out=['# S015 tsfresh限定价格路径普查与职责验证','','Status: COMPLETED','',
      '本轮补齐适用时序普查对tsfresh的实际使用，以及相邻运动相关、路径粗糙和反复穿越的信息表达。EX035原24表达及历史证据保持不变。本轮没有新增候选或完整账户，不能据组件结果宣称策略达标。','',
      '固定六个表达后实际调用已安装tsfresh 0.21.1，2进程、每进程1原生线程；不扫描全库、不调参数。数据仍是已授权434日、每日8根30分钟原始价格，日末形成信号，不能虚构同根内部高低点顺序。','',
      f"全部434日实际提取，六列完整队列{c['complete_case_n']}日；缺失输出不填零。逐日隔离调用核验2604个值，另核对1/100/434日前缀。合成平价和恒定步幅中未定义自相关、能量占比保留NaN，未被伪装成0。",'',
      '| 新表达 | 与旧表达最强绝对秩相关 | 相关系数 |','| --- | --- | ---: |']
    for name in ep.FEATURES:
        p=next(z for z in c['correlations'] if z['new']==name);out.append(f"| {name} | {p['old']} | {p['spearman']:.4f} |")
    out+=['','相关性用于报告信息重复，不构成有效性门槛。以下固定四折净化前推：训练标签实际已知日必须早于测试首日；常数、旧量价基线、新六表达、旧基线加六表达使用相同队列。Ridge10，无列筛选、阈值或超参数搜索。风险阈值是各折同模型训练拟合预测中位，收益及入场日阈值为0。原开发池反复已见，不能称独立验证。','',
      '| 职责 | 模型 | MSE改善vs常数 | MSE改善vs旧基线 | 保留数 | 识别亏损金额 | 遗漏盈利金额 | 保留均值 |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for target,models in r.items():
        for name,z in models.items():
            u=z['utility'];out.append(f"| {target} | {name} | {100*z['mse_gain_vs_constant']:.3f}% | {100*z['mse_gain_vs_legacy']:.3f}% | {u['selected']['n']} | {100*u['caught_loss_fraction']:.2f}% | {100*u['missed_profit_fraction']:.2f}% | {100*u['selected']['mean']:.4f}% |")
    out+=['','## 四折与不确定性','', '| 职责/模型 | 各折MSE改善vs旧基线 | 各折保留事件均值 | MSE差95%块区间vs旧基线 | 保留金额增量每事件95%区间 |','| --- | --- | --- | --- | --- |']
    for target,models in r.items():
        for name in ('tsfresh','legacy_tsfresh'):
            z=models[name];gains='/'.join(f"{100*v['mse_gain_vs_legacy']:.2f}%" for v in z['folds'].values())
            means='/'.join(f"{100*v['utility']['selected']['mean']:.3f}%" if v['utility']['selected']['mean'] is not None else '无保留' for v in z['folds'].values())
            out.append(f"| {target}/{name} | {gains} | {means} | {z['mse_delta_ci_vs_legacy']} | {z['retained_increment_vs_legacy']['ci95']} |")
    out+=['','区间使用完整434日轴上20日块499次重抽样，种子13；收益标签和选择事件相互重叠，金额合计与区间不等于连续账户收益或独立因果效果。入场日只计买入费，不能与完整交易净收益混同；loss3的参与效果用同事件net3实际净收益衡量。','',
      '所有模型、四折、删去最大绝对损益5事件、相对常数和旧基线的区间完整保留，不根据最漂亮结果删行。原目标、频率与阶段权限均未改变；没有完整进退场策略或达标候选。','',
      '验证：48个fold/model以另一套增广最小二乘算法重算，核对实际训练净化、风险阈值、参与决定和用途；再重新计算全部汇总与块区间。审计由同一执行agent独立算法完成，不冒称独立分析者复核。','',
      '下一步建议由阶段二综合评审结合效用与反证判断此新家族是否保留为研究线索；不以工具使用、相关性或单项误差改善作为有效组件或策略达标的替代。','',
      '证据：[固定协议](protocols/tsfresh_plan.json)、[API及并行预检](others/api_preflight.json)、[普查](others/census.json)、[全部结果](others/results.json)、[预测](others/predictions.csv)、[重算审计](others/independent_audit.json)。']
    (HERE/'report.md').write_text('\n'.join(out)+'\n',encoding='utf-8',newline='\n')
    print('EX041_REPORT_READY',flush=True)


def publish():
    frozen();assert not (HERE/'others/published_refs.json').exists()
    assert read(HERE/'others/independent_audit.json')['status']=='PASS'
    refs=[EvidenceRef.from_dict(v) for v in read(HERE/'protocols/tsfresh_plan.json')['dependencies'].values()];materials={}
    for sub in ('src','protocols','others'):
        for p in sorted((HERE/sub).glob('*')):
            if p.suffix in ('.py','.json','.csv','.md'):
                ref=material(p);materials[f'{sub}/{p.name}']=ref.to_dict();refs.append(ref)
    rr=publish_evidence(context(),ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    v=validate_experiment(RepositoryContext.discover(ROOT),ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION));assert v.status.value=='PASS',v.issues
    save(HERE/'others/published_refs.json',{'report':rr.to_dict(),'materials':materials,'validation':v.to_dict()});print('EX041_PUBLISHED',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','census','validate','audit','report','publish']);globals()[p.parse_args().mode]()
