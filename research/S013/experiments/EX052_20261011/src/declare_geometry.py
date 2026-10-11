"""Prospective original13 declaration; execute only after root identity approval."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def build_geometry(previous):
    geometry = {name: previous[name] for name in ('version', 'protocol', 'coordinates', 'origins', 'mapping', 'feasibility')}
    legacy_path = 'research/S013/experiments/EX043_20261011/src/direction_oracle.py'
    geometry.update(fixed_or_categorical=[
        'BEAR_CONSENSUS_ACF20 fixed structure: bear_acf_value=min(original rawACF20,fixed one-per-tail winsorACF20); compare to the same original bear.acf_min, exactly equivalent to both statistics passing one cutoff',
        'Winsor component exactlyEX051: twenty original simple returns; sort only for second-smallest/second-largest bounds, retain original time order using max(lower,min(r,upper)), original common mean20/variance20/cov19 formula',
        'Original np.isclose(variance,0) unavailable rule on required winsor input, requiredT strictly refused even if raw cutoff already fails; no shortcircuit or oldACF fallback',
        'Only bear eligibility scalar changes. Original rawacf1 columns/rawACF buy confirmation, bull entry, rawregime routing/immediate exits, range/time/stop/trail precedence and signal-session H unchanged',
        'Complete causal daily computation before reindex; exactly20 finite returns. No18-observation trimming, interpolated quantile, sequence sorting, output coefficient clipping, abs, fallback or threshold remapping',
        'All13 original numerical domains/centers and original32 coordinates retained. Threshold0.1 is not equal filtering strength; minimum combines statistics rather than shrinking the threshold domain or mapping its units',
        'Fixed raw+one-per-tail winsor consensus, no searched weight/cutoff/window; original parent warmup unchanged, estimate needs21 causal prices',
        'Stricter eligibility at a fixed observed before-state can lose profitable entries or frequency; it does not imply fewer actual closed trades or better annual returns after state propagation'],
        comparison='Original EX01532 and coupled EX043N0 32 exact native reuse; only qualified newN0 gets32 new full points at original C2132 numeric centers/full13domains/coordinates. Coupled cohort is historical counterevidence with multiple structural differences.',
        candidate_reservation={'first': 7240, 'last': 7271},
        prospective_identity_note='New center C7280 and parameter C7240..7271 are prospective only; root must check all33 collisions before any declaration.',
        helper_source_files={name: file_hash(SRC / name) for name in (
            'run_parameters.py', 'parameter_analysis.py', 'pair_parameters.py', 'declare_geometry.py',
            'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py')},
        consensus_oracle_sha256=file_hash(SRC / 'consensus_oracle.py'),
        legacy_direction_oracle={'path': legacy_path, 'sha256': file_hash(ROOT / legacy_path)},
        selection_history='After FULL47 winsor-only center failed and prospectiveEX052 observed-state method found center5 lost targets/neighbor32 pooled176 lost targets with0 gains, test fixed raw/winsor same-cutoff consensus. Those conditional counts are not actual trades/profit and are not independent observations. Existing rank/smooth/centering/direction failures preserved. Adaptive exposed development pool, no numerical optimization or independent validation.',
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
