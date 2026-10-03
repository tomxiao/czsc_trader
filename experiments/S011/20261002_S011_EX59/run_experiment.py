"""Execute the fixed experiment and publish its current delivery."""
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
from dataflows import Dataflows, LocalCacheConfig
from research_experiment import (load_experiment, load_experiment_input, experiment_source_sha256, ExperimentResources, ExperimentWorkspace)
from strategy_manager import CandidateEvidence, CandidateRegistrationOrigin
from strategy_runtime import StrategyCandidate, ImplementationDependency
from czsc_trader.application import RepositoryContext, register_candidate, CandidateRegistrationRequest
from czsc_trader.research_tools import preflight_experiment, create_formal_experiment_context, execute_experiment
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from threadpoolctl import threadpool_limits
from publication import publish

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')


def main():
    assert not (ROOT / 'artifacts').exists()
    inputs = read(ROOT / 'inputs.json')
    assessment = 'neighbors' in inputs
    if assessment:
        prior = REPO / inputs['center_workspace']
        inputs['predecessors'] = {prior.parent.name: read(prior / 'execution_receipt.json')['receipt_sha256']}
        write(ROOT / 'inputs.json', inputs)
    names = ['experiment.py', 'run_experiment.py', 'publication.py', 'evaluation_batch.py', 'inputs.json', '01_goal.md', '02_design.md']
    if assessment:
        names += ['family_statistics.py', 'evaluation_policy.json', 'neighborhood_protocol.json', 'neighborhood_mapping.json']
    else:
        names += sorted({(ROOT / x['runtime_root'] / name).relative_to(ROOT).as_posix() for x in inputs['centers'] for name in x['payload']['runtime']['source_files']})
    write(ROOT / 'experiment_binding.json', dict(schema_version=3, module='experiment', qualname='Experiment',
        source_files=names, source_sha256=experiment_source_sha256(ROOT, tuple(names)), dependencies=inputs['dependencies']))
    loaded = load_experiment(ROOT)
    predecessors = tuple(load_experiment_input(ROOT.parent / ex / 'artifacts', expected_receipt_sha256=h) for ex, h in inputs['predecessors'].items())
    resources = ExperimentResources(8, 20261002, 1)
    cache = LocalCacheConfig(REPO / '.tmp/s011-regeneration/cache', 'S011-20260928-regeneration-v1', timedelta(days=1))
    report = preflight_experiment(loaded, resources=resources, predecessors=predecessors, dataflows=Dataflows(env_file=REPO / '.env', cache=cache))
    write(ROOT / 'preflight.json', report.to_dict())
    report.require_pass()
    if not assessment:
        repository = RepositoryContext.discover(REPO)
        origin = CandidateRegistrationOrigin(ROOT.name, loaded.definition.sha256,
            sha256((ROOT / 'experiment_binding.json').read_bytes()).hexdigest(),
            CandidateEvidence((ROOT / 'preflight.json').relative_to(REPO).as_posix(), sha256((ROOT / 'preflight.json').read_bytes()).hexdigest()))
        deps = tuple(ImplementationDependency(**x) for x in inputs['dependencies'])
        for spec in inputs['centers']:
            candidate = StrategyCandidate('S011', spec['candidate_id'], spec['payload'], ROOT / spec['runtime_root'])
            register_candidate(repository, CandidateRegistrationRequest(candidate, origin, deps))
    workspace = ExperimentWorkspace(REPO / '.tmp/s011-current/workspaces' / ROOT.name, REPO)
    context = create_formal_experiment_context(loaded.definition, repository_root=REPO,
        resources=resources, workspace=workspace, predecessors=predecessors, cache=cache)
    result = execute_experiment(loaded, context)
    shutil.copytree(workspace.root, ROOT / 'artifacts')
    receipt = publish()
    (ROOT / '03_execution.md').write_text(f'# 执行\n\n正式执行回执 `{result.receipt.sha256}`。8个受管进程，进程内单线程；固定参数，无新增搜索。\n', encoding='utf-8', newline='\n')
    stage = 'ASSESSMENT' if assessment else 'CANDIDATES'
    (ROOT / '04_conclusion.md').write_text(f'# 阶段交付\n\n状态 COMPLETE，公共验证 PASS。\n\n[报告](deliveries/{stage}/1/report.md) · [机器交付](deliveries/{stage}/1/delivery.json)\n\n用户已选择 C0618，阶段五执行技术一致性检验。已见开发池、选择偏差与复权历史时点限制继续保留。\n', encoding='utf-8', newline='\n')
    build_experiment_manifest(ROOT, dict(experiment_id=ROOT.name, strategy_id='S011', symbol='159326.SZ', status='COMPLETE', development_cutoff='2026-09-28'))
    validate_experiment_archive(ROOT)
    print(json.dumps(dict(status='COMPLETE', reference=receipt.reference.to_dict())), flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
