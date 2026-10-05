from dataclasses import asdict
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
from dataflows import DataSpace
from research_experiment import ExperimentResources, ExperimentWorkspace, experiment_source_sha256, load_experiment, load_experiment_input
from czsc_trader.application import RepositoryContext, PredecessorEvidence, preflight_experiment_archive
from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment

def main():
    root=Path.cwd();exp=Path(__file__).resolve().parent;eid=exp.name
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    sources=('experiment.py', 's012_search_worker.py', 's012_accelerator.py', 's012_bound_model.py', 'managed_market.py', 'strategy_runtime/resources/features.csv', 'gate.json', 'proofs/real_comparison.json', 'proofs/synthetic_comparison.json')
    write(exp/'experiment_binding.json',{'schema_version':3,'module':'experiment','qualname':'Experiment','source_files':sources,
        'source_sha256':experiment_source_sha256(exp,sources),'dependencies':[{'name':p,'version':version(p)} for p in ('numpy','pandas','optuna')]})
    loaded=load_experiment(exp)
    predecessors=[];evidence=[]
    for old in loaded.definition.protocol.predecessor_experiment_ids:
        path=exp.parent/old/'artifacts/rex'
        digest=json.loads((path/'execution_receipt.json').read_text(encoding='utf-8'))['receipt_sha256']
        predecessors.append(load_experiment_input(path,expected_receipt_sha256=digest));evidence.append(PredecessorEvidence(path,digest))
    workers=4
    check=preflight_experiment_archive(RepositoryContext.discover(root),exp,max_workers=workers,predecessors=tuple(evidence))
    write(exp/'artifacts/preflight.json',asdict(check));print('PREFLIGHT',check.status,flush=True)
    if check.status=='FAIL':raise ValueError('preflight failed')
    ctx=create_formal_experiment_context(loaded.definition,repository_root=root,data_space=DataSpace(Path('data/backtest')),
        resources=ExperimentResources(workers,loaded.definition.random_seed,1),workspace=ExperimentWorkspace(root/f'.tmp/s012-stage3-20261005/{eid}/execution',root),predecessors=tuple(predecessors))
    try:
        result=execute_experiment(loaded,ctx)
        print('EXECUTION',result.outcome.value,dict(result.facts),flush=True)
    finally:
        shutil.copytree(ctx.workspace.root,exp/'artifacts/rex',dirs_exist_ok=True)

if __name__=='__main__':main()
