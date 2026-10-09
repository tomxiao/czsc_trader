"""Publish real selected accounts, authenticated identities and CANDIDATES/4."""
from hashlib import sha256
from importlib.metadata import version

from czsc_trader.application import (
    publish_evidence, register_candidate, load_candidate, CandidateRegistrationRequest,
    assemble_delivery, validate_delivery,
)
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import StrategyRuntime
from common import ROOT, SRC, EXPERIMENT, PROTOCOLS, RUNS, CACHE, DEPENDENCIES, context, read, write, cache_read
from diagnose import rows
from economics_r4 import summarize


def previous(stage, revision):
    return d.DeliveryReceipt.from_dict(read(ROOT / f'research/S013/deliveries/{stage}/{revision}/receipt.json')).reference


def registered_entry(identifier):
    loaded = load_candidate(context(1).repository, CandidateKey('S013', identifier))
    record = read(ROOT / f'research/registrations/S013/candidates/{identifier}.json')['record']
    assert StrategyRuntime().identify(loaded, dependencies=DEPENDENCIES).content_sha256 == record['content_sha256']
    original = record['origin']['evidence'][0]
    ref = EvidenceRef(ExperimentRef('S013', record['origin']['experiment_id']),
        original['sha256'] + '.json', original['sha256'], 'application/json',
        'contract-migration-' + identifier.lower(), 'account_evaluation', 5)
    ref.resolve(ROOT)
    return d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', identifier), record['content_sha256']),
        '原阶段三达标配置的技术继任，经济账本与原候选精确等价。',
        '沿用已交付资格和阶段四反证；本轮不将其视为独立新发现。',
        (d.EvaluationEvidenceRef(ref),)), ref


def main():
    selection = read(RUNS / 'selection.json')
    diagnosis = read(RUNS / 'diagnostics.json')
    costs = read(RUNS / 'cost_diagnostics.json')
    assert diagnosis['status'] == 'PASS' and costs['status'] == 'COMPLETE'
    assert diagnosis['known_low_error_potential_orders'] == 0
    research = context(1)
    refs = {}

    def material(name, path, media='application/json'):
        ref = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name,
            path.read_bytes(), media, path.suffix.removeprefix('.')))
        refs[name] = ref
        return ref

    for path in sorted(PROTOCOLS.glob('*plan.json')):
        material('continuation-' + path.stem.replace('_', '-'), path)
    material('continuation-authorization', PROTOCOLS / 'authorization.json')
    for path in sorted(RUNS.glob('state_*.json')):
        if 'rows' in read(path):
            material('continuation-' + path.stem.replace('_', '-'), path)
    for name in ('precheck', 'synthetic_check', 'mechanism_boundary_check', 'diagnostics',
                 'cost_diagnostics', 'selection', 'preservation'):
        material('continuation-' + name.replace('_', '-'), RUNS / (name + '.json'))
    reproduction = {'files': {p.relative_to(SRC).as_posix(): {
        'sha256': sha256(p.read_bytes()).hexdigest(), 'source': p.read_text(encoding='utf-8')}
        for p in SRC.rglob('*.py')},
        'versions': {n: version(n) for n in ('numpy', 'pandas', 'optuna', 'czsc-strategy-runtime')},
        'baseline_commit': 'c7a99508dac242fca77780e70a1861175cd1f02c',
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'data_retention': 'research/S013/assets/data and all bound preparation references; .tmp is only a cache',
        'scope': 'S013 only; no new source/dependency/platform/production modifications'}
    write(RUNS / 'reproduction.json', reproduction)
    material('continuation-reproduction', RUNS / 'reproduction.json')
    old_content = d.DeliveryContent.from_dict(read(ROOT / 'research/S013/assets/deliveries/COMPONENTS/1/delivery.json')['content'])
    refs['stage-two-data'] = next(ref for ref in old_content.evidence if ref.name == 'stage-two-data')
    migration = read(ROOT / 'research/S013/materials/contract_migration_20261009.json')
    refs['contract-migration-equivalence'] = EvidenceRef.from_dict(migration['evidence']['candidate_equivalence.json'])
    original_centers = [row['successor'] for row in migration['candidate_migration'] if row['stage4_center']]
    entries, accounts, registrations = [], {}, []
    for identifier in original_centers:
        entry, ref = registered_entry(identifier)
        entries.append(entry)
        accounts[identifier] = ref
    indexed = {row['candidate_id']: row for row in rows()}
    search_plans = {read(path)['rows'][0]['search']: read(path)['plan']
                    for path in RUNS.glob('state_*.json') if 'rows' in read(path)}
    for identifier in selection['retained']:
        row = indexed[identifier]
        bound, result = cache_read(CACHE / f'{identifier}.pkl.gz')
        computed = summarize(result)
        for key in ('annual', 'closed_trades', 'gates', 'result_hash', 'content_sha256'):
            assert row[key] == computed[key], (identifier, key)
        ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
            'continuation-account-' + identifier.lower(), bound, result))
        accounts[identifier] = ref
        parent = row['parent']
        parent_record = read(ROOT / f'research/registrations/S013/candidates/{parent}.json')['record']
        parent_evidence = parent_record['origin']['evidence'][0]
        origin = EvidenceRef(ExperimentRef('S013', parent_record['origin']['experiment_id']),
            parent_evidence['sha256'] + '.json', parent_evidence['sha256'], 'application/json',
            'contract-migration-' + parent.lower(), 'account_evaluation', 5)
        derivation = CandidateDerivation(CandidateKey('S013', parent), parent_record['content_sha256'],
            CandidateKey('S013', identifier), row['content_sha256'], CandidateDerivationKind.IMPLEMENTATION,
            {'mechanism': row['label'], 'parameters': row['parameters']},
            sha256((PROTOCOLS / search_plans[row['search']]).read_bytes()).hexdigest(),
            CandidateEvidence(origin.repository_path, origin.sha256))
        registered = register_candidate(research.repository, CandidateRegistrationRequest(
            bound.strategy, EXPERIMENT, (ref,), DEPENDENCIES, derivation))
        loaded = load_candidate(research.repository, CandidateKey('S013', identifier))
        assert StrategyRuntime().identify(loaded, dependencies=DEPENDENCIES).content_sha256 == row['content_sha256']
        registrations.append(registered.to_dict())
        judgments = '原四门同时达标；诊断不改变资格' if row['qualified'] else (
            '前沿或机制反证；未通过：' + '、'.join(k for k, value in row['gates'].items() if not value))
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(registered.key, registered.content_sha256),
            '状态退出方向、连续确认及状态专用冷却与持有期的因果可得机制对照：' + row['label'],
            judgments, (d.EvaluationEvidenceRef(ref),)))
    # Selected cost accounts also become formal evidence; do not leave them only in caches.
    for row in costs['rows']:
        identifier = row['candidate_id']
        bound, result = cache_read(CACHE / f'{identifier}-stress.pkl.gz')
        material_ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
            'continuation-cost-' + identifier.lower(), bound, result))
        refs['cost-' + identifier] = material_ref
    write(RUNS / 'account_references.json', {k: ref.to_dict() for k, ref in accounts.items()})
    write(RUNS / 'registrations.json', registrations)
    material('continuation-account-references', RUNS / 'account_references.json')
    report = (SRC.parent / 'others/report.md').read_text(encoding='utf-8')
    report += '\n\n## 正式证据索引\n\n'
    for name, ref in sorted(refs.items()):
        report += f'- [{name}](../../../assets/deliveries/CANDIDATES/4/{ref.path})\n'
    for identifier, ref in sorted(accounts.items()):
        report += f'- [{identifier}完整账户](../../../assets/deliveries/CANDIDATES/4/{ref.path})\n'
    searches = []
    for path in sorted(RUNS.glob('state_*.json')):
        value = read(path)
        if 'rows' not in value:
            continue
        assert value['status'] == 'COMPLETE'
        searches.append(d.SearchSummary(path.stem, 'Optuna固定队列、去重、TDR完整账户多进程评价',
            'S013原开发池、费用、HFQ研究单位与四项目标；已有样本持续复用',
            len(value['rows']), len({row['config_hash'] for row in value['rows']}),
            '全部原四门达标配置和盈利余量/收益/频率前沿；机制反证单列',
            ('无独立封存样本；根据已见结果追加机制对照', '费用和邻域只作诊断，不新增资格门'),
            (refs['continuation-' + path.stem.replace('_', '-')],)))
    handoff = tuple(CandidateKey('S013', identifier) for identifier in original_centers + selection['qualified'])
    payload = d.CandidateSet(tuple(entries), handoff, tuple(searches),
        '阶段三机制补证完成，新增结果与旧中心一并交接；经济改善和风险依据报告逐项判断，后续阶段等待用户决定。')
    receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 4,
            (previous('MANDATE', 5), previous('CANDIDATES', 3), previous('ASSESSMENT', 1))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE,
            facts=(d.FactValue('continuation_successful_configurations',
                selection['counts']['successful_configurations'], '个', d.FactStatus.AVAILABLE,
                (refs['continuation-selection'],)),), explanations=(), report=report,
            evidence=tuple(dict.fromkeys(refs.values()))))
    validation = validate_delivery(research.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status == d.ValidationStatus.PASS, validation.to_dict()
    output = {'status': 'PASS', 'reference': receipt.reference.to_dict(),
        'validation': validation.to_dict(), 'new_registrations': len(registrations),
        'handoff': [key.candidate_id for key in handoff], 'selection': selection['counts']}
    write(RUNS / 'delivery_validation.json', output)
    write(ROOT / 'research/S013/materials/stage3_continuation_20261009.json', output)
    print(output, flush=True)


if __name__ == '__main__':
    main()
