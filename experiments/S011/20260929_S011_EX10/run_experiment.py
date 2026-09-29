"""Preflight, then one formal run; preserve failures and receipts."""
from pathlib import Path
import json
import shutil
from uuid import uuid4
from experiment import PREDECESSORS
from czsc_trader.research_tools import create_formal_experiment_context,execute_experiment,preflight_experiment
from research_experiment import ExperimentResources,ExperimentWorkspace,load_experiment,load_experiment_input

def main():
    root=Path(__file__).resolve().parent; repo=root.parents[2]
    for name in ('artifacts','03_execution.md','04_conclusion.md','experiment_manifest.json'):
        if (root/name).exists():raise FileExistsError(f'immutable output exists: {name}')
    loaded=load_experiment(root)
    predecessors=tuple(load_experiment_input(root.parent/ex/'artifacts',expected_receipt_sha256=sha) for ex,sha in PREDECESSORS.items())
    resources=ExperimentResources(max_workers=1,random_seed=loaded.definition.random_seed)
    check=preflight_experiment(loaded,resources=resources,predecessors=predecessors);check.require_pass()
    print(json.dumps({'preflight':check.to_dict()},ensure_ascii=False),flush=True)
    work=ExperimentWorkspace(repo/'.tmp/research-experiments'/uuid4().hex/loaded.definition.experiment_id,repo)
    context=create_formal_experiment_context(loaded.definition,repository_root=repo,workspace=work,resources=resources,predecessors=predecessors)
    try: result=execute_experiment(loaded,context)
    except Exception as exc:
        shutil.copytree(work.root,root/'artifacts')
        (root/'03_execution.md').write_text(f'# EX10 执行\n\nTECHNICAL_FAILURE: {type(exc).__name__}: {exc}\n',encoding='utf-8')
        raise
    if result.receipt is None:raise RuntimeError('receipt missing')
    shutil.copytree(work.root,root/'artifacts')
    (root/'03_execution.md').write_text(f'# S011 EX10 执行\n\nSchema v3 preflight 与合成检查通过。正式执行完成。\n\nReceipt: `{result.receipt.sha256}`；状态：`{result.outcome.value}`。这只确认统一证据普查完成，组件尚需职责评审。\n',encoding='utf-8')
    print(json.dumps({'receipt':result.receipt.sha256,'facts':dict(result.facts)},ensure_ascii=False))

if __name__=='__main__':main()
