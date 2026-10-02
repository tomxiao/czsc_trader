"""Freeze, preflight and run once; preserve failed execution without retry."""
from datetime import timedelta
from hashlib import sha256
import argparse
import json
from pathlib import Path
import traceback
import shutil

from dataflows import Dataflows, LocalCacheConfig, DataRequest, Dataset
from research_experiment import (load_experiment, load_experiment_input, experiment_source_sha256,
    ExperimentResources, ExperimentWorkspace)
from strategy_manager import CandidateEvidence, CandidateRegistrationOrigin
from czsc_trader.application import RepositoryContext, register_candidate, CandidateRegistrationRequest, load_candidate
from czsc_trader.research_tools import preflight_experiment, create_formal_experiment_context, execute_experiment
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from experiment import ROOT, REPO, ID, INPUTS, DEPS, candidate

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args=parser.parse_args()
    assert not (ROOT/'artifacts').exists(), 'immutable execution already exists'
    names=('experiment.py','run_experiment.py','inputs.json','01_goal.md','02_design.md',
        *(p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'runtime').rglob('*.py'))))
    binding=dict(schema_version=3,module='experiment',qualname='Experiment',source_files=list(names),
        source_sha256=experiment_source_sha256(ROOT,names),dependencies=INPUTS['dependencies'])
    path=ROOT/'experiment_binding.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==binding, 'bound source changed'
    else:
        write(path,binding)
    loaded=load_experiment(ROOT)
    previous=tuple(load_experiment_input(ROOT.parent/ex/'artifacts',expected_receipt_sha256=digest)
        for ex,digest in INPUTS['predecessors'].items())
    resources=ExperimentResources(1,20261001)
    cache=LocalCacheConfig(REPO/'.tmp/s011-regeneration/cache','S011-20260928-regeneration-v1',timedelta(days=1))
    flows=Dataflows(env_file=REPO/'.env',cache=cache)
    requests=tuple(DataRequest(dataset,symbol,start,'2026-09-28','2026-09-28',frequency)
        for dataset,symbol,start,frequency in (
            (Dataset.ETF_OHLCV,'159326.SZ','2024-12-26','daily'),
            (Dataset.ETF_OHLCV,'159326.SZ','2024-12-26','30m'),
            (Dataset.ETF_UNADJUSTED_DAILY,'159326.SZ','2024-12-26','daily'),
            (Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000300.SH','2024-12-26','daily'),
            (Dataset.GLOBAL_INDEX_DAILY,'SPX','2024-12-16','daily'),
            (Dataset.TRADING_CALENDAR,'SSE','2025-02-06','daily')))
    report=preflight_experiment(loaded,resources=resources,predecessors=previous,dataflows=flows,data_requests=requests)
    write(ROOT/'preflight.json',report.to_dict())
    print(json.dumps(report.to_dict()),flush=True)
    report.require_pass()
    if not args.execute:
        return
    repository=RepositoryContext.discover(REPO)
    registrations=[]
    origin = CandidateRegistrationOrigin(ID, loaded.definition.sha256,
        sha256((ROOT/'experiment_binding.json').read_bytes()).hexdigest(),
        CandidateEvidence((ROOT/'preflight.json').relative_to(REPO).as_posix(),
            sha256((ROOT/'preflight.json').read_bytes()).hexdigest()))
    for spec in INPUTS['centers']:
        registered = register_candidate(repository, CandidateRegistrationRequest(candidate(spec), origin, DEPS))
        saved = load_candidate(repository, registered.key)
        assert saved.payload == candidate(spec).payload
        registrations.append(registered.to_dict())
    write(ROOT/'registrations.json',registrations)
    workspace_root=REPO/'.tmp/s011-regeneration/EX33-execution'
    assert not workspace_root.exists(), 'execution workspace already exists'
    workspace=ExperimentWorkspace(workspace_root,REPO)
    context=create_formal_experiment_context(loaded.definition,repository_root=REPO,resources=resources,
        workspace=workspace,predecessors=previous,cache=cache)
    failure=None
    result=None
    try:
        result=execute_experiment(loaded,context)
    except Exception:
        failure=traceback.format_exc()
        workspace.path('technical_failure.txt').write_text(failure,encoding='utf-8',newline='\n')
    shutil.copytree(workspace.root,ROOT/'artifacts')
    status='TECHNICAL_FAILURE' if failure else 'COMPLETE'
    (ROOT/'03_execution.md').write_text(f'# EX33 执行\n\n状态：`{status}`。单进程受管执行，预检和登记见本目录JSON。\n',encoding='utf-8',newline='\n')
    (ROOT/'04_conclusion.md').write_text('# EX33 结论\n\n'+('技术失败，已停止；查看artifacts/technical_failure.txt。不得重跑或覆盖。' if failure else
        '135份策略账户及135份限价基准账户的五张账本均与原证据等价。迁移提供当前身份与回执，不增加独立研究证据；阶段交付仍需正式组装和校验。')+'\n',encoding='utf-8',newline='\n')
    if failure:
        build_experiment_manifest(ROOT, dict(experiment_id=ID,strategy_id='S011',credential_id='SGC-S011-001',status=status))
        validate_experiment_archive(ROOT)
    if failure:
        raise RuntimeError(failure)
    print(json.dumps({'status':status,'receipt':result.receipt.sha256}),flush=True)

if __name__=='__main__':
    main()
