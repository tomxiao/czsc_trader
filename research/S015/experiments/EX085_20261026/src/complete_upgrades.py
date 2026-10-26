"""RSCH publication and audit under the approved audit-only upgrade contract."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json

import upgrade_batch as v
from czsc_trader.application import (
    FrozenRuntimeUpgradeRequest, apply_frozen_runtime_upgrade,
    prepare_frozen_runtime_upgrade, publish_evidence, validate_release_package,
)
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import EvidenceRef
from strategy_manager import StrategyRegistry, freeze_contracts as f
from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256


def context(ref):
    from czsc_trader.application import RepositoryContext, create_research_context
    from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, ExecutionResources
    from dataflows import ProviderConfig
    item = v.ITEMS[ref]
    ex = ExperimentRef.from_dict(item['experiment'])
    ctx = create_research_context(RepositoryContext.discover(v.ROOT), ResearchBatchRef(ex.strategy_id),
        resources=ExecutionResources(2, 1, 42), providers=ProviderConfig(bindings={}))
    home = v.ROOT / item['home']
    out = home / 'others' / ref
    out.mkdir(parents=True, exist_ok=True)
    return item, ex, ctx, home, out


def candidate(ref):
    item, ex, ctx, home, out = context(ref)
    family, version = ref.split('-')
    current = StrategyRegistry(ctx.repository.strategy_root).get_version(family, version)
    archive = ctx.repository.strategy_root / 'revisions' / ref / item['original']['release_hash']
    old_repo = ctx.repository if current.release_hash == item['original']['release_hash'] else replace(
        ctx.repository, strategy_root=archive / 'strategies')
    manifest, binding, _ = validate_release_package(old_repo, ref)
    assert manifest['strategy_version_hash'] == item['original']['release_hash']
    source = v.ROOT / item['source']
    payload = json.loads(json.dumps(item['original']['strategy_payload']))
    extra = sorted(p.relative_to(source).as_posix() for p in source.rglob('observation_*.py'))
    names = list(dict.fromkeys(payload['runtime']['source_files'] + binding['install_files'] + extra))
    payload['runtime'].update(source_files=names, source_sha256=implementation_sha256(tuple(names), source_root=source))
    child = StrategyCandidate(family, item['candidate_id'], payload, source)
    original = f.FrozenVersionReference(family, version, item['original']['release_hash'], manifest['package_hash'])
    return child, original


def publish(ctx, ex, name, value):
    data = json.dumps(v.plain(value), ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    return publish_evidence(ctx, MaterialEvidenceWrite(ex, name, data, 'application/json', 'json'))


def research_ref(ref):
    return f.ResearchEvidenceRef(f.ResearchEvidenceOwner(ref.experiment.strategy_id, ref.experiment.experiment_id),
                                ref.evidence_id, ref.sha256)


def apply(ref):
    item, ex, ctx, home, out = context(ref)
    child, original = candidate(ref)
    definition = StrategyRuntime().describe(child)
    if ex.strategy_id == 'S001':
        case = out / 'audit_replay_v2'
        result = v.read(case / 'result.json')
        assert result['source_sha256'] == child.payload['runtime']['source_sha256']
        result['identity'] = {side + '_identity': v.read(case / (side + '_binding.json'))['plan']['strategy']
                              for side in ('old', 'new')}
        published = v.read(case / 'published.json')
        for name, raw in published.items():
            evidence = EvidenceRef.from_dict(raw)
            assert (case / name).read_bytes() == evidence.resolve(v.ROOT).read_bytes()
        result['published_artifacts'] = published
    else:
        result = v.read(out / 'equivalence/result.json')
        for record in result['artifacts']:
            path = out / record['path']
            assert sha256(path.read_bytes()).hexdigest() == record['sha256'], path
    assert result['status'] == 'PASS'
    assert result['identity']['new_identity']['runtime_sha256'] == definition.runtime_sha256
    assert result['identity']['old_identity']['release_hash'] == original.release_hash
    validation = publish(ctx, ex, ref + '_research_equivalence', result)
    authorization = publish(ctx, ex, ref + '_audit_upgrade_authorization', {
        'user_instruction': '同意，切换RSCH，使用新API自主完成剩余已冻结策略发布包的原地升级。',
        'additional_instruction': '还需要完成等价性测试',
        'original': original.to_dict(), 'candidate': child.reference_id,
        'scope': '仅升级信号解释；原交易机制、参数、版本号、父版本、研究日期保持；生产操作另行授权。',
        'responsibility': 'RSCH负责解释及等价性结论；TDR记录与提交升级事务。',
    })
    refs = [research_ref(validation)]
    prior_inspection = out / 'inspection_ref.json'
    if prior_inspection.exists():
        refs.append(f.ResearchEvidenceRef.from_dict(v.read(prior_inspection)))
    prepared = prepare_frozen_runtime_upgrade(ctx.repository, FrozenRuntimeUpgradeRequest(
        original, child, research_ref(authorization),
        '仅补齐v4信号解释；RSCH双模式历史信号与五本经济账本等价核验通过。',
        'RSCH / Codex，依据本会话用户授权执行', tuple(refs),
        v.WORK / 'audit-staged' / ref))
    v.save(out / 'audit_upgrade_prepared.json', prepared)
    receipt = apply_frozen_runtime_upgrade(ctx.repository, prepared)
    raw = v.read(receipt.receipt_path)
    v.save(out / 'audit_upgrade_receipt.json', raw)
    v.save(out / 'audit_upgrade_evidence_refs.json', {'authorization': authorization.to_dict(),
                                                    'equivalence': validation.to_dict()})
    print(ref, 'COMMITTED', raw['migrated'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('reference', nargs='+')
    args = parser.parse_args()
    for reference in args.reference:
        apply(reference)
