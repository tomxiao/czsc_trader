"""Immutable stage-three revision six and complementary-confirmation evidence."""
from hashlib import sha256
from importlib.metadata import version
import subprocess
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
    paths = read(RUNS / 'path_attribution.json')
    assert paths['status'] == 'PASS' and paths['successful_accounts'] == len(rows())
    assert read(RUNS / 'behavior_groups.json')['status'] == 'PASS'
    research, refs = context(1), {}

    def material(name, path):
        ref = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name,
            path.read_bytes(), 'application/json', 'json'))
        refs[name] = ref
        return ref

    for path in sorted(PROTOCOLS.glob('*plan.json')):
        material('cost-confirmation-' + path.stem.replace('_', '-'), path)
    material('cost-confirmation-authorization', PROTOCOLS / 'authorization.json')
    searches = [(path, read(path)) for path in sorted(RUNS.glob('cost_confirmation_*.json'))
                if 'rows' in read(path)]
    assert all(value['status'] == 'COMPLETE' for _, value in searches)
    for path, _ in searches:
        material(path.stem.replace('_', '-'), path)
    for name in ('precheck', 'synthetic_check', 'complement_synthetic_check', 'diagnostics',
                 'cost_diagnostics', 'selection', 'preservation', 'trade_attribution',
                 'path_attribution', 'behavior_groups', 'price_margin_precheck'):
        material('cost-confirmation-' + name.replace('_', '-'), RUNS / (name + '.json'))
    reproduction = {'files': {p.relative_to(SRC).as_posix(): {
        'sha256': sha256(p.read_bytes()).hexdigest(), 'source': p.read_text(encoding='utf-8')}
        for p in SRC.rglob('*.py')},
        'versions': {name: version(name) for name in ('numpy', 'pandas', 'optuna', 'czsc-strategy-runtime')},
        'baseline_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'retention': 'retain research/S013/assets/data and every bound DFLS reference; .tmp caches can be rebuilt from formal requests and evaluations',
        'prior_accounts': 'original account/control/pressure evidence remains in predecessor CANDIDATES/5; technical controls here reproduce the two parent baseline accounts',
        'scope': 'S013 original developer pool only; S007 expression already documented in predecessor; no new acquisition/platform/production changes'}
    write(RUNS / 'reproduction.json', reproduction)
    material('cost-confirmation-reproduction', RUNS / 'reproduction.json')
    previous = d.DeliveryReceipt.from_dict(read(ROOT / 'research/S013/deliveries/CANDIDATES/5/receipt.json'))
    assert previous.reference.content_sha256 == '10b9dede43468b5fa7eaa125288f5f8619aca3afea7269630f338cde98f2c2f4'
    old = d.DeliveryContent.from_dict(read(ROOT / 'research/S013/assets/deliveries/CANDIDATES/5/delivery.json')['content'])
    old_keys = set(old.payload.handoff)
    entries = [entry for entry in old.payload.candidates if entry.identity.key in old_keys]
    assert len(entries) == len(old_keys) == 65
    accounts = {entry.identity.key.candidate_id: entry.evaluations[0].evidence for entry in entries}
    index = {row['candidate_id']: row for row in rows()}
    plans = {value['rows'][0]['search']: value['plan'] for _, value in searches}
    registrations = []
    for identifier in selection['controls_material_only']:
        bound, result = cache_read(CACHE / (identifier + '.pkl.gz'))
        refs['control-' + identifier] = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
            'cost-confirmation-control-' + identifier.lower(), bound, result))
    for count, identifier in enumerate(selection['retained'], 1):
        row = index[identifier]
        bound, result = cache_read(CACHE / (identifier + '.pkl.gz'))
        computed = summarize(result)
        assert all(row[key] == computed[key] for key in ('annual', 'closed_trades', 'gates', 'result_hash', 'content_sha256'))
        ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
            'cost-confirmation-account-' + identifier.lower(), bound, result))
        accounts[identifier] = ref
        parent = row['parent']
        parent_record = read(ROOT / f'research/registrations/S013/candidates/{parent}.json')['record']
        origin = accounts[parent]
        same_source = bound.strategy.payload['runtime']['source_sha256'] == load_candidate(
            research.repository, CandidateKey('S013', parent)).payload['runtime']['source_sha256']
        derivation = CandidateDerivation(CandidateKey('S013', parent), parent_record['content_sha256'],
            CandidateKey('S013', identifier), row['content_sha256'],
            CandidateDerivationKind.PARAMETERS if same_source else CandidateDerivationKind.IMPLEMENTATION,
            {'mechanism': row['label'], 'parameters': row['parameters']},
            sha256((PROTOCOLS / plans[row['search']]).read_bytes()).hexdigest(),
            CandidateEvidence(origin.repository_path, origin.sha256))
        registered = register_candidate(research.repository, CandidateRegistrationRequest(
            bound.strategy, EXPERIMENT, (ref,), DEPENDENCIES, derivation))
        loaded = load_candidate(research.repository, CandidateKey('S013', identifier))
        assert StrategyRuntime().identify(loaded, dependencies=DEPENDENCIES).content_sha256 == row['content_sha256']
        registrations.append(registered.to_dict())
        judgment = ('原四门同时达标；费用和盈利余量为诊断，相同经济路径不算独立发现' if row['qualified'] else
                    '机制反证或费用代表；未通过：' + '、'.join(key for key, value in row['gates'].items() if not value))
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(registered.key, registered.content_sha256),
            '互补确认与价格费用取舍：' + row['label'], judgment, (d.EvaluationEvidenceRef(ref),)))
        print({'published_accounts': count, 'total': len(selection['retained'])}, flush=True)
    for row in costs['rows']:
        identifier = row['candidate_id']
        bound, result = cache_read(CACHE / (identifier + '-stress.pkl.gz'))
        refs['pressure-' + identifier] = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
            'cost-confirmation-pressure-' + identifier.lower(), bound, result))
    write(RUNS / 'account_references.json', {key: ref.to_dict() for key, ref in accounts.items()})
    write(RUNS / 'registrations.json', registrations)
    material('cost-confirmation-account-references', RUNS / 'account_references.json')
    report = (SRC.parent / 'others/report.md').read_text(encoding='utf-8').rstrip() + '\n\n## 正式证据索引\n\n'
    for name, ref in sorted(refs.items()):
        report += f'- [{name}](../../../assets/deliveries/CANDIDATES/6/{ref.path})\n'
    for identifier, ref in sorted(accounts.items()):
        report += f'- [{identifier}完整账户](../../../assets/deliveries/CANDIDATES/6/{ref.path})\n'
    summaries = tuple(d.SearchSummary(path.stem, 'Optuna事前固定队列、去重、TDR FULL实际账户',
        'S013原开发池和四门；初始后按可解释边界追加，全部样本已见',
        len(value['rows']), len({row['config_hash'] for row in value['rows']}),
        '全部新达标身份、费用代表与必要反证；原策略精确控制不重复登记',
        ('无独立封存样本；适应性设计受已见结果影响', '费用、余量、集中度和路径分组不新增资格门'),
        (refs[path.stem.replace('_', '-')],)) for path, value in searches)
    assert not selection['existing_content_aliases'], 'reuse existing identities explicitly before assembling'
    handoff = old.payload.handoff + tuple(CandidateKey('S013', key) for key in selection['qualified'])
    payload = d.CandidateSet(tuple(entries), handoff, summaries,
        '互补门可提高年化，弱年份余量未明显增厚；旧交接保持、同路径身份单列，是否继续阶段三或进入阶段四由用户决定。')
    print({'assembly': 'RUNNING', 'new_registrations': len(registrations), 'handoff': len(handoff)}, flush=True)
    receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 6, (previous.reference,)),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE,
            facts=(d.FactValue('cost_confirmation_successful_configurations', len(index), '个',
                d.FactStatus.AVAILABLE, (refs['cost-confirmation-selection'],)),),
            explanations=(), report=report, evidence=tuple(dict.fromkeys(refs.values()))))
    print({'delivery': receipt.reference.to_dict(), 'validation': 'RUNNING'}, flush=True)
    validation = validate_delivery(research.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status == d.ValidationStatus.PASS, validation.to_dict()
    output = {'status': 'PASS', 'reference': receipt.reference.to_dict(), 'validation': validation.to_dict(),
        'new_registrations': len(registrations), 'handoff': [key.candidate_id for key in handoff],
        'selection': selection['counts']}
    write(RUNS / 'delivery_validation.json', output)
    write(ROOT / 'research/S013/materials/cost_confirmation_20261009.json', output)
    print({'validation': 'FULL PASS', 'hash': receipt.reference.content_sha256}, flush=True)


if __name__ == '__main__':
    main()
