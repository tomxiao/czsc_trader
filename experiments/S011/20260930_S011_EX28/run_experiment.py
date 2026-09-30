"""Preflight then one immutable execution; all temporary work stays under .tmp."""
from pathlib import Path
from uuid import uuid4
import argparse
import json
import os
import shutil
import traceback
from dotenv import load_dotenv
from dataflows import Dataflows
from strategy_runtime import StrategyCandidate
from research_experiment import ExperimentResources,ExperimentWorkspace,load_experiment,load_experiment_input
from czsc_trader.research_tools import create_experiment_context,preflight_experiment,execute_experiment
from czsc_trader.experiment_archive import build_experiment_manifest,validate_experiment_archive
from experiment import ID,SEED,BUDGET,PREDECESSORS,CUTOFF,WORKERS,POINTS,RUNTIME,payload
from engine import Dispatcher

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preflight-only',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parent;repo=root.parents[2]
    for name in ('artifacts','03_execution.md','04_conclusion.md','experiment_manifest.json'):
        if (root/name).exists():raise FileExistsError('immutable execution already exists: '+name)
    loaded=load_experiment(root)
    prior=tuple(load_experiment_input(root.parent/ex/'artifacts',expected_receipt_sha256=sha) for ex,sha in PREDECESSORS.items())
    resources=ExperimentResources(max_workers=WORKERS,random_seed=SEED,max_evaluations=BUDGET)
    preflight=preflight_experiment(loaded,resources=resources,predecessors=prior);preflight.require_pass()
    print(json.dumps(preflight.to_dict()),flush=True)
    dispatcher=Dispatcher(WORKERS)
    try:
        process_precheck=dispatcher.precheck(StrategyCandidate('S011','EX28SYN',payload(POINTS[0]),RUNTIME))
        print(json.dumps(process_precheck),flush=True)
        if args.preflight_only:return
        load_dotenv(repo/'.env',override=False)
        # Workers already exist; load .env explicitly inside worker without exposing values.
        workspace=ExperimentWorkspace(repo/'.tmp/research-experiments'/uuid4().hex/ID,repo)
        context=create_experiment_context(loaded.definition,repository_root=repo,dataflows=Dataflows(),resources=resources,
            workspace=workspace,real_returns=True,predecessors=prior,evaluator=dispatcher)
        result=None;failure=None
        try:result=execute_experiment(loaded,context)
        except Exception:
            failure=traceback.format_exc();workspace.path('technical_failure.txt').write_text(failure,encoding='utf-8')
        workspace.path('process_precheck.json').write_text(json.dumps(process_precheck,indent=2)+'\n',encoding='utf-8')
        workspace.path('worker_execution.json').write_text(json.dumps(dispatcher.records,indent=2)+'\n',encoding='utf-8')
        shutil.copytree(workspace.root,root/'artifacts')
        receipt=None if result is None or result.receipt is None else result.receipt.sha256
        facts={} if result is None else result.to_dict()['facts'];status='TECHNICAL_FAILURE' if failure else 'COMPLETE'
        (root/'03_execution.md').write_text('# EX28执行\n\n状态：`'+status+'`。冻结源码后preflight通过，Optuna内存Study、8个spawn进程、每进程单原生线程。\n\nreceipt：`'+str(receipt)+'`。\n\n'+json.dumps(facts,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
        (root/'04_conclusion.md').write_text('# EX28结论\n\n'+('技术失败，已完成路径保留，后继实验承接。' if failure else '预登记扰动账户已完成，逐中心解释由阶段四补充决策包承接。')+'\n\n已见开发池证据；无新增经济硬门，不批准候选或冻结/生产操作。\n',encoding='utf-8',newline='\n')
        build_experiment_manifest(root,{'experiment_id':ID,'strategy_id':'S011','credential_id':'SGC-S011-001','status':status,
            'experiment_type':'s011_stage4_balanced_parameter_perturbation','symbol':'159326.SZ','development_cutoff':CUTOFF.isoformat(),
            'decision':facts.get('decision',status),'rex_receipt_sha256':receipt,'development_only':True,'promotion_allowed':False})
        validate_experiment_archive(root)
        if failure:raise RuntimeError(failure)
        print(json.dumps({'status':status,'receipt':receipt,'facts':facts}),flush=True)
    finally:dispatcher.close()

if __name__=='__main__':main()
