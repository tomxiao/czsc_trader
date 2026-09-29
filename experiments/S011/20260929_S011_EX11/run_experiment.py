"""Single immutable execution after preflight."""
from pathlib import Path
from uuid import uuid4
import json
import shutil
from experiment import PREDECESSORS
from research_experiment import ExperimentResources,ExperimentWorkspace,load_experiment,load_experiment_input
from czsc_trader.research_tools import create_formal_experiment_context,preflight_experiment,execute_experiment

def main():
    root=Path(__file__).resolve().parent;repo=root.parents[2]
    for name in ('artifacts','03_execution.md','04_conclusion.md','experiment_manifest.json'):
        if (root/name).exists():raise FileExistsError('immutable output exists: '+name)
    loaded=load_experiment(root)
    prior=tuple(load_experiment_input(root.parent/ex/'artifacts',expected_receipt_sha256=sha) for ex,sha in PREDECESSORS.items())
    resources=ExperimentResources(max_workers=1,random_seed=loaded.definition.random_seed)
    report=preflight_experiment(loaded,resources=resources,predecessors=prior);report.require_pass()
    print(json.dumps({'preflight':report.to_dict()},ensure_ascii=False),flush=True)
    workspace=ExperimentWorkspace(repo/'.tmp/research-experiments'/uuid4().hex/loaded.definition.experiment_id,repo)
    context=create_formal_experiment_context(loaded.definition,repository_root=repo,workspace=workspace,resources=resources,predecessors=prior)
    try:result=execute_experiment(loaded,context)
    except Exception as exc:
        shutil.copytree(workspace.root,root/'artifacts')
        (root/'03_execution.md').write_text(f'# EX11 执行\n\nTECHNICAL_FAILURE: {type(exc).__name__}: {exc}\n',encoding='utf-8')
        raise
    if result.receipt is None:raise RuntimeError('receipt missing')
    shutil.copytree(workspace.root,root/'artifacts')
    (root/'03_execution.md').write_text(f'# S011 EX11 执行\n\nSchema v3 preflight与合成检查通过。Receipt: `{result.receipt.sha256}`。状态：`{result.outcome.value}`，只确认职责审查证据计算完成；组件资格另由研究判断记录。\n',encoding='utf-8')
    print(json.dumps({'receipt':result.receipt.sha256,'facts':dict(result.facts)},ensure_ascii=False))

if __name__=='__main__':main()
