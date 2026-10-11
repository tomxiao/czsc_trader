"""Prospective original13 declaration; execute only after root identity approval."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def build_geometry(previous):
    geometry = {name: previous[name] for name in ('version', 'protocol', 'coordinates', 'origins', 'mapping', 'feasibility')}
    legacy_path = 'research/S013/experiments/EX043_20261011/src/direction_oracle.py'
    geometry.update(fixed_or_categorical=[
        'BEAR_RANK_ACF20 fixed structure:20 simple returns, adjacent19 pairs separately average-tie ranked, centered rank dot/sqrt(sumsquares product)',
        'Only bear entry ACF condition uses bear_acf_value>=original bear.acf_min. Original rawacf1 columns and original rawACF buy confirmation remain unchanged',
        'Original raw regime routing/immediate exits, bull entry, range/time/stop/trail precedence and original signal-session H unchanged',
        'Complete causal daily computation before reindex; exactly20 finite returns and positive variance in both19-rank samples; undefined correlation explicitly refused, no fill, abs, clip or scaling',
        'All13 original numerical domains/centers and original32 coordinates retained. Threshold0.1 is not equal filtering strength across the two estimators; both dimensionless but statistics differ',
        'Fixed20/19 structure, no new numeric coordinate or length search; original parent warmup unchanged, rank estimate needs21 causal prices'],
        comparison='Original EX01532 and coupled EX043N0 32 exact native reuse; only qualified newN0 gets32 new full points at original C2132 numeric centers/full13domains/coordinates. Coupled cohort is historical counterevidence with multiple structural differences.',
        candidate_reservation={'first': 6640, 'last': 6671},
        prospective_identity_note='New center C6680 and parameter C6640..6671 are prospective only; root must check all33 collisions before any declaration.',
        helper_source_files={name: file_hash(SRC / name) for name in (
            'run_parameters.py', 'parameter_analysis.py', 'pair_parameters.py', 'declare_geometry.py',
            'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py')},
        rank_oracle_sha256=file_hash(SRC / 'rank_oracle.py'),
        legacy_direction_oracle={'path': legacy_path, 'sha256': file_hash(ROOT / legacy_path)},
        selection_history='After EX049 mean-momentum center failed and bounded S013 EX050 duplicate/statistical-contract review found no exact prior local adjacent19-pair Spearman bear filter, test one prospective rank-estimator mechanism. Existing robust/smoothed ACF and direction-gate failures retained. Adaptive exposed development pool, no numerical optimization or independent validation.',
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
