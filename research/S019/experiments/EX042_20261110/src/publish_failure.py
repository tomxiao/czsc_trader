"""Archive EX042's technical failure without replay, stage delivery or budget mutation."""
import argparse
import ast
from hashlib import sha256
import inspect
import json
from pathlib import Path
from time import perf_counter

from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_experiment
from dataflows import ProviderConfig
from strategy_runtime import equity_source_hash
from strategy_runtime.equity_replay import StateRecord, StrategyStateSchema, StateField, StateValueType

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OUT = WORK/'others'


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


def prepare():
    assert not (WORK/'report_ref.json').exists()
    manifest = read(WORK/'protocols/run_manifest.json')
    results = read(OUT/'results.json')
    attempts = read(OUT/'attempts.json')
    specs = read(WORK/'protocols/specs.json')['specs']
    assert results['manifest'] == manifest and results['status'] == 'STOPPED' and not results['accounts']
    assert len(attempts) == 2 and all(a['status']=='STOPPED' for a in attempts)
    assert all(a['equity_statistics']['candidate_runs']==a['equity_statistics']['benchmark_runs']==0 for a in attempts)
    assert sum(a['execution_stats']['unknown'] for a in attempts) == 8
    assert not results['replay_statistics_complete'] and results['rounds_debited_by_runner'] == 0
    assert len(specs) == 19 and not list(OUT.glob('*_account.json'))
    definitions = [read(OUT/f"{s['label']}_definition.json") for s in specs]
    assert all(x['state_schema']==definitions[0]['state_schema'] for x in definitions)
    assert all(x['source_sha256']==manifest['source_sha256']==equity_source_hash(WORK/'src',tuple(x['source_files'])) for x in definitions)
    tree = ast.parse((WORK/'src/strategy.py').read_text(encoding='utf-8'))
    emitted_sets = [sorted(pair.elts[0].value for pair in call.args[0].elts)
        for call in ast.walk(tree) if isinstance(call,ast.Call) and isinstance(call.func,ast.Name)
        and call.func.id=='StateRecord']
    fields = {'anchor':100.,'allocation':.3,'exiting':False,'high_water':100.,
        'entry_atr':2.,'risk_fraction':1.,'breach_count':0}
    assert emitted_sets and all(set(x)==set(fields) for x in emitted_sets)
    record = StateRecord(tuple(fields.items()))
    schema = StrategyStateSchema.from_dict(definitions[0]['state_schema'])
    try:
        schema.validate_record(record,scope='cycle')
    except ValueError as error:
        failure = str(error)
    else:
        raise AssertionError('Original state declaration unexpectedly accepted seven fields')
    assert failure == 'state fields differ from declared cycle schema'
    revised = StrategyStateSchema(schema.account_fields, schema.cycle_fields+(
        StateField('risk_fraction',StateValueType.FLOAT),StateField('breach_count',StateValueType.INT)))
    revised.validate_record(record,scope='cycle')
    archives = []
    for source, name in (
        ('.tmp/ex042_20261110-accounts/run.log','failure_pool_attempt1.md'),
        ('.tmp/ex042_20261110-accounts/recovery.log','failure_container_comparison.md'),
        ('.tmp/ex042_20261110-accounts/recovery_v2.log','failure_pool_attempt2.md'),
        ('.tmp/s019-stage2-resume/pool_worker_before.log','pool_smoke_before.md'),
        ('.tmp/s019-stage2-resume/pool_worker_after.log','pool_smoke_after.md')):
        path = ROOT/source
        text = path.read_text(encoding='utf-8-sig').replace(str(ROOT),' .').replace(ROOT.as_posix(),' .')
        dest = OUT/name
        dest.write_text(f"Source: `{source}`\n\nOriginal SHA256: `{digest(path)}`\n\n"
            "日志文本保留；仓库绝对路径规范为相对路径。\n\n```text\n"+text+"\n```\n",encoding='utf-8')
        archives.append({'source':source,'original_sha256':digest(path),
            'archive':dest.relative_to(WORK).as_posix(),'archive_sha256':digest(dest)})
    pool_source = ROOT/'.tmp/s019-stage2-resume/pool_worker_diagnostic.py'
    archived_pool_source = OUT/'pool_worker_diagnostic_source.txt'
    archived_pool_source.write_bytes(pool_source.read_bytes())
    binding_paths = [*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*')),
        *sorted(OUT.glob('*_definition.json')), OUT/'attempts.json', OUT/'attempts_v1.json',
        OUT/'results.json', OUT/'results_v1.json',archived_pool_source]
    platform_path = Path(inspect.getsourcefile(StrategyStateSchema))
    diagnosis = {'status':'REPRODUCED_STATE_SCHEMA_MISMATCH','experiment':WORK.name,
        'strategy_source_sha256':manifest['source_sha256'],'declared_cycle_fields':[x.key for x in schema.cycle_fields],
        'emitted_cycle_fields':sorted(fields),'missing_declarations':['risk_fraction','breach_count'],
        'original_contract_exception':failure,'in_memory_seven_field_validation':'PASS',
        'corrected_definition_written':False,'account_replays_in_diagnosis':0,
        'platform_validator':{'path':platform_path.relative_to(ROOT).as_posix(),'sha256':digest(platform_path)},
        'bindings':{p.relative_to(WORK).as_posix():digest(p) for p in binding_paths if p.is_file()},
        'logs':archives,'execution_attempts':2,'pre_compute_container_comparison_failures':1,
        'unknown_compute_tasks':8,'successful_candidate_runs':0,'successful_benchmark_runs':0,
        'published_account_count':0,'rounds_debited':0,'remaining_authorized_rounds':6,
        'failed_candidate_ids':[f'C{i:04}' for i in range(622,641)],
        'next_experiment':'EX043_20261110','next_candidate_ids':[f'C{i:04}' for i in range(641,660)],
        'inference':'The declared schema deterministically rejects the strategy state. Pool records expose BrokenProcessPool/UNKNOWN; original worker traceback was not delivered.',
        'source_contract_unchanged':True}
    save(OUT/'technical_failure_diagnosis.json',diagnosis)
    report = f'''# EX042：退出机制对照的技术失败收口

Status: FAILED；RSCH；技术失败，研究轮扣减0。

本实验计划19个退出机制配置，尚未形成有效策略账户或买持账户。C0622—C0640的原定义、策略源码与执行记录保留，经济结论尚未形成。既有10轮额度仍已用4轮、剩6轮；本次批准的6轮完整保留。

## 执行事实

|执行事件|账户计算|记录结果|预算影响|
|---|---|---|---|
|第一次池执行|提交4项任务|4 UNKNOWN；策略0、买持0|0研究轮|
|第一次恢复的容器比较|在results.manifest相等断言处停止|tuple/list表示差异，尚未启动新账户计算|0研究轮|
|规范化后第二次池执行|提交4项任务|4 UNKNOWN；策略0、买持0|0研究轮|

两次真实池执行均返回BrokenProcessPool，合计8项UNKNOWN按原状态留存。已记录成功回放为0；统计完整性为False。两段执行记录累计{results['elapsed_seconds']:.6f}秒，容器比较及后续诊断另计。资源均为12账户进程、各1原生线程。详见[执行记录](others/attempts.json)、[原始结果](others/results.json)、[第一次池执行](others/failure_pool_attempt1.md)、[容器比较失败](others/failure_container_comparison.md)及[第二次池执行](others/failure_pool_attempt2.md)。

## 已复现的阻断原因

策略返回7个周期状态字段，原定义从C0355继承5字段声明，遗漏`risk_fraction`与`breach_count`。独立调用公开`StrategyStateSchema.validate_record`，原声明确定报出`state fields differ from declared cycle schema`。在内存中补充float风险乘数及int连续穿越计数后，同一7字段记录验证PASS；该检查新增账户0，原实验声明与源码保持原值。

策略在入场信号成立时就会返回完整周期状态，此处已构成账户推进的确定阻断。两次池日志暴露的是BrokenProcessPool/UNKNOWN，原工作器异常栈未透出，具体映射保留这一证据限制。[EX005历史记录](../EX005_20261110/report.md)已记载策略ReplayFailure在并行执行中的未知结果呈现，供平台问题后续追踪。两组独立12进程依赖与数值运算检查均完成，见[检查一](others/pool_smoke_before.md)、[检查二](others/pool_smoke_after.md)及[检查源码](others/pool_worker_diagnostic_source.txt)。

源、19个定义、请求清单、两版runner及日志的哈希绑定与公开接口复现结果见[技术诊断](others/technical_failure_diagnosis.json)。此前容器规范化恢复仅调整表示和诊断记录，其原件及合同不变核对见[恢复修订](protocols/technical_recovery_amendment.json)。

## 修正路线与研究目标

按主方决定，将同一19配置机制方案承接至EX043，使用新身份C0641—C0659及完整7字段声明；策略金融逻辑、参数、原数据样本和费用合同保持。新实验先核对状态声明与实际返回，再以三条hard控制执行完整经济parity，验证相对C0355及其ATR上下5%账户的经济一致性，通过后开展机制对照。EX042在此关闭，成功机制实验仍待新实验完成。

原目标NAR≥55%、Calmar≥5、MDD与双频率门槛，以及正式邻域通过率≥80%均保持。本次只发布技术失败实验报告，阶段交付和研究额度均保持原状态。原方案见[机制计划](protocols/plan.md)、[19配置](protocols/specs.json)及[准备请求](protocols/prepared_request_manifest.json)。
'''
    (WORK/'report.md').write_text(report,encoding='utf-8')
    print('FAILURE_REPORT_READY',digest(WORK/'report.md'),flush=True)


def publish():
    assert not (WORK/'report_ref.json').exists(), 'Inspect existing publication before retry'
    assert not (OUT/'failure_publication.json').exists()
    diagnosis = read(OUT/'technical_failure_diagnosis.json')
    assert diagnosis['status']=='REPRODUCED_STATE_SCHEMA_MISMATCH' and diagnosis['rounds_debited']==0
    for name, expected in diagnosis['bindings'].items():
        assert digest(WORK/name)==expected,name
    for item in diagnosis['logs']:
        assert digest(WORK/item['archive'])==item['archive_sha256']
    assert not read(OUT/'results.json')['accounts']
    started = perf_counter()
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo,d.ResearchBatchRef('S019'),providers=ProviderConfig(bindings={},equity_bindings={}))
    exp = d.ExperimentRef('S019',WORK.name)
    paths = [*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*')),
        *sorted(OUT.glob('*.json')),*sorted(OUT.glob('*.md')),*sorted(OUT.glob('*.txt'))]
    refs = []
    for i,path in enumerate(paths):
        if not path.is_file():
            continue
        ext = path.suffix[1:]
        assert ext in {'py','json','md','txt'}
        refs.append(publish_evidence(ctx,d.MaterialEvidenceWrite(exp,f'failure-{i:03}-{path.stem}',path.read_bytes(),
            {'py':'text/x-python','json':'application/json','md':'text/markdown','txt':'text/plain'}[ext],ext)))
    report = publish_evidence(ctx,d.ExperimentReportWrite(exp,digest(WORK/'report.md'),d.ExperimentOutcome.FAILED,tuple(refs)))
    validation = validate_experiment(repo,d.ExperimentValidationRequest(exp,d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    save(OUT/'failure_publication.json',{'report':report.to_dict(),'validation':validation.to_dict(),
        'outcome':'FAILED','seconds':perf_counter()-started,'new_account_replays':0,'rounds_debited':0,
        'research_intent_mutation':'NONE','stage_delivery_mutation':'NONE'})
    print('FAILURE_REPORT_PUBLISHED',report.sha256,validation.status.value,flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('prepare','publish'))
    args = parser.parse_args()
    {'prepare':prepare,'publish':publish}[args.action]()
