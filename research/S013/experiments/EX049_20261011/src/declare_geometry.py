"""Prospective original13 declaration; execute only after root identity approval."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def build_geometry(previous):
    geometry = {name: previous[name] for name in ('version', 'protocol', 'coordinates', 'origins', 'mapping', 'feasibility')}
    legacy_path = 'research/S013/experiments/EX043_20261011/src/direction_oracle.py'
    geometry.update(fixed_or_categorical=[
        'MEAN_MOMENTUM3 fixed arithmetic structure: mbar=(m_t+m_t-1+m_t-2)/3 with m=Close/Close.shift(W)-1',
        'Full causal predecessor m values before reindex. W and theta retain original units/full13 domains/numeric centers; equality bull',
        'Both flat route and immediate holding regime exit use mean-state. Locked holding route and original range/time/stop/trail precedence unchanged',
        'Original raw ACF20/range/score/L/confirmation threshold remain active; no price smoothing, majority vote, deadband, standardized threshold or altered H units',
        'Fixed3 is structural only, not a searched confirmation period. warmup=max(parent,W+3), no missing-history fill'],
        comparison='Original EX01532 and coupled EX043N0 32 exact native reuse; only qualified newN0 gets32 new full points at original C2132 numeric centers/full13domains/coordinates. Coupled cohort is historical counterevidence with multiple structural differences.',
        candidate_reservation={'first': 6440, 'last': 6471},
        prospective_identity_note='New center C6480 and parameter C6440..6471 are prospective only; root must check all33 collisions before any declaration.',
        helper_source_files={name: file_hash(SRC / name) for name in (
            'run_parameters.py', 'parameter_analysis.py', 'pair_parameters.py', 'declare_geometry.py',
            'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py')},
        regime_oracle_sha256=file_hash(SRC / 'regime_oracle.py'),
        legacy_direction_oracle={'path': legacy_path, 'sha256': file_hash(ROOT / legacy_path)},
        selection_history='After FULL44 bear-exit delay frequency failure and existing original13 diagnosis; exact-prior-duplicate search found no mean of three original momentum implementation. One prospective fixed3 mechanism, no numerical optimization or independent validation.',
        counts='If qualified:64 old controls reused,32 newbusiness/33actual including one technical serial/spawn duplicate. If unqualified:zero parameter preparation/evaluation/reuse.',
        identity='control_key aliases preserve native labels/IDs/source/plans/lineage/account references. Registered original C2132 is IMPLEMENTATION parent; own new center is PARAMETERS parent. Coupled C4900 is historical control only.',
        economic_policy='Only four original economic gates qualify center; all neighbor gates remain diagnostics, no additional veto. AbsoluteQ10/Q90 and relative degradation jointly inform improvement.')
    assert len(geometry['coordinates']) == 13 and geometry['protocol'] == {'radius': .05, 'point_count': 32, 'seed': 13}
    return geometry


def main():
    assert not (PROTOCOLS / 'geometry.json').exists()
    previous = read(ROOT / 'research/S013/experiments/EX043_20261011/protocols/geometry.json')
    geometry = build_geometry(previous)
    write(PROTOCOLS / 'geometry.json', geometry)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT, 'prospective-common-parameter-geometry',
        (PROTOCOLS / 'geometry.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'geometry_reference.json', ref.to_dict())
    print({'geometry': 'PUBLISHED', 'dimensions': 13, 'points': 32, 'centers_if_qualified': 3})


if __name__ == '__main__':
    main()
