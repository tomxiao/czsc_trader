"""Prospective original13 declaration; execute only after root identity approval."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def build_geometry(previous):
    geometry = {name: previous[name] for name in ('version', 'protocol', 'coordinates', 'origins', 'mapping', 'feasibility')}
    legacy_path = 'research/S013/experiments/EX043_20261011/src/direction_oracle.py'
    geometry.update(fixed_or_categorical=[
        'RAW_BEAR_TIME_BELOW_CLOSE fixed structure on original C2132 rawACF20 background; only originaleligible flatrawbear after finalbearTIME strictBELOW own signal-entry anchor additionally requires currentClose>previousactualTradingClose',
        'Only final reason=time and exit-before active_route=bear classifies BELOW/EQUAL/ABOVE with strict signalClose versus own episode signal-entry anchor. All other exits category=None; no epsilon, threshold/day search or fill-PnL labels',
        'Beforedecision last_exit_reason/route/category object None initially; flat failures, direction refusals and rawroute changes preserve context, any route signalentry clears all three. EQUAL/ABOVE/NONE never acquire direction gate',
        'Original eligible opportunity and confirmation_pass retain original meaning; direction refusal precedes originalscore rejection only within selected BELOW scope. No holding exit or same-day exit/entry behavior changes',
        'Original rawACF20 eligibility/confirmation, bull rules, range/time/regime/loss/trail priority, held-session H and all13 numerical coordinates remain active and unchanged; L only in original confirmation score',
        'All13 original numerical domains/centers and original32 coordinates retained; no statistic replacement, threshold/unit remapping, narrowing, new numeric dimensions or point reselection',
        'Original parent warmup unchanged exactly, including W60/L40/ranges21 minimum61 and center180; previousClose from complete daily shift1, no previous_regime/momentum diagnostic or W+2 requirement',
        'Original positive2023 BELOW-category cash contribution+2.3049pp is strongest counterevidence; rejecting reentries can lose favorable rebound/frequency, persistent context may be stale across rawbull. Contributions describe old path, never deletion-profit predictions'],
        comparison='Original EX01532 and coupled EX043N0 32 exact native reuse; only qualified newN0 gets32 new full points at original C2132 numeric centers/full13domains/coordinates. Coupled cohort is historical counterevidence with multiple structural differences.',
        candidate_reservation={'first': 7540, 'last': 7571},
        prospective_identity_note='New center C7580 and parameter C7540..7571 are prospective only; root must check all33 collisions before any declaration.',
        helper_source_files={name: file_hash(SRC / name) for name in (
            'run_parameters.py', 'parameter_analysis.py', 'pair_parameters.py', 'declare_geometry.py',
            'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py')},
        raw_below_oracle_sha256=file_hash(SRC / 'raw_below_oracle.py'),
        legacy_direction_oracle={'path': legacy_path, 'sha256': file_hash(ROOT / legacy_path)},
        selection_history='After repeated MEAN/category and robust-ACF routes failed to satisfy joint original goals, return to original RAW ACF background and isolate the existing BELOW-close gate. EX042 original2023 BELOW-source contribution+2.3049pp is positive counterevidence, not a chosen loss-year exception or deletable profit. All years retained; adaptive exposed development pool, no independent validation or category/window optimization.',
        counts='If qualified:64 old controls reused,32 newbusiness/33actual including one technical serial/spawn duplicate. If unqualified:zero parameter preparation/evaluation/reuse.',
        identity='control_key aliases preserve native labels/IDs/source/plans/lineage/account references. Registered original C2132 is IMPLEMENTATION parent; own new center is PARAMETERS parent. Coupled C4900 is historical control only.',
        diagnostic_controls='Extra MEAN no-gate C8701 center may appear in plan.diagnostic_controls/analysis.rows B0-MEAN only; not controls, selected center, reused parameter cohort or SE/pair panel.',
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
