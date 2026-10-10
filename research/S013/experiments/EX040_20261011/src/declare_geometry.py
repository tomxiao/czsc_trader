"""Freeze the unchanged original complete numerical domain and helper identities."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def main():
    assert not (PROTOCOLS / 'geometry.json').exists()
    old = read(ROOT / 'research/S013/experiments/EX038_20261011/protocols/geometry.json')
    geometry = {'version': 'S013-common-domain-mechanism-diagnostic-v1',
        'protocol': old['protocol'], 'coordinates': old['coordinates'], 'origins': old['origins'],
        'mapping': old['mapping'], 'feasibility': old['feasibility'],
        'fixed_or_categorical': ['mechanism', 'confirmation orientation/profile/scope/enabled',
            'context entry_gate/volume_basis/weighting', 'exit_on_regime_change', 'null stops/trail/momentum',
            'zero cooldown', 'execution limit premium .01',
            'strict Close>previousClose or Close>Open at flat eligible rawbear entry only; no direction magnitude threshold; categorical alternatives outside13 coordinates; RAW rawACF20 unchanged, MEAN existing L supplies strictpast baseline; original H units unchanged'],
        'comparison': 'Original C2132 and only each new four-gate-qualified direction center at identical numeric centers/all13 full domains/32point coordinates; original EX01532 exact native reuse. No outcome-based point replacement or added economic veto.',
        'difference_from_historical': 'Same full13 domain/totalL2=.05/PCG64seed13/HALF_EVEN/LINEAR32 as EX015. Earlier different-domain tails are not substitutes. Each qualifying new center receives32business/33actual including one technical serial/spawn duplicate; failed centers remain center-only.',
        'reason': 'Preserve original business-valid full domains and pair all13 original numeric points rather than narrowing domains or dropping coordinates.',
        'helper_source_files': {name: file_hash(SRC / name) for name in
            ('run_parameters.py', 'parameter_analysis.py', 'pair_parameters.py', 'declare_geometry.py',
             'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py')},
        'direction_oracle_sha256': file_hash(SRC / 'direction_oracle.py'),
        'implementation_parent_authentication': 'Exact native original C2132 account and public registry identity are IMPLEMENTATION registration anchor; MEAN EX028/N1 is disclosed intermediate unqualified background evidence only. Qualified EX040 new-center evidence is PARAMETERS parent. Authenticate exact identities/source/dependencies/runtime-binding/parameters/formal native ledgers; no invented registry parent or promotion.'}
    assert len(geometry['coordinates']) == 13 and geometry['protocol'] == {'radius': .05, 'point_count': 32, 'seed': 13}
    write(PROTOCOLS / 'geometry.json', geometry)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT, 'prospective-common-parameter-geometry',
        (PROTOCOLS / 'geometry.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'geometry_reference.json', ref.to_dict())
    print({'geometry': 'PUBLISHED', 'coordinates': 13, 'radius': .05, 'points': 32}, flush=True)


if __name__ == '__main__':
    main()
