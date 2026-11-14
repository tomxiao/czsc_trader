"""Shared immutable package descriptions for inspection and same-version upgrades."""

from strategy_runtime import EquityStrategyCandidate, RuntimeBindingSpec, StrategyRuntime
from strategy_manager import canonical_sha256


def candidate_install_files(candidate):
    """Keep Python source identity separate from declared data resources."""
    names = tuple(candidate.payload['runtime']['source_files'])
    if isinstance(candidate, EquityStrategyCandidate):
        names += tuple(asset.relative_path for asset in candidate.definition.frozen_assets)
    return names


def candidate_binding_spec(candidate, install_files=None):
    definition = StrategyRuntime().describe(candidate)
    source_files = tuple(candidate.payload['runtime']['source_files'])
    installed = candidate_install_files(candidate) if install_files is None else tuple(install_files)
    if isinstance(candidate, EquityStrategyCandidate):
        contract = f'equity-account-v{definition.contract_version}' if definition.account_replay else 'equity-decision-v2'
        return RuntimeBindingSpec(source_files, definition.source_sha256, installed,
            canonical_sha256({'contract': contract, 'definition': definition.to_dict()}))
    return RuntimeBindingSpec(source_files, definition.implementation.source_sha256, installed,
                              definition.observation.sha256)


def package_manifest(version, provenance_sha256, file_hashes, *, runtime_candidate_id=None):
    manifest = {'schema_version': 1, 'strategy_version_id': version.release_id,
        'strategy_version_hash': version.release_hash,
        'source_candidate_id': f'{version.strategy_id}-{version.source_candidate}',
        'candidate_package_hash': provenance_sha256, 'runtime_root': 'src/strategy_runtime',
        'runtime_binding': 'runtime_binding.json', 'files': dict(file_hashes)}
    if runtime_candidate_id is not None:
        from strategy_manager import CandidateKey
        CandidateKey(version.strategy_id, runtime_candidate_id)
        manifest.update(schema_version=2, runtime_candidate_id=runtime_candidate_id)
    manifest['package_hash'] = canonical_sha256(manifest)
    return manifest
