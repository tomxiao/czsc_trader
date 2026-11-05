"""Apply a reviewed native candidate using the public same-version transaction.

This command is for the explicitly authorized local frozen-package migration.
It does not grant qualification, rebind a PTE account or touch production.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from czsc_trader.application import (RepositoryContext, create_research_context,
    load_candidate, publish_evidence, prepare_frozen_runtime_upgrade,
    apply_frozen_runtime_upgrade, FrozenRuntimeUpgradeRequest, validate_release_package)
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, MaterialEvidenceWrite
from strategy_manager import CandidateKey, StrategyRegistry
from strategy_manager.freeze_contracts import FrozenVersionReference, ResearchEvidenceOwner, ResearchEvidenceRef


def apply_reviewed(root, *, family, candidate_id, experiment_id, comparison, technical):
    root = Path(root).resolve()
    repository = RepositoryContext.discover(root)
    context = create_research_context(repository, ResearchBatchRef(family))
    experiment = ExperimentRef(family, experiment_id)
    candidate = load_candidate(repository, CandidateKey(family, candidate_id))
    # RSCH's explicit review, separate from the platform publication transaction.
    if family == 'S001':
        raise ValueError('S001 upgrades are paused by the user')
    origin = technical['origin']
    if (any(origin['candidate'][key] != value for key, value in candidate.key.to_dict().items())
            or origin['content_sha256'] != candidate.content_identity.content_sha256):
        raise ValueError('reviewed technical report belongs to different candidate content')
    if any(technical[name]['status'] != 'PASS' for name in ('behavior_equivalence', 'pte_runtime')):
        raise ValueError('reviewed technical inspection has not passed')
    manifest, _, _ = validate_release_package(repository, family + '-v1')
    version = StrategyRegistry(repository.strategy_root).get_version(family, 'v1')
    original = FrozenVersionReference(family, 'v1', version.release_hash, manifest['package_hash'])
    reviewed = {
        'candidate': candidate.key.to_dict(),
        'content_identity': asdict(candidate.content_identity),
        'comparison': comparison,
        'technical': technical,
        'scope': 'RSCH reviewed same-version V4 migration; no production changes or qualification grants; new content starts at RESEARCH',
    }
    authorization = {
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'actor': 'RSCH',
        'user_instructions': [
            '已冻结策略实现统一原地升级，适配当前PTE版本，并做等价性验证',
            '沿用 codex/dev-pte-multichannel-refactor',
            '继续',
        ],
        'interpretation': 'Continue the authorized frozen implementation migration and equivalence verification after DEV delivery; local same-version publication only.',
        'original': original.to_dict(),
        'candidate': candidate.key.to_dict(),
        'content_identity': asdict(candidate.content_identity),
        'excluded': ['production writes', 'PTE account rebinding', 'qualification grants', 'merge', 'push', 'tag'],
    }
    def publish(name, value):
        content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        ref = publish_evidence(context, MaterialEvidenceWrite(experiment, name, content, 'application/json', 'json'))
        return ResearchEvidenceRef(ResearchEvidenceOwner(family, experiment_id), ref.evidence_id, ref.sha256)
    confirmation = publish('native-v4-upgrade-user-authorization', authorization)
    evidence = publish('native-v4-upgrade-reviewed-verification', reviewed)
    prepared = prepare_frozen_runtime_upgrade(repository, FrozenRuntimeUpgradeRequest(
        original, candidate, confirmation,
        '原地迁移为原生V4；保留冻结参数、信号独立计时和周期补单规则。历史账户及PTE技术检验的范围和结论见所附材料。',
        'RSCH', (evidence,),
        root / '.tmp/rsch-frozen-v4-upgrade' / family / ('prepared-' + candidate.content_identity.content_sha256[:12])))
    receipt = apply_frozen_runtime_upgrade(repository, prepared)
    result = {'prepared': {**asdict(prepared), 'plan_path': prepared.plan_path.relative_to(root).as_posix()},
              'receipt': {**asdict(receipt), 'archive_path': receipt.archive_path.relative_to(root).as_posix(),
                          'receipt_path': receipt.receipt_path.relative_to(root).as_posix()},
              'authorization': confirmation.to_dict(), 'verification': evidence.to_dict()}
    output = experiment.resolve(root) / 'others' / 'native_v4_upgrade_receipt.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('family')
    parser.add_argument('candidate_id')
    parser.add_argument('experiment_id')
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--technical', type=Path, required=True)
    args = parser.parse_args()
    result = apply_reviewed(Path.cwd(), family=args.family, candidate_id=args.candidate_id,
        experiment_id=args.experiment_id,
        comparison=json.loads(args.comparison.read_text(encoding='utf-8')),
        technical=json.loads(args.technical.read_text(encoding='utf-8')))
    print(json.dumps(result, ensure_ascii=False, indent=2))
