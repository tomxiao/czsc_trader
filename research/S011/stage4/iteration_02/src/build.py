"""Recompute decision package from sealed evidence; always use a new output directory."""
from pathlib import Path
from hashlib import sha256
from importlib.metadata import version
import argparse
import json
import shutil
import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from contracts import Registry,Decision,Pareto,canonical,pareto_layers,SCHEMAS,document_schema,validate_document
from inputs import REPO,Sources,load,evidence_digest
from analytics import analyze

SOURCE=Path(__file__).resolve().parent.parent


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def table(path,frame):
    frame.to_parquet(path,index=False)


def seal(output,sources):
    schemas={}
    for path in sorted(output.rglob('*.parquet')):
        schema=pq.read_schema(path)
        schemas[path.relative_to(output).as_posix()]=[{'name':f.name,'type':str(f.type),'nullable':f.nullable} for f in schema]
    dump(output/'schemas/tables.json',schemas)
    for name,schema in SCHEMAS.items():dump(output/f'schemas/{name}.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema',**schema})
    documents={}
    for path in sorted(output.rglob('*.json')):
        if 'schemas' in path.relative_to(output).parts or path==output/'manifest.json':continue
        value=json.loads(path.read_text(encoding='utf-8'))
        name={'configurations.json':'Registry','pareto.json':'Pareto','pareto_without_knn.json':'Pareto','decision.json':'Decision'}.get(path.name)
        documents[path.relative_to(output).as_posix()]=SCHEMAS[name] if name else document_schema(value)
    dump(output/'schemas/documents.schema.json',documents)
    files={p.relative_to(output).as_posix():sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'manifest.json' and '__pycache__' not in p.parts}
    dump(output/'manifest.json',{'schema_version':1,'path_base':'repository_root_for_inputs_package_root_for_files',
        'files':files,'inputs':sources.hashes,'environment':{k:version(k) for k in ('numpy','pandas','pyarrow','scipy','optuna')},
        'input_hash_policy':'SHA256_RAW_FOR_EXPERIMENTS_AND_BINARY; SHA256_AFTER_CRLF_TO_LF_FOR_OTHER_PY_MD_JSON_CSV; package file hashes are raw bytes',
        'python':sys.version,'output_identity':sha256(canonical(files).encode()).hexdigest(),
        'entrypoints':{'validate':'src/build.py validate --package <package>',
            'recompute':'src/build.py build --output <new-directory-under-.tmp>',
            'replay':'src/replay.py --config-id <id> --data-dir <same-candidate-managed-data> --output <new-directory-under-.tmp>'},
        'dependencies':'Existing project .venv; no new dependency installed; evidence inputs must be present with matching hashes',
        'decision_authority':'USER_ONLY','stage_five_started':False})


def validate(package):
    manifest=json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file() and p!=package/'manifest.json' and '__pycache__' not in p.parts}
    assert actual==set(manifest['files']), 'untracked or missing package files'
    for relative,digest in manifest['files'].items():
        if sha256((package/relative).read_bytes()).hexdigest()!=digest:raise ValueError('package changed: '+relative)
    for relative,digest in manifest['inputs'].items():
        if evidence_digest(REPO/relative)!=digest:raise ValueError('input changed: '+relative)
    registry=Registry.model_validate(json.loads((package/'configurations.json').read_text()))
    ids={c['config_id'] for c in registry.configurations}
    p=Pareto.model_validate(json.loads((package/'pareto.json').read_text()))
    Decision.model_validate(json.loads((package/'decision.json').read_text()))
    documents=json.loads((package/'schemas/documents.schema.json').read_text())
    for name,schema in documents.items():validate_document(json.loads((package/name).read_text(encoding='utf-8')),schema)
    metrics=pd.read_parquet(package/'ranking_metrics.parquet')
    assert pareto_layers(metrics.to_dict('records'),p.metrics)==p.model_dump()
    all_ranked={c for l in p.layers for c in l['config_ids']}
    assert all_ranked|set(p.unranked)==set(metrics.config_id)
    schemas=json.loads((package/'schemas/tables.json').read_text())
    for name,expected in schemas.items():
        schema=pq.read_schema(package/name)
        assert expected==[{'name':f.name,'type':str(f.type),'nullable':f.nullable} for f in schema]
        frame=pd.read_parquet(package/name)
        if 'config_id' in frame:assert set(frame.config_id.dropna())<=ids
    diagnostic=pd.read_parquet(package/'diagnostics.parquet')
    assert diagnostic.loc[diagnostic.status.eq('MISSING'),'value'].isna().all()
    assert diagnostic.loc[diagnostic.status.eq('COMPLETE'),'value'].notna().all()
    print(json.dumps({'status':'PASS','configurations':len(ids),'ranked':len(all_ranked),'unranked':len(p.unranked),'files':len(manifest['files'])}),flush=True)


def build(output):
    if output.exists():raise FileExistsError('use a fresh output directory')
    if not output.is_relative_to(REPO/'.tmp'):raise ValueError('build output must stay under repository .tmp')
    output.mkdir(parents=True)
    sources=Sources();protocol=sources.json(SOURCE/'protocol.json')
    for path in SOURCE.glob('src/*.py'):sources.record(path)
    for path in SOURCE.glob('tests/*.py'):sources.record(path)
    sources.record('research/RSCH_AGENT.md')
    sources.record('packages/strategy_evaluator/src/strategy_evaluator/search_bias.py')
    for name in ('EX26','EX27','statistics'):
        sources.record(f'research/S011/stage4/verification/{name}/verification.json')
    print('Validating and loading immutable accounts...',flush=True)
    data=load(sources)
    print(json.dumps({'loaded_configurations':len(data['registry']['configurations']),'evaluation_rows':len(data['evaluations'])}),flush=True)
    # Protocol and consumed source snapshot are materialized before new diagnostics.
    # Preserve protocol bytes: the delivered protocol is also a hashed input.
    shutil.copyfile(SOURCE/'protocol.json',output/'protocol.json');dump(output/'input_snapshot.json',sources.hashes)
    print('Recomputing joint observed geometry, temporal/cost statistics, bootstrap and search bias...',flush=True)
    result=analyze(data,protocol)
    sources.validate()
    dump(output/'configurations.json',data['registry']);dump(output/'decision.json',Decision().model_dump())
    dump(output/'historical_failures.json',data['history'])
    table(output/'evaluations.parquet',data['evaluations'])
    table(output/'cost_evaluations.parquet',data['cost_evaluations'])
    trial_events=data['evaluations'][['evaluation_id','config_id','reference','state','evidence','failure_reason']].to_dict('records')
    trial_events.extend({'evaluation_id':h['experiment']+'-failure-'+str(i),'config_id':None,'reference':h['experiment'],
        'state':'TECHNICAL_FAILURE','evidence':h['evidence'],'failure_reason':json.dumps(h['detail'],ensure_ascii=False)} for i,h in enumerate(data['history']))
    table(output/'trial_events.parquet',pd.DataFrame(trial_events))
    for name,value in result.items():
        if isinstance(value,pd.DataFrame):
            table(output/(name+'.parquet'),value.reset_index() if name=='returns' else value)
        else:dump(output/(name+'.json'),value)
    qualified=data['evaluations'].loc[data['evaluations'].qualified.eq(True)&data['evaluations'].scope.eq('COMPARABLE_DEVELOPMENT')]
    dump(output/'qualified_configurations.json',{'schema_version':1,'contract':'S011 original three gates; standard 10bp; EX16 integer-lot benchmark',
        'configurations':[{'config_id':cid,'evaluation_ids':g.evaluation_id.tolist()} for cid,g in qualified.groupby('config_id',sort=False)]})
    config_lookup={c['config_id']:c for c in data['registry']['configurations']}
    assessment={'schema_version':1,'status':'SELF_CHECK_COMPLETE_PENDING_USER_DECISION','development_only':True,
        'new_hard_gates':False,'automatic_promotion':False,'stage_five_started':False,
        'scope':'Read-only recomputation; no new parameter proposals or account executions; no platform modifications',
        'summary':{'registered_configurations':len(config_lookup),'comparable_configurations':data['evaluations'].loc[data['evaluations'].scope.eq('COMPARABLE_DEVELOPMENT'),'config_id'].nunique(),
            'qualified_configurations':qualified.config_id.nunique(),'distinct_comparable_behaviors':len(set(data['behaviors'].values())),
            'layer_sizes':[len(x['config_ids']) for x in result['pareto']['layers']],'unranked':result['pareto']['unranked'],
            'pbo':{str(x['block_count']):x['pbo'] for x in result['family_statistics']['pbo']},'effective_trial_count':result['family_statistics']['effective_trial_count']},
        'sorting_limits':['Exact Pareto after declared rounding; display by config ID does not rank within layer',
            'kNN is conditional on nonuniform adaptive samples; inspect radius and ranking-without-kNN sensitivity',
            'No ranking metric proves future profitability; PBO is research-family evidence, not individual eligibility'],
        'unmeasured':protocol['unmeasured'],
        'configuration_assessments':[],
        'review_options':[{'config_id':c,'first_reference':config_lookup[c]['first_reference'],'reason':'Non-dominated under declared diagnostic axes; inspect complete tradeoffs, not automatic selection'} for c in result['pareto']['layers'][0]['config_ids']],
        'historical_status':'Prior stage4 report selected a representative under superseded rules; immutable prior evidence preserved. Current decision is pending user selection.'}
    ranking=result['ranking_metrics'];layer_map={c:x['layer'] for x in result['pareto']['layers'] for c in x['config_ids']}
    for r in ranking.to_dict('records'):
        cid=r['config_id'];risks=[]
        if r['joint_observed_count']==0:risks.append('No joint neighbor within the registered local radius')
        if r['knn20_radius']>1:risks.append('Twenty-neighbor set extends beyond the local diagnostic radius; its qualification share is not local-box coverage')
        if pd.isna(r['fee20_cagr_loss']):risks.append('Same-source-version 20bp account missing; no cross-version imputation')
        risks+=['Development-only evidence with material search selection uncertainty','Real queue, capacity and execution delay untested']
        assessment['configuration_assessments'].append({'config_id':cid,'pareto_layer':layer_map.get(cid),'first_reference':r['first_reference'],
            'metrics':{k:(None if pd.isna(v) else v) for k,v in r.items() if k not in ('config_id','first_reference','behavior_id')},
            'tradeoff':'Compare all six dimensions and the without-kNN sensitivity; same-layer options have no forced ordering',
            'risks':risks,'evidence':['diagnostics.parquet','comparisons.parquet','ranking_metrics.parquet','family_statistics.json']})
    dump(output/'assessment.json',assessment)
    # Structured stage-three intake: no retrospective rewrite or rerun of original experiments.
    intake=output/'stage3_input';intake.mkdir()
    before=data['evaluations'].loc[~data['evaluations'].reference.str.startswith('EX27')]
    table(intake/'evaluations.parquet',before)
    dump(intake/'configurations.json',{'schema_version':1,'strategy_id':'S011','fingerprint_version':'S011_TYPED_CANONICAL_JSON_V1',
        'configurations':[c for c in data['registry']['configurations'] if c['config_id'] in set(before.config_id)]})
    s3q=before.loc[before.qualified.eq(True)&before.scope.eq('COMPARABLE_DEVELOPMENT')].drop_duplicates('config_id')
    dump(intake/'qualified_configurations.json',{'configurations':s3q[['config_id','evaluation_id']].to_dict('records')})
    objectives=[{'name':name,'direction':direction,'decimals':10} for name,direction in [('cagr','maximize'),('drawdown_magnitude','minimize')]]
    dump(intake/'pareto.json',pareto_layers(s3q.to_dict('records'),objectives))
    dump(intake/'hypothesis.json',{'strategy_family':'S011','hypothesis':'Short-lived ETF/domestic pressure followed by reversal, with strict-prior SPX information providing weak confirmation',
        'components':['COMP01','COMP02','COMP04'],'diagnostic_only_components':['COMP03'],
        'source':'research/S011/stage3/iteration_02/README.md','falsification':'The full causal executable account fails the original return/drawdown/frequency mandate or information/execution contract'})
    dump(intake/'implementation.json',{'implementations':list({c['definition']['runtime']['source_sha256']:c['source_root'] for c in data['registry']['configurations'] if c['config_id'] in set(before.config_id)}.items()),
        'parameter_contract':'src/contracts.py:Definition','source_closure_rule':'Each configuration references its exact immutable runtime; execution/input rules are fixed by source closure',
        'replay_entry':'src/replay.py','search_evidence':'Original immutable run_experiment.py, experiment.py and per-trial artifacts are referenced by input hashes; launching a new search requires a successor experiment, not an in-place rerun'})
    dump(intake/'protocol.json',{'kind':'STRUCTURED_MIGRATION_OF_SEALED_STAGE_THREE_INPUT',
        'source_protocols':[f'experiments/S011/20260930_S011_EX{n}/02_design.md' for n in (14,15,19,23,22,24,25)],
        'original_mandate':{**protocol['execution_policy'],'gates':{'cagr':'strategy >= 1.5 * same-contract EX16 buyhold; if buyhold <= 0 require strategy > 0 and > buyhold','drawdown':'strategy drawdown magnitude strictly less than buyhold','frequency':'4 <= 60 * closed_cycles / 403 <= 6'}},'new_search_performed':False,'legacy_EX14':'NONCOMPARABLE_LEGACY; original reported gates retained, not used as current qualification'})
    dump(intake/'assessment.json',{'status':'STRUCTURED_INPUT_MIGRATED','comparable_standard_paths':int(before.scope.eq('COMPARABLE_DEVELOPMENT').sum()),
        'qualified_configuration_count':len(s3q),'historical_failures':'historical_failures.json','limits':'Historical trial failures and raw proposal records remain linked in sealed archives; inherited successful trials counted once'})
    # Preserve prior attribution as typed reference rows, without inventing numbers.
    table(intake/'attribution.parquet',pd.DataFrame([{'kind':'PAIRED_ACCOUNT_ATTRIBUTION','evidence':'research/S011/stage3/iteration_02/paired_changes.json'},
        {'kind':'BOUNDARY_AND_SEARCH_COMPLETION','evidence':'research/S011/stage3/iteration_02/summary.json'}]))
    for path in ('research/S011/stage3/iteration_02/paired_changes.json','research/S011/stage3/iteration_02/summary.json'):sources.record(path)
    dump(intake/'manifest.json',{'schema_version':1,'kind':'INTAKE_SUBPACKAGE','authority':'Parent manifest hashes all files and source evidence','paths_relative_to':'repository_root_for_evidence_parent_package_for_code'})
    for directory in ('src','tests'):shutil.copytree(SOURCE/directory,output/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    report(output,result,assessment,config_lookup)
    seal(output,sources);validate(output)
    print(json.dumps(assessment['summary'],ensure_ascii=True),flush=True)


def report(output,result,assessment,configs):
    table_=result['ranking_metrics'].set_index('config_id');lines=['# S011阶段四迭代02：多维自检与用户决策包','',
        '状态：SELF_CHECK_COMPLETE_PENDING_USER_DECISION。未设置自检硬门，未批准任何配置晋升。全部为已见开发池。','',
        '## 配置与排序','',f'登记配置{assessment["summary"]["registered_configurations"]}个；当前达标配置{assessment["summary"]["qualified_configurations"]}个。源码版本不同则配置ID不同，不能与历史纯参数组合计数混用。','',
        '排序维度：年化、回撤幅度、20近邻达标比例、最差60日超额、前三笔正利润占比、20bp成本导致的年化损失。方向与容差见[protocol.json](protocol.json)。同层无强制名次。','',
        '| 层级 | 配置ID | 首次试验 | 年化 | 回撤幅度 | 20近邻比例 | 20bp年化损失 |','| --- | --- | --- | --- | --- | --- | --- |']
    for layer in result['pareto']['layers']:
        for cid in layer['config_ids']:
            r=table_.loc[cid];lines.append(f'| {layer["layer"]} | {cid} | {configs[cid]["first_reference"]} | {r.cagr:.2%} | {r.drawdown_magnitude:.2%} | {r.knn20_qualified_share:.0%} | {r.fee20_cagr_loss:.2%} |')
    lines+=['','未排名配置与原因：`'+json.dumps(result['pareto']['unranked'],ensure_ascii=False)+'`。证据缺失不等于淘汰。','',
        '## 证据边界','',
        '联合检查使用全部封存参数的已观测多维变化与连通关系；没有新增均衡联合扰动，kNN半径与密度不一致。另提供[去掉kNN的分层](pareto_without_knn.json)，不能把局部比例当总体成功概率。','',
        'PBO使用完整可比行为池（含未达标配置），以Sharpe选优作分块比较；它不能完整复刻原约束多目标TPE，也不是未来亏损概率。DSR并列588/685次以及相关结构有效次数口径，不覆盖此前全部机制研究与S010选择历史。','',
        '重抽样覆盖10/20/40日区块、每档5000次，统计样本仍来自已见数据。成本使用既有完整账户，同参数但不同源码版本不自动借用费用结果。盘口排队、容量、冲击、延迟、跨标的与新消融未做。','',
        '## 机器入口','',
        '[manifest.json](manifest.json)锁定原始输入、代码和结果；[assessment.json](assessment.json)给出解释与缺口；[decision.json](decision.json)保持待用户决策。','',
        '复算使用项目既有.venv；从仓库根执行src/build.py对应的相对路径，build输出必须是.tmp下的新目录。先执行tests，再build或validate。原实验只读，平台未改。','',
        '下一步：用户审阅完整多维比较，选择具体配置晋升、要求补证或暂不晋升。第一层不自动取得候选资格。']
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('build');p.add_argument('--output',required=True,type=Path)
    p=sub.add_parser('validate');p.add_argument('--package',required=True,type=Path)
    args=parser.parse_args()
    if args.command=='build':build(args.output.resolve())
    else:validate(args.package.resolve())
