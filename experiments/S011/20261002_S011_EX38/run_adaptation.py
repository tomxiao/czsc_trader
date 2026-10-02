"""Run the approved fixed technical adaptation using current public APIs."""
from hashlib import sha256
import json
from pathlib import Path
import shutil

from dataflows import Dataflows
from research_experiment import load_experiment, experiment_source_sha256, ExperimentResources, ExperimentWorkspace
from czsc_trader.research_tools import preflight_experiment, create_experiment_context, execute_experiment
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def main():
    assert not (ROOT / 'experiment_manifest.json').exists(), 'Already sealed'
    inputs = json.loads((ROOT / 'inputs.json').read_text(encoding='utf-8'))
    names = ('experiment.py', 'run_adaptation.py', 'inputs.json', '01_goal.md', '02_design.md',
             *tuple(sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'runtime').rglob('*.py'))))
    binding = dict(schema_version=3, module='experiment', qualname='Experiment', source_files=list(names),
                   source_sha256=experiment_source_sha256(ROOT, names), dependencies=inputs['dependencies'])
    binding_path = ROOT / 'experiment_binding.json'
    if binding_path.exists():
        assert json.loads(binding_path.read_text(encoding='utf-8')) == binding, 'Bound source changed'
    else:
        write(binding_path, binding)
    loaded = load_experiment(ROOT)
    resources = ExperimentResources(1, 38)
    report = preflight_experiment(loaded, resources=resources)
    write(ROOT / 'preflight.json', report.to_dict())
    print(json.dumps(report.to_dict(), ensure_ascii=False), flush=True)
    report.require_pass()
    workspace = ExperimentWorkspace(REPO / '.tmp/s011-candidate-adaptation/execution', REPO)
    assert not workspace.path('execution_receipt.json').exists(), 'Execution already completed'
    context = create_experiment_context(loaded.definition, repository_root=REPO, dataflows=Dataflows({}),
                                        resources=resources, workspace=workspace)
    result = execute_experiment(loaded, context)
    assert not result.receipt.trace.evaluations and not result.receipt.trace.data_requests
    shutil.copytree(workspace.root, ROOT / 'artifacts')
    index = json.loads(workspace.path('candidates.json').read_text(encoding='utf-8'))
    for row in index['candidates']:
        row.pop('historical_derivation')
    write(ROOT / 'current_candidates.json', index)
    write(ROOT / 'technical_receipt.json', {**result.receipt.to_dict(), 'receipt_sha256': result.receipt.sha256})
    (ROOT / '03_execution.md').write_text(
        '# EX38 技术适配执行\n\n612 个固定候选经 `register_candidate` 登记，并经 `load_candidate` 与 `StrategyRuntime.identify` 逐个校验。'
        '36 个中心、576 个扰动；2 份源码通过 AST 差异约束，参数保持不变。预检使用每候选 40 行合成信号；未读取行情、未搜索参数、未执行真实市场评价。\n',
        encoding='utf-8', newline='\n')
    (ROOT / '04_conclusion.md').write_text(
        '# EX38 技术适配结论\n\n技术适配完成。当前入口为 [候选索引](current_candidates.json)，全部 `NOT_EVALUATED`。'
        '`C0621` 对应历史选择 621；历史 EX37 报告仍保留原编号和内容哈希。技术预检通过不代表回测表现、稳健性或冻结资格成立。\n\n'
        '576 个扰动的历史父子关系与原始证据引用保留在 [输入契约](inputs.json)。当前登记的 `derivation` 为空；'
        '索引标为 `PENDING_CURRENT_PARENT_EVALUATION`，须在新父候选真实评价后建立当前认证关系。\n',
        encoding='utf-8', newline='\n')
    build_experiment_manifest(ROOT, dict(experiment_id=ROOT.name, strategy_id='S011', symbol='159326.SZ',
                                         status='TECHNICAL_ADAPTATION_COMPLETE', development_cutoff='2026-09-28'))
    validate_experiment_archive(ROOT)
    print(json.dumps({'status':'TECHNICAL_ADAPTATION_COMPLETE','candidates':612,'receipt':result.receipt.sha256}),flush=True)


if __name__ == '__main__':
    main()
