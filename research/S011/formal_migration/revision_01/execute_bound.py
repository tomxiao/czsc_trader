"""Run the bound EX29 implementation in the mandatory repository .tmp workspace."""
from datetime import timedelta
import json
from pathlib import Path
import shutil
import traceback
from dataflows import LocalCacheConfig
from research_experiment import load_experiment, load_experiment_input, ExperimentResources, ExperimentWorkspace
from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive

REPO=Path(__file__).resolve().parents[4]
ROOT=REPO/'experiments/S011/20261001_S011_EX29'
loaded=load_experiment(ROOT)
inputs=json.loads((ROOT/'inputs.json').read_text(encoding='utf-8'))
workspace_root=REPO/'.tmp/s011-formal-migration/EX29-execution'
assert not workspace_root.exists() and not (ROOT/'artifacts').exists(), 'execution already exists'
previous=tuple(load_experiment_input(ROOT.parent/ex/'artifacts',expected_receipt_sha256=digest)
    for ex,digest in inputs['predecessors'].items())
workspace=ExperimentWorkspace(workspace_root,REPO)
context=create_formal_experiment_context(loaded.definition,repository_root=REPO,
    resources=ExperimentResources(1,20261001),workspace=workspace,predecessors=previous,
    cache=LocalCacheConfig(REPO/'.tmp/s011-formal-migration/cache','S011-20260928-migration-v1',timedelta(days=1)))
result=None
failure=None
try:
    result=execute_experiment(loaded,context)
except Exception:
    failure=traceback.format_exc()
    workspace.path('technical_failure.txt').write_text(failure,encoding='utf-8',newline='\n')
shutil.copytree(workspace.root,ROOT/'artifacts')
status='TECHNICAL_FAILURE' if failure else 'COMPLETE'
(ROOT/'03_execution.md').write_text(f'# EX29 执行\n\n状态：`{status}`。启动器为../../../research/S011/formal_migration/revision_01/execute_bound.py。\n\n原run_experiment.py在构造工作区时被.tmp路径契约拒绝，当时尚未进入execute_experiment且没有账户执行；36份登记已完成，完整保留其来源。当前启动器通过.tmp工作区执行同一绑定实现，结束后复制封存。\n',encoding='utf-8',newline='\n')
(ROOT/'04_conclusion.md').write_text('# EX29 结论\n\n'+('技术失败并停止；见artifacts/technical_failure.txt。' if failure else
    '135份账户五张账本对账通过。此次为身份迁移，不增加独立证据。')+'\n',encoding='utf-8',newline='\n')
build_experiment_manifest(ROOT,dict(experiment_id=ROOT.name,strategy_id='S011',credential_id='SGC-S011-001',status=status,
    experiment_type='s011_formal_delivery_migration',symbol='159326.SZ',development_cutoff='2026-09-28',
    development_only=True,promotion_allowed=False,rex_receipt_sha256=None if result is None else result.receipt.sha256))
validate_experiment_archive(ROOT)
if failure:
    raise RuntimeError(failure)
print(json.dumps({'status':status,'receipt':result.receipt.sha256}),flush=True)
