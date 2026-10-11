"""Publish immutable original13 geometry before any parameter preparation."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def main():
    assert not (PROTOCOLS / 'geometry.json').exists()
    previous = read(ROOT / 'research/S013/experiments/EX043_20261011/protocols/geometry.json')
    geometry = {name: previous[name] for name in ('version', 'protocol', 'coordinates', 'origins', 'mapping', 'feasibility')}
    geometry.update(fixed_or_categorical=[
        'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE fixed structural enum; original strictly past actual-L rawACF20 MEAN baseline, not current/future values',
        'confirmation lookback remains active in original score and bear MEAN baseline; all13 original numerical coordinates retained',
        'Only flat originaleligible rawbear after final bearTIME BELOW-own-signal-entry-anchor in its uninterrupted rawbear segment requires strict Close>previousClose before original score',
        'Rawbull on final bearTIME exit prevents category carry; later flat rawbull clears category before decision, preserving original last reason/route and confirmation context',
        'EQUAL/ABOVE/None unchanged; any entry clears all3 exit fields, flat refusal/ineligibility/rawbear preserve current category; original signal H and all holding exits unchanged',
        'Original confirmation profile/orientation/scope/enabled, context, null stops/trail/momentum, cooldown0, H units, exit priority, execution and fees'],
        comparison='Original EX01532 and coupled EX043N0 32 exact native reuse; only qualified newN0 gets32 new full points at same numeric centers/full13domains/coordinates. No failed center expansion.',
        candidate_reservation={'first': 3900, 'last': 3931},
        helper_source_files={name: file_hash(SRC / name) for name in (
            'run_parameters.py', 'parameter_analysis.py', 'pair_parameters.py', 'declare_geometry.py',
            'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py')},
        direction_oracle_sha256=file_hash(SRC / 'direction_oracle.py'),
        selection_history='After EX043/45 parameter tails failed and the zero-new-account full66 native context diagnosis found cross-rawbull incremental direction refusals, test one segment-expiry structure on the coupled background. Repeatedly exposed S013 development paths, not independent validation, profit prediction or a categorical/window search.',
        counts='If qualified:64 old32+32 controls reused,32 newbusiness/33actual including one technical serial/spawn duplicate. If unqualified:zero parameter preparation/evaluation/reuse.',
        identity='control_key cache aliases do not replace native labels/IDs/source/plans/lineage/account references. Registered coupled center is implementation parent; new center is PARAMETERS parent.',
        economic_policy='Only four original economic gates qualify center; all points retain all four diagnostic gates, no added veto. AbsoluteQ10/Q90 and relative degradations jointly inform improvement.')
    assert len(geometry['coordinates']) == 13 and geometry['protocol'] == {'radius': .05, 'point_count': 32, 'seed': 13}
    write(PROTOCOLS / 'geometry.json', geometry)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT, 'prospective-common-parameter-geometry',
        (PROTOCOLS / 'geometry.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'geometry_reference.json', ref.to_dict())
    print({'geometry': 'PUBLISHED', 'dimensions': 13, 'points': 32, 'centers_if_qualified': 3})


if __name__ == '__main__':
    main()
