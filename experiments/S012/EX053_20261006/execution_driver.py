"""Owner-invoked immutable formal driver; no binding rewrite or experiment allocation."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import sys

from dataflows import DataSpace
from research_experiment import ExperimentResources, ExperimentWorkspace, load_experiment, load_experiment_input
from czsc_trader.application import RepositoryContext, PredecessorEvidence, preflight_experiment_archive
from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment

def main():
    root=Path.cwd().resolve();exp=Path(__file__).resolve().parent
    loaded=load_experiment(exp)
    if '--synthetic-only' in sys.argv:
        result=loaded.implementation.synthetic_precheck()
        print('SYNTHETIC_POST52_FOCUSED',len(result.checks),flush=True)
        return
    if exp!=root/'experiments/S012'/loaded.definition.experiment_id:
        raise ValueError('formal execution requires owner-allocated S012 experiment location')
    config=json.loads((exp/'full_config.json').read_text(encoding='utf-8'))
    selection=json.loads((exp/'witness_options.json').read_text(encoding='utf-8'))
    receipts=selection['predecessor_receipts']
    workers=config['worker_cap'];maximum=min(8,max(1,(os.cpu_count() or 1)//2))
    if type(workers) is not int or not 1<=workers<=maximum:raise ValueError('invalid resource cap')
    predecessors=[];evidence=[]
    for eid in loaded.definition.protocol.predecessor_experiment_ids:
        path=root/'experiments/S012'/eid/'artifacts/rex';expected=receipts[eid]
        predecessors.append(load_experiment_input(path,expected_receipt_sha256=expected))
        evidence.append(PredecessorEvidence(path,expected))
    check=preflight_experiment_archive(RepositoryContext.discover(root),exp,max_workers=workers,predecessors=tuple(evidence))
    target=exp/'artifacts/preflight.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(asdict(check),ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    if check.status!='PASS':raise ValueError('selected FULL formal preflight not PASS')
    context=create_formal_experiment_context(loaded.definition,repository_root=root,
        data_space=DataSpace(Path('data/research/S012')),resources=ExperimentResources(workers,config['seed'],1),
        workspace=ExperimentWorkspace(root/f'.tmp/s012-stage3-native-20261006/{loaded.definition.experiment_id}/execution',root),
        predecessors=tuple(predecessors))
    try:
        result=execute_experiment(loaded,context)
        print('FORMAL_POST52_FULL',result.outcome.value,dict(result.facts),flush=True)
    finally:
        shutil.copytree(context.workspace.root,exp/'artifacts/rex',dirs_exist_ok=True)

if __name__=='__main__':main()
