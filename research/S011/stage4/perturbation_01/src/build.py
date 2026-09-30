"""Summarize sealed EX28 without selecting a new strategy or mutating old packages."""
from pathlib import Path
from hashlib import sha256
import argparse
import importlib.util
import json
import shutil
import sys
import numpy as np
import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive

REPO=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
EX=REPO/'experiments/S011/20260930_S011_EX28';SOURCE=Path(__file__).resolve().parent.parent
OLD=REPO/'research/S011/stage4/iteration_03';REG=REPO/'research/S011/configurations.json'
sys.path.append(str(REPO/'research/S011/stage4/iteration_02/src'))
from contracts import Registry,Configuration,Decision,fingerprint,document_schema,validate_document

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def dump(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')

def summarize(frame):
    rows=[]
    for (center,kind,scenario),g in frame.groupby(['center_config_id','kind','scenario'],sort=True):
        groups=[('ALL',g)]
        if kind=='JOINT_HOLD13':groups += [(str(days),gg) for days,gg in g.groupby('max_days')]
        for holding,gg in groups:
            row={'center_config_id':center,'kind':kind,'scenario':scenario,'holding_stratum':holding,
                 'positions':len(gg),'unique_parameters':int(gg.design_id.nunique()),'qualified':int(gg.qualified.sum()),
                 'qualified_share':float(gg.qualified.mean()),'same_account_count':int(gg.same_center_account.sum())}
            for gate in ('return_pass','drawdown_pass','frequency_pass'):row[gate+'_count']=int(gg[gate].sum())
            row['frequency_below4']=int(gg.frequency.lt(4).sum());row['frequency_above6']=int(gg.frequency.gt(6).sum())
            for name in ('cagr','drawdown_magnitude','frequency','cagr_delta','drawdown_delta'):
                vals=gg[name]
                for label,quantile in [('min',0),('q10',.1),('median',.5),('q90',.9),('max',1)]:row[name+'_'+label]=float(vals.quantile(quantile))
            rows.append(row)
    return pd.DataFrame(rows)

def paired(frame):
    out=[]
    pairs=[('S011-CFG-000618','S011-CFG-000624'),('S011-CFG-000621','S011-CFG-000628'),
           ('S011-CFG-000618','S011-CFG-000621'),('S011-CFG-000624','S011-CFG-000628')]
    for a,b in pairs:
        left=frame[frame.center_config_id.eq(a)];right=frame[frame.center_config_id.eq(b)]
        merged=left.merge(right,on=['kind','probe','scenario'],suffixes=('_a','_b'),validate='one_to_one')
        assert len(merged)==94
        for row in merged.to_dict('records'):
            out.append({'config_a':a,'config_b':b,'kind':row['kind'],'probe':row['probe'],'scenario':row['scenario'],
                        'design_a':row['design_id_a'],'design_b':row['design_id_b'],
                        'cagr_b_minus_a':row['cagr_b']-row['cagr_a'],
                        'drawdown_magnitude_b_minus_a':row['drawdown_magnitude_b']-row['drawdown_magnitude_a'],
                        'frequency_b_minus_a':row['frequency_b']-row['frequency_a'],
                        'qualified_a':row['qualified_a'],'qualified_b':row['qualified_b']})
    return pd.DataFrame(out)

def research_findings(stats,frame):
    centers=[]
    for cid in ('S011-CFG-000618','S011-CFG-000624','S011-CFG-000621','S011-CFG-000628'):
        rows=stats[stats.center_config_id.eq(cid)&stats.holding_stratum.eq('ALL')]
        values={}
        for r in rows.itertuples():
            values[r.scenario+'/'+r.kind]={'positions':r.positions,'original_goals_met':r.qualified,
                'cagr_median':r.cagr_median,'cagr_delta_median':r.cagr_delta_median,
                'return_goal_misses':r.positions-r.return_pass_count,'frequency_goal_misses':r.positions-r.frequency_pass_count,
                'drawdown_goal_misses':r.positions-r.drawdown_pass_count}
        centers.append({'config_id':cid,'results':values})
    notes=[
        '本设计对四配置的宽邻域支持有限：单参数达标10/14、11/14、8/14、9/14，固定2天联合扰动降至5/16、2/16、1/16、1/16。它们不是未来成功概率。',
        '固定2天联合扰动的年化中位数分别为39.10%、36.62%、37.25%、34.81%，较各自中心下降10.71、13.18、5.86、8.30个百分点。主要退化来自收益，全部扰动账户的回撤仍优于同成本买入持有基准；回撤优于基准不等于保持中心低回撤。',
        '原中心40笔闭合交易对应每60日5.955笔，增加1笔即变成6.104笔、超过原上限。标准成本单参数频率越界分别3、1、3、1点，须与收益不足分开解释。',
        '000624与000628的entry从0.330提高到0.335时，年化分别降至41.36%与35.03%；较中心分别下降约8.44与8.08个百分点。中心账户相同不能推断邻域稳定性相同。',
        '收益组000624单参数达标数高于000618，但固定持有期联合达标数低于000618；低回撤组联合均仅1/16。旧不均匀近邻下的阅读代表不获得全面更稳健的结论，四个配置继续并列保留。',
        '20bp单边成本下，两组联合模块的四配置均0/16达到原目标，且全部未达收益目标。标准成本下持有期改为1/3天并联合改变其他参数也均0/16；这包含离散的大幅持有期改变，不统称微小扰动。',
        '研究判断：当前证据支持局部参数敏感性与成本脆弱性，尚不足以确认宽阔稳定区域，也不能单凭本设计判定过拟合或未来失效。建议用户把这些风险与原核心收益/回撤取舍一起审议；如继续研究，优先研究联合变化时的收益保持能力。'
    ]
    # Keep narrative claims numerically tied to the diagnostic table.
    standard=stats[stats.scenario.eq('standard')&stats.kind.eq('JOINT_HOLD2')&stats.holding_stratum.eq('ALL')].set_index('center_config_id')
    assert [int(standard.loc[c['config_id'],'qualified']) for c in centers]==[5,2,1,1]
    assert frame.drawdown_pass.all()
    joint=frame[frame.kind.str.startswith('JOINT')&frame.scenario.eq('fee_20bp')]
    assert not joint.return_pass.any()
    workers=read(EX/'artifacts/worker_execution.json')
    active=peak=0
    for _,change in sorted([(r['started'],1) for r in workers.values()]+[(r['finished'],-1) for r in workers.values()]):
        active+=change;peak=max(peak,active)
    return {'interpretation':'POSTHOC_RESEARCHER_JUDGMENT_ON_PRESPECIFIED_DESIGN','centers':centers,'notes':notes,
            'configured_processes':8,'distinct_worker_processes':len({r['pid'] for r in workers.values()}),'peak_overlapping_public_evaluations':peak,
            'resource_note':'10秒启动节流下实际评价重叠峰值为2；8个进程轮流参与不等于8个评价同时运行或50%CPU利用率。',
            'promotion_decision':'USER_ONLY_PENDING','core_pareto_changed':False}

def build(output,capture_managed_inputs=False):
    if output.exists() or not output.is_relative_to(REPO/'.tmp'):raise ValueError('use fresh .tmp output')
    validate_experiment_archive(EX)
    if read(EX/'experiment_manifest.json')['status']!='COMPLETE':raise ValueError('incomplete experiment; do not summarize as completed')
    artifacts=EX/'artifacts';protocol=read(artifacts/'protocol.json');table=pd.read_csv(artifacts/'trials.csv')
    assert len(table)==368 and not table[['design_id','scenario']].duplicated().any()
    slots=pd.DataFrame(read(artifacts/'design_slots.json'));points=read(artifacts/'unique_parameters.json')
    registry=Registry.model_validate(read(REG)).model_dump();original=registry['configurations'].copy()
    by_fingerprint={c['config_fingerprint']:c['config_id'] for c in original};last=max(int(c['config_id'].split('-')[-1]) for c in original)
    mapping={};new_ids=[]
    for i,p in enumerate(points):
        definition=read(artifacts/f'trials/T{i:03}/payload.json');assert definition['parameters']==p
        fp=fingerprint(definition)
        if fp not in by_fingerprint:
            last+=1;cid=f'S011-CFG-{last:06}';reference=f'EX28T{i:03}'
            item=Configuration(config_id=cid,config_fingerprint=fp,definition=definition,
                source_root='experiments/S011/20260930_S011_EX28/runtime/strategy_runtime',first_reference=reference,references=[reference],scope='COMPARABLE_DEVELOPMENT').model_dump()
            registry['configurations'].append(item);by_fingerprint[fp]=cid;new_ids.append(cid)
        mapping[i]=by_fingerprint[fp]
    assert registry['configurations'][:len(original)]==original
    accounts={};audit=[]
    for row in table.itertuples():
        folder=artifacts/f'trials/T{row.design_id:03}/{row.scenario}'
        a=pd.read_csv(folder/'account_daily.csv.gz');t=pd.read_csv(folder/'trades.csv.gz');eq=a.equity
        m=[float((eq.iloc[-1]/1e6)**(252/len(eq))-1),float((eq/eq.cummax().clip(lower=1e6)-1).min()),int(t.status.eq('CLOSED').sum())]
        assert len(a)==403 and np.allclose(m,[row.cagr,row.drawdown,row.closed_trades],rtol=0,atol=1e-10)
        assert np.isclose(60*m[2]/403,row.frequency,rtol=0,atol=1e-12)
        b=protocol['benchmark'][row.scenario]
        gates=[m[0]>=1.5*b['cagr'] and (b['cagr']>0 or m[0]>max(0,b['cagr'])),m[1]>b['drawdown'],4<=row.frequency<=6]
        assert gates==[row.return_pass,row.drawdown_pass,row.frequency_pass] and all(gates)==row.qualified
        accounts[(row.design_id,row.scenario)]=a
        audit.append({'design_id':row.design_id,'scenario':row.scenario,'metric_and_original_gate_reconstruction':'PASS'})
    table['config_id']=table.design_id.map(mapping)
    table['drawdown_magnitude']=-table.drawdown
    slots['perturbed_config_id']=slots.design_id.map(mapping)
    frame=slots.drop(columns=['parameters']).merge(table,on='design_id',validate='many_to_many')
    assert len(frame)==376
    center_rows=frame[frame.kind.eq('CENTER')].set_index(['center_config_id','scenario'])
    same=[];deltas=[]
    for row in frame.itertuples():
        center=center_rows.loc[(row.center_config_id,row.scenario)]
        a=accounts[(row.design_id,row.scenario)];b=accounts[(int(center.design_id),row.scenario)]
        columns=['equity','cash','quantity']
        # Account field names are verified against the sealed ledger, not guessed/imputed.
        assert all(c in a and c in b for c in columns)
        same.append(bool(np.allclose(a[columns],b[columns],rtol=0,atol=1e-8)))
        deltas.append((row.cagr-center.cagr,row.drawdown_magnitude-center.drawdown_magnitude))
    frame['same_center_account']=same
    frame['cagr_delta']=[x[0] for x in deltas];frame['drawdown_delta']=[x[1] for x in deltas]
    frame['failed_original_goals']=['|'.join(name for name,passed in [('RETURN',r.return_pass),('DRAWDOWN',r.drawdown_pass),('FREQUENCY',r.frequency_pass)] if not passed) or 'NONE' for r in frame.itertuples()]
    diagnostics=summarize(frame);comparisons=paired(frame)
    failures=frame.groupby(['center_config_id','kind','scenario','failed_original_goals'],sort=True).size().rename('positions').reset_index()
    findings=research_findings(diagnostics,frame)
    direction=[]
    for (center,kind,scenario),g in frame[frame.kind.str.startswith('JOINT')].groupby(['center_config_id','kind','scenario']):
        offsets=np.stack(g.offset.to_numpy())
        for i,param in enumerate(protocol['steps']):
            if not (offsets[:,i]>0).any():continue
            pos=g.loc[offsets[:,i]>0];neg=g.loc[offsets[:,i]<0]
            direction.append({'center_config_id':center,'kind':kind,'scenario':scenario,'parameter':param,
                'positive_count':len(pos),'negative_count':len(neg),'positive_minus_negative_mean_cagr':float(pos.cagr.mean()-neg.cagr.mean()),
                'positive_minus_negative_mean_drawdown':float(pos.drawdown_magnitude.mean()-neg.drawdown_magnitude.mean()),
                'limitation':'Balanced marginal contrast; higher-order interactions aliased, not an isolated causal effect'})
    output.mkdir(parents=True)
    # Archive the public managed preparations as evidence, not as renamed runtime caches.
    # Explicit capture makes later diagnostics independent of temporary store survival.
    if capture_managed_inputs:
        managed=[];input_signatures=[]
        for i in range(len(points)):
            directories=list((REPO/'.tmp/s011-ex28-execution').glob(f'S011EX28T{i:03}_159326_*/preparations/20250206_20260928'))
            if len(directories)!=1:raise ValueError('exact same-candidate managed preparation required')
            directory=directories[0];raw=(directory/'prepared-data.json').read_bytes();prepared=json.loads(raw)
            assert prepared['reference_id']==f'S011-EX28T{i:03}'
            archived={}
            for name,info in prepared['inputs'].items():
                source=directory/info['file'];assert digest(source)==info['file_sha256']
                destination=output/'inputs'/(info['file_sha256']+'.csv.gz');destination.parent.mkdir(exist_ok=True)
                if not destination.exists():shutil.copyfile(source,destination)
                archived[name]=destination.relative_to(output).as_posix()
            input_signatures.append({k:v['content_sha256'] for k,v in prepared['inputs'].items()})
            managed.append({'design_id':i,'reference_id':prepared['reference_id'],'prepared_manifest_bytes':raw,
                            'manifest_file_sha256':sha256(raw).hexdigest(),'archived_input_files':json.dumps(archived,sort_keys=True)})
        assert all(s==input_signatures[0] for s in input_signatures),'confounded comparison: signal input contents differ across parameters'
        pd.DataFrame(managed).to_parquet(output/'managed_input_provenance.parquet',index=False)
    else:
        # Explicit archived-input mode: missing evidence is an error, never a cache fallback.
        existing=read(SOURCE/'manifest.json')
        for name,h in existing['files'].items():
            if name=='managed_input_provenance.parquet' or name.startswith('inputs/'):
                assert digest(SOURCE/name)==h,name
                (output/name).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/name,output/name)
    for name,data in [('evaluations',table),('design_positions',frame),('diagnostics',diagnostics),('failure_patterns',failures),('paired_comparisons',comparisons),('direction_contrasts',pd.DataFrame(direction)),('account_audit',pd.DataFrame(audit))]:data.to_parquet(output/(name+'.parquet'),index=False)
    dump(output/'configurations.json',registry)
    dump(output/'registration_delta.json',{'predecessor_snapshot':'research/S011/configurations.json','predecessor_sha256':digest(REG),
        'original_entries_unchanged':len(original),'new_config_ids':new_ids,'design_to_config':mapping,
        'policy':'Successor append-only registry snapshot; old registry file and old packages remain immutable. Use this snapshot as the base for subsequent registrations.'})
    dump(output/'protocol.json',protocol)
    dump(output/'findings.json',findings)
    dump(output/'decision.json',Decision().model_dump())
    shutil.copyfile(OLD/'pareto.json',output/'pareto.json')
    dump(output/'assessment.json',{'status':'PARAMETER_PERTURBATION_SELF_CHECK_COMPLETE_PENDING_USER_DECISION',
        'original_four_centers':protocol['center_ids'],'positions':188,'unique_parameters':184,'complete_accounts':368,'new_registered_configs':len(new_ids),
        'economic_gates_added':False,'new_winner_selected':False,'existing_core_ranking':'Copied unchanged from iteration_03; perturbation is diagnostic, not a new ranking objective.',
        'statistics_scope':'Original PBO/DSR cover the previous search pool only. This experiment adds184 standard-account evaluations and184 cost stresses; no updated PBO/DSR or independent validation claimed.',
        'limits':['Fixed local scales only','Balanced pairwise directions, aliased higher interactions','Not full factorial coverage','Existing development pool','No capacity/latency or forward validation'],
        'account_reconstruction_passed':368,'same_signal_input_contents_across_all_parameters':True,
        'managed_preparation_evidence':'managed_input_provenance.parquet and inputs/; captured snapshots are evidence only, not a runtime cache substitution'})
    shutil.copytree(SOURCE/'src',output/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    if (SOURCE/'tests').exists():shutil.copytree(SOURCE/'tests',output/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    report(output,diagnostics,comparisons,new_ids,frame,findings)
    schemas={p.name:document_schema(read(p)) for p in output.glob('*.json') if p.name not in ('configurations.json','manifest.json')}
    dump(output/'schemas/documents.json',schemas)
    source_files={str(p.relative_to(REPO)).replace('\\','/'):digest(p) for p in (EX/'experiment_manifest.json',REG,OLD/'manifest.json',OLD/'pareto.json',REPO/'research/S011/stage4/iteration_02/src/contracts.py')}
    files={p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()}
    dump(output/'manifest.json',{'files':files,'inputs':source_files,'experiment':'experiments/S011/20260930_S011_EX28',
        'input_policy':'Raw SHA256; registry/old package files are immutable. Experiment manifest recursively authenticates all source and ledger inputs.',
        'decision_authority':'USER_ONLY','entrypoint':'src/build.py --output <fresh .tmp directory>; --validate <package>'})
    validate(output)

def report(output,stats,comparisons,new_ids,frame,findings):
    lines=['# 四配置参数扰动补充自检','',
        '对象：S011-CFG-000618、000624、000621、000628。188个设计位置、184组唯一参数、368条完整账户；同一偏移配对比较。所有结果为已见开发池，达标比例只描述本设计。','',
        '## 研究判断','']
    lines += ['- '+note for note in findings['notes']]
    lines += ['', '[结构化判断](findings.json)区分数值证据与事后研究解释，不新增硬门，不自动晋升。','',
        '## 扰动尺度','',
        'tail_weight ±0.025；spx_weight ±0.025；entry ±0.005；exit ±0.025；lookback ±10个交易日；premium ±0.0005（5bp）；max_days从2天变为1/3天。每个中心包括14个单参数双向点、16个固定2天六参数联合点、16个七参数联合点，另复算中心。联合点每维正负各8次、每对方向组合各4次。','',
        '10bp/20bp均为单边成交成本（0.1%/0.2%），评价期2025-02-06至2026-09-28、403交易日。标准/压力的原收益目标分别约40.1648%/40.0438%年化，回撤须严格优于同成本买入持有、交易频率须在每60日4至6笔。此处报告原目标达成情况，不将其升级为阶段四自动阻断规则。','',
        '## 标准成本分层结果','',
        '| 配置 | 模块 | 持有期分层 | 达到原目标 | 年化最小/中位/最大 | 最大回撤幅度最差值 | 频率超过6笔的点数 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for r in stats[stats.scenario.eq('standard')].itertuples():
        lines.append(f'| {r.center_config_id} | {r.kind} | {r.holding_stratum} | {r.qualified}/{r.positions} | {r.cagr_min:.2%}/{r.cagr_median:.2%}/{r.cagr_max:.2%} | {r.drawdown_magnitude_max:.2%} | {r.frequency_above6} |')
    lines += ['', 'CENTER=中心；AXIS=单参数双向；JOINT_HOLD2=六参数联合、持有期2天；JOINT_HOLD13=七参数联合、持有期1/3天。1/3天各8点是同一16点集合的分层，不另加样本。','',
              '## 双倍成本分层结果','',
              '| 配置 | 模块 | 持有期分层 | 达到原目标 | 年化最小/中位/最大 | 回撤幅度最差值 |',
              '| --- | --- | --- | --- | --- | --- |']
    for r in stats[stats.scenario.eq('fee_20bp')].itertuples():
        lines.append(f'| {r.center_config_id} | {r.kind} | {r.holding_stratum} | {r.qualified}/{r.positions} | {r.cagr_min:.2%}/{r.cagr_median:.2%}/{r.cagr_max:.2%} | {r.drawdown_magnitude_max:.2%} |')
    lines += ['', '## 单参数方向明细（标准成本）','',
              '每格为“年化/回撤幅度/每60日闭合交易频率”；完整原目标分项见design_positions.parquet。','',
              '| 扰动 | 000618 | 000624 | 000621 | 000628 |', '| --- | --- | --- | --- | --- |']
    axis=frame[frame.kind.eq('AXIS')&frame.scenario.eq('standard')]
    for probe in axis.probe.drop_duplicates():
        values=[]
        for center in ('S011-CFG-000618','S011-CFG-000624','S011-CFG-000621','S011-CFG-000628'):
            r=axis[axis.probe.eq(probe)&axis.center_config_id.eq(center)].iloc[0]
            values.append(f'{r.cagr:.2%}/{r.drawdown_magnitude:.2%}/{r.frequency:.3f}')
        lines.append('| '+probe+' | '+' | '.join(values)+' |')
    lines += ['',
              '## 同组配对比较','', '| 配置A→B | 模块 | 场景 | B达标/A达标 | B−A年化差中位数 |', '| --- | --- | --- | --- | --- |']
    mask=(comparisons.config_a.eq('S011-CFG-000618')&comparisons.config_b.eq('S011-CFG-000624'))|(comparisons.config_a.eq('S011-CFG-000621')&comparisons.config_b.eq('S011-CFG-000628'))
    for (a,b,kind,scenario),g in comparisons[mask].groupby(['config_a','config_b','kind','scenario']):
        lines.append(f'| {a}→{b} | {kind} | {scenario} | {int(g.qualified_b.sum())}/{int(g.qualified_a.sum())}（各{len(g)}点） | {g.cagr_b_minus_a.median()*100:.3f}个百分点 |')
    lines += ['', '## 证据与局限','',
        f'追加登记{len(new_ids)}个配置，最新追加式[注册快照](configurations.json)保留旧666条完整前缀；[注册增量](registration_delta.json)记录新旧映射。旧注册文件、实验和阶段四包均不改写。','',
        '主要机器结果：[分层诊断](diagnostics.parquet)、[全部位置](design_positions.parquet)、[未达原因](failure_patterns.parquet)、[配对差异](paired_comparisons.parquet)、[方向对照](direction_contrasts.parquet)、[账户复核](account_audit.parquet)、[评估局限](assessment.json)。参数改动后的新账户均保留完整失败/未达标证据，不自动替代原四配置。','',
        findings['resource_note']+'Optuna采用InMemoryStorage，184次trial全部完成。','',
        '正负及两两方向均衡不等于全部高阶交互已验证；本轮没有扩展到第二种扰动尺度、没有新增前瞻数据，也不覆盖盘口容量/延迟。旧PBO/DSR尚未覆盖本次追加评价。','',
        '复算：从仓库根用既有.venv执行本包src/build.py --output <新的.tmp目录>；校验用--validate <包目录>。原实验只读。下一步由用户根据补充风险决定是否晋升具体配置；当前[决定](decision.json)保持待用户确认。']
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')

def validate(package):
    manifest=read(package/'manifest.json');validate_experiment_archive(REPO/manifest['experiment'])
    actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file() and p!=package/'manifest.json' and '__pycache__' not in p.parts}
    assert actual==set(manifest['files'])
    for name,h in manifest['files'].items():assert digest(package/name)==h,name
    for name,h in manifest['inputs'].items():assert digest(REPO/name)==h,name
    Registry.model_validate(read(package/'configurations.json'));Decision.model_validate(read(package/'decision.json'))
    for name,schema in read(package/'schemas/documents.json').items():validate_document(read(package/name),schema)
    frame=pd.read_parquet(package/'design_positions.parquet')
    provenance=pd.read_parquet(package/'managed_input_provenance.parquet')
    assert len(provenance)==184 and provenance.design_id.nunique()==184
    for row in provenance.itertuples():
        assert sha256(row.prepared_manifest_bytes).hexdigest()==row.manifest_file_sha256
        p=json.loads(row.prepared_manifest_bytes);locations=json.loads(row.archived_input_files)
        for name,info in p['inputs'].items():assert digest(package/locations[name])==info['file_sha256']
    signatures=[{k:v['content_sha256'] for k,v in json.loads(row.prepared_manifest_bytes)['inputs'].items()} for row in provenance.itertuples()]
    assert all(s==signatures[0] for s in signatures)
    # parquet roundtrip stores ndarray offsets, while the summary only uses metric columns.
    pd.testing.assert_frame_equal(summarize(frame),pd.read_parquet(package/'diagnostics.parquet'))
    pd.testing.assert_frame_equal(paired(frame),pd.read_parquet(package/'paired_comparisons.parquet'))
    assert len(frame)==376 and frame[['center_config_id','kind','probe','scenario']].duplicated().sum()==0
    assert read(package/'configurations.json')['configurations'][:666]==read(REG)['configurations']
    print(json.dumps({'status':'PASS','account_paths':368,'design_positions':188,'registry_entries':len(read(package/'configurations.json')['configurations'])}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--output',type=Path);g.add_argument('--validate',type=Path)
    parser.add_argument('--capture-managed-inputs',action='store_true',help='Initial evidence capture only; subsequent builds read the sealed snapshot, never a temporary cache.')
    a=parser.parse_args()
    build(a.output.resolve(),a.capture_managed_inputs) if a.output else validate(a.validate.resolve())
