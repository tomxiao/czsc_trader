"""Immutable confirmation research evidence and stage-three revision five."""
from hashlib import sha256
from importlib.metadata import version
from czsc_trader.application import (
    publish_evidence, register_candidate, load_candidate, CandidateRegistrationRequest,
    assemble_delivery, validate_delivery,
)
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import StrategyRuntime
from common import ROOT, SRC, EXPERIMENT, PROTOCOLS, RUNS, CACHE, DEPENDENCIES, context, read, write, cache_read
from diagnose import rows
from economics_r4 import summarize


def main():
    selection, diagnostics, costs = (read(RUNS / (name + '.json'))
                                    for name in ('selection', 'diagnostics', 'cost_diagnostics'))
    assert diagnostics['status'] == 'PASS' and costs['status'] == 'COMPLETE'
    assert diagnostics['known_low_error_potential_orders'] == 0
    score = read(RUNS / 'score_attribution.json')
    assert score['successful_configurations_covered'] == len(rows())
    assert {item['candidate_id'] for item in score['actual_paths']} == {
        row['candidate_id'] for row in rows() if row['parameters']['confirmation']['enabled']}
    research, refs = context(1), {}

    def material(name, path, media='application/json'):
        ref = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name,
            path.read_bytes(), media, path.suffix.removeprefix('.')))
        refs[name] = ref
        return ref

    for path in sorted(PROTOCOLS.glob('*plan.json')):
        material('confirmation-' + path.stem.replace('_', '-'), path)
    material('confirmation-authorization', PROTOCOLS / 'authorization.json')
    searches = [(path, read(path)) for path in sorted(RUNS.glob('confirmation_*.json'))
                if 'rows' in read(path)]
    assert all(value['status'] == 'COMPLETE' for _, value in searches)
    for path, _ in searches:
        material(path.stem.replace('_', '-'), path)
    for name in ('precheck', 'synthetic_check', 'context_synthetic_check', 'context_precheck',
                 'context_precheck_failure', 'raw_volume_scope_preparation', 'diagnostics',
                 'cost_diagnostics', 'selection', 'preservation', 'score_attribution'):
        material('confirmation-' + name.replace('_', '-'), RUNS / (name + '.json'))
    material('confirmation-opportunity-labels', RUNS / 'conditional_opportunities.csv', 'text/csv')
    reproduction = {'files': {p.relative_to(SRC).as_posix(): {
        'sha256': sha256(p.read_bytes()).hexdigest(), 'source': p.read_text(encoding='utf-8')}
        for p in SRC.rglob('*.py')},
        'versions': {name: version(name) for name in ('numpy', 'pandas', 'optuna', 'czsc-strategy-runtime')},
        'baseline_commit': '1a398248d62fafbbed1dc64cd5f3222e24c59201',
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'retention': 'research/S013/assets/data and all bound preparation references; .tmp is a cache',
        'scope': 'S013 research only; S007-v1 frozen expression reference; no new acquisition, platform or production changes'}
    write(RUNS / 'reproduction.json', reproduction)
    material('confirmation-reproduction', RUNS / 'reproduction.json')
    previous_receipt = d.DeliveryReceipt.from_dict(read(ROOT / 'research/S013/deliveries/CANDIDATES/4/receipt.json'))
    old = d.DeliveryContent.from_dict(read(ROOT / 'research/S013/assets/deliveries/CANDIDATES/4/delivery.json')['content'])
    old_keys = set(old.payload.handoff)
    entries = [entry for entry in old.payload.candidates if entry.identity.key in old_keys]
    assert {entry.identity.key for entry in entries} == old_keys
    accounts = {entry.identity.key.candidate_id: entry.evaluations[0].evidence for entry in entries}
    index = {row['candidate_id']: row for row in rows()}
    plans = {value['rows'][0]['search']: value['plan'] for _, value in searches}
    registrations = []
    for count, identifier in enumerate(selection['retained'], 1):
        row = index[identifier]
        bound, result = cache_read(CACHE / (identifier + '.pkl.gz'))
        computed = summarize(result)
        assert all(row[key] == computed[key] for key in ('annual', 'closed_trades', 'gates', 'result_hash', 'content_sha256'))
        ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
            'confirmation-account-' + identifier.lower(), bound, result))
        accounts[identifier] = ref
        parent = row['parent']
        parent_record = read(ROOT / f'research/registrations/S013/candidates/{parent}.json')['record']
        origin = accounts[parent]
        derivation = CandidateDerivation(CandidateKey('S013', parent), parent_record['content_sha256'],
            CandidateKey('S013', identifier), row['content_sha256'], CandidateDerivationKind.IMPLEMENTATION,
            {'mechanism': row['label'], 'parameters': row['parameters']},
            sha256((PROTOCOLS / plans[row['search']]).read_bytes()).hexdigest(),
            CandidateEvidence(origin.repository_path, origin.sha256))
        registered = register_candidate(research.repository, CandidateRegistrationRequest(
            bound.strategy, EXPERIMENT, (ref,), DEPENDENCIES, derivation))
        loaded = load_candidate(research.repository, CandidateKey('S013', identifier))
        assert StrategyRuntime().identify(loaded, dependencies=DEPENDENCIES).content_sha256 == row['content_sha256']
        registrations.append(registered.to_dict())
        judgment = ('原四门同时达标；费用压力等为诊断' if row['qualified'] else
                    '机制反证或取舍前沿；未通过：' + '、'.join(key for key, value in row['gates'].items() if not value))
        if not row['parameters']['confirmation']['enabled']:
            judgment += '；关闭确认的等价控制，不作为新机制发现'
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(registered.key, registered.content_sha256),
            '原机会与因果可得确认分联合控制买入：' + row['label'], judgment, (d.EvaluationEvidenceRef(ref),)))
        print({'published_accounts': count, 'total': len(selection['retained'])}, flush=True)
    for row in costs['rows']:
        identifier = row['candidate_id']
        bound, result = cache_read(CACHE / (identifier + '-stress.pkl.gz'))
        refs['cost-' + identifier] = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
            'confirmation-cost-' + identifier.lower(), bound, result))
    write(RUNS / 'account_references.json', {key: ref.to_dict() for key, ref in accounts.items()})
    write(RUNS / 'registrations.json', registrations)
    material('confirmation-account-references', RUNS / 'account_references.json')
    report = (SRC.parent / 'others/report.md').read_text(encoding='utf-8')
    report += '\n\n## 正式证据索引\n\n'
    for name, ref in sorted(refs.items()):
        report += f'- [{name}](../../../assets/deliveries/CANDIDATES/5/{ref.path})\n'
    for identifier, ref in sorted(accounts.items()):
        report += f'- [{identifier}完整账户](../../../assets/deliveries/CANDIDATES/5/{ref.path})\n'
    summaries = tuple(d.SearchSummary(path.stem, 'Optuna固定队列、去重、TDR FULL实际账户',
        'S013原开发池与四门；已见样本重复复用；S007仅借用表达结构',
        len(value['rows']), len({row['config_hash'] for row in value['rows']}),
        '全部达标身份、诊断前沿及必要反证；关闭确认控制单列',
        ('无独立封存样本；根据已见结果适应性追加', '压力费用和盈利余量不新增资格门'),
        (refs[path.stem.replace('_', '-')],)) for path, value in searches)
    handoff = old.payload.handoff + tuple(CandidateKey('S013', key) for key in selection['qualified'])
    payload = d.CandidateSet(tuple(entries), handoff, summaries,
        '确认分阶段三验证；旧交接保持、新达标单列；是否继续研究或推进阶段由用户决定。')
    receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 5, (previous_receipt.reference,)),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE,
            facts=(d.FactValue('confirmation_successful_configurations',
                selection['counts']['successful_configurations'], '个', d.FactStatus.AVAILABLE,
                (refs['confirmation-selection'],)),), explanations=(), report=report,
            evidence=tuple(dict.fromkeys(refs.values()))))
    print({'delivery': receipt.reference.to_dict(), 'validation': 'RUNNING'}, flush=True)
    validation = validate_delivery(research.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status == d.ValidationStatus.PASS, validation.to_dict()
    output = {'status': 'PASS', 'reference': receipt.reference.to_dict(), 'validation': validation.to_dict(),
        'new_registrations': len(registrations), 'handoff': [key.candidate_id for key in handoff],
        'selection': selection['counts']}
    write(RUNS / 'delivery_validation.json', output)
    write(ROOT / 'research/S013/materials/buy_confirmation_20261009.json', output)
    print({'validation': 'FULL PASS', 'hash': receipt.reference.content_sha256}, flush=True)


if __name__ == '__main__':
    main()
