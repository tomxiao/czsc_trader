"""Owner-invoked formal driver; reuse witness prepared assets in data/backtest.

The witness's PreparedDataRef belongs to that space. Research ownership S012
does not relocate the prepared assets. This preparation task does not run it.
"""
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
        print('SYNTHETIC_PRECHECK',len(result.checks),flush=True)
        return
    require_path=root/'experiments/S012'/loaded.definition.experiment_id
    if exp!=require_path:
        raise ValueError('formal execution requires owner-allocated S012 experiment location')
    scope=json.loads((exp/'scope.json').read_text(encoding='utf-8'))
    prior=root/'experiments/S012'/scope['witness_experiment_id']/'artifacts/rex'
    receipt_sha=scope['witness_receipt_sha256']
    predecessor=load_experiment_input(prior,expected_receipt_sha256=receipt_sha)
    maximum=max(1,(os.cpu_count() or 1)//2)
    config=json.loads((exp/'search_config.json').read_text(encoding='utf-8'))
    workers=min(maximum,config['worker_cap'] or maximum)
    if config['worker_cap'] is not None and config['worker_cap']>maximum:
        raise ValueError('worker_cap exceeds half CPU')
    check=preflight_experiment_archive(RepositoryContext.discover(root),exp,max_workers=workers,
        predecessors=(PredecessorEvidence(prior,receipt_sha),))
    target=exp/'artifacts/preflight.json';target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(asdict(check),ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    if check.status!='PASS':raise ValueError('formal preflight not PASS')
    context=create_formal_experiment_context(loaded.definition,repository_root=root,
        data_space=DataSpace(Path('data/backtest')),
        resources=ExperimentResources(workers,config['seed'],1),
        workspace=ExperimentWorkspace(root/f'.tmp/s012-stage3-native-20261006/{loaded.definition.experiment_id}/execution',root),
        predecessors=(predecessor,))
    try:
        result=execute_experiment(loaded,context)
        print('FORMAL_SCREENING',result.outcome.value,dict(result.facts),flush=True)
    finally:
        shutil.copytree(context.workspace.root,exp/'artifacts/rex',dirs_exist_ok=True)

if __name__=='__main__':main()
