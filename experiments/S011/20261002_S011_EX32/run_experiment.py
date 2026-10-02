"""Preflight and execute once; publish deliveries before sealing the archive."""
from datetime import timedelta
import json
from pathlib import Path
import shutil
import traceback

from dataflows import Dataflows, LocalCacheConfig, DataRequest
from research_experiment import load_experiment, experiment_source_sha256, ExperimentResources, ExperimentWorkspace
from czsc_trader.research_tools import preflight_experiment, create_formal_experiment_context, execute_experiment
from czsc_trader.experiment_archive import build_experiment_manifest
from experiment import ROOT, REPO, ID, REQUESTS, Experiment

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')

def main():
    assert not (ROOT/'artifacts').exists(), 'execution already preserved'
    names=('experiment.py','component_methods.py','run_experiment.py','historical_sources.json','01_goal.md','02_design.md')
    binding=dict(schema_version=3,module='experiment',qualname='Experiment',source_files=list(names),
        source_sha256=experiment_source_sha256(ROOT,names),dependencies=[{'name':x.name,'version':x.version} for x in Experiment().definition.dependencies])
    path=ROOT/'experiment_binding.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==binding
    else:
        write(path,binding)
    loaded=load_experiment(ROOT)
    resources=ExperimentResources(1,2026092911)
    cache=LocalCacheConfig(REPO/'.tmp/s011-regeneration/cache','S011-20260928-regeneration-v1',timedelta(days=1))
    requests=tuple(DataRequest(dataset,symbol,start,'2026-09-28',None,frequency) for _,dataset,symbol,start,frequency in REQUESTS)
    report=preflight_experiment(loaded,resources=resources,dataflows=Dataflows(env_file=REPO/'.env',cache=cache),data_requests=requests)
    write(ROOT/'preflight.json',report.to_dict())
    print(json.dumps(report.to_dict()),flush=True)
    report.require_pass()
    workspace_root=REPO/'.tmp/s011-regeneration/EX32-execution'
    assert not workspace_root.exists()
    workspace=ExperimentWorkspace(workspace_root,REPO)
    context=create_formal_experiment_context(loaded.definition,repository_root=REPO,resources=resources,workspace=workspace,cache=cache)
    failure=None
    try:
        result=execute_experiment(loaded,context)
    except Exception:
        failure=traceback.format_exc()
        workspace.path('technical_failure.txt').write_text(failure,encoding='utf-8',newline='\n')
    shutil.copytree(workspace.root,ROOT/'artifacts')
    status='TECHNICAL_FAILURE' if failure else 'COMPLETE'
    (ROOT/'03_execution.md').write_text(f'# EX32 执行\n\n状态：{status}。当前REX受管执行及DFLS原始数据见artifacts，预检见preflight.json。\n',encoding='utf-8',newline='\n')
    conclusion='技术失败，保留原执行并停止。' if failure else '9个定义、7种标签和63条角色检验复算通过，189折及留月统计与旧证据一致。旧广泛筛选仅作历史附件；开发池选择偏差与旧清单引用缺口保留。阶段交付完成后再封存。'
    (ROOT/'04_conclusion.md').write_text('# EX32 结论\n\n'+conclusion+'\n',encoding='utf-8',newline='\n')
    if failure:
        build_experiment_manifest(ROOT,dict(experiment_id=ID,strategy_id='S011',credential_id='SGC-S011-001',status=status))
        raise RuntimeError(failure)
    print(json.dumps({'status':status,'receipt':result.receipt.sha256}),flush=True)

if __name__=='__main__':
    main()
