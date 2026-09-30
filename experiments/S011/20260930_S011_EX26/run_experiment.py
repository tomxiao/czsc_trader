"""One preregistered development execution; preserve any failed execution."""
from pathlib import Path
from uuid import uuid4
import json
import shutil
import traceback
import os
from dotenv import load_dotenv
from dataflows import Dataflows
from research_experiment import ExperimentResources,ExperimentWorkspace,load_experiment,load_experiment_input
from czsc_trader.research_tools import create_experiment_context,preflight_experiment,execute_experiment
from czsc_trader.experiment_archive import build_experiment_manifest,validate_experiment_archive
from experiment import ID,SEED,BUDGET,PREDECESSORS,CUTOFF,WORKERS


def main():
    root=Path(__file__).resolve().parent;repo=root.parents[2]
    for name in ('artifacts','03_execution.md','04_conclusion.md','experiment_manifest.json'):
        if (root/name).exists():raise FileExistsError('immutable execution already exists: '+name)
    loaded=load_experiment(root)
    prior=tuple(load_experiment_input(root.parent/ex/'artifacts',expected_receipt_sha256=sha) for ex,sha in PREDECESSORS.items())
    resources=ExperimentResources(max_workers=WORKERS,random_seed=SEED,max_evaluations=BUDGET)
    preflight=preflight_experiment(loaded,resources=resources,predecessors=prior);preflight.require_pass()
    print(json.dumps(preflight.to_dict(),ensure_ascii=False),flush=True)
    load_dotenv(repo/'.env', override=False)
    if not os.environ.get('TUSHARE_TOKEN'):raise RuntimeError('project Tushare credential unavailable')
    workspace=ExperimentWorkspace(repo/'.tmp/research-experiments'/uuid4().hex/ID,repo)
    context=create_experiment_context(loaded.definition,repository_root=repo,dataflows=Dataflows(),
        resources=resources,workspace=workspace,real_returns=True,predecessors=prior)
    result=None;failure=None
    try:result=execute_experiment(loaded,context)
    except Exception:
        failure=traceback.format_exc()
        workspace.path('technical_failure.txt').write_text(failure,encoding='utf-8')
    shutil.copytree(workspace.root,root/'artifacts')
    receipt=None if result is None or result.receipt is None else result.receipt.sha256
    facts={} if result is None else dict(result.facts)
    status='TECHNICAL_FAILURE' if failure else 'COMPLETE'
    (root/'03_execution.md').write_text('# EX26执行\n\n'+
        f'状态：`{status}`。源码冻结后preflight全部通过，实际单进程、8评价线程、单原生线程，最多{BUDGET}个账户。\n\n'+
        f'REX模式DISCOVERY；receipt：`{receipt}`。\n\n'+
        ('技术失败见artifacts/technical_failure.txt；保留已完成路径，后继实验承接。\n' if failure else json.dumps(facts,ensure_ascii=False)+'\n'),encoding='utf-8')
    (root/'04_conclusion.md').write_text('# EX26结论\n\n'+
        ('技术失败，不能用于机制否定或候选晋级。\n' if failure else
         f'机器裁决：`{facts.get("decision")}`。完成{facts.get("evaluated",0)}条完整账户路径，合格{facts.get("qualified",0)}条。\n')+
        '\n这是已见开发池证据；不提供独立验证，不代表阶段四已完成，不创建阶段五候选或任何冻结/生产状态。\n',encoding='utf-8')
    build_experiment_manifest(root,{'experiment_id':ID,'strategy_id':'S011','credential_id':'SGC-S011-001',
        'status':status,'experiment_type':'s011_stage4_development_diagnostics','symbol':'159326.SZ',
        'development_cutoff':CUTOFF.isoformat(),'decision':facts.get('decision',status),'rex_receipt_sha256':receipt,
        'development_only':True,'promotion_allowed':False})
    validate_experiment_archive(root)
    if failure:raise RuntimeError(failure)
    print(json.dumps({'status':status,'receipt':receipt,'facts':facts},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
