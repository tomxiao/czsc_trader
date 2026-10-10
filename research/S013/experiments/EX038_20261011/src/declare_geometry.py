"""Fix a common complete coordinate domain before viewing mechanism results."""
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import EXPERIMENT,PROTOCOLS,SRC,context,file_hash,write

def main():
    assert not (PROTOCOLS/'geometry.json').exists()
    geometry={'version':'S013-common-domain-mechanism-diagnostic-v1','protocol':{'radius':.05,'point_count':32,'seed':13},
        'coordinates':[
            ['bull.range_window',21.,360.,'INTEGER'],['bull.entry',0.,1.,'CONTINUOUS'],['bull.exit',0.,1.,'CONTINUOUS'],['bull.max_hold',1.,60.,'INTEGER'],
            ['bear.range_window',21.,360.,'INTEGER'],['bear.entry',0.,1.,'CONTINUOUS'],['bear.exit',0.,1.,'CONTINUOUS'],['bear.max_hold',1.,60.,'INTEGER'],['bear.acf_min',-.60,.50,'CONTINUOUS'],
            ['regime_window',5.,60.,'INTEGER'],['regime_threshold',-.2,.2,'CONTINUOUS'],['confirmation.lookback',40.,120.,'INTEGER'],['confirmation.threshold',-.5,.5,'CONTINUOUS']],
        'mapping':'payload.parameters dotted paths; int casts only INTEGER coordinates, float otherwise; all other payload and source unchanged per center.',
        'feasibility':'bull.entry<bull.exit and bear.entry<bear.exit; domain and integer constraints enforced by SE.',
        'origins':{'route_domains':'EX014 original range_reversion.py:39-44 complete source business-valid domains',
            'acf_domain':'EX004 src/search.py:26,29 existing S013 extended search [-.60,.50]; source itself only checks finite',
            'regime_domains':'EX014 original adaptive_range.py:19-24',
            'confirmation_domains':'EX014 original confirmed_range.py:52-57'},
        'fixed_or_categorical':['mechanism','confirmation orientation/profile/scope/enabled','context entry_gate/volume_basis/weighting','exit_on_regime_change',
            'null stops/trail/momentum','zero cooldown','execution limit premium .01','fixed raw component ACF20; native MEAN reference uses existing confirmation lookback and BODY background preserves entry context; fixed adverse-displacement cutoff2 or3 per center and strictly past20 TR unit excluded from13 coordinates, with no claim either selected width or the20-day window is stable; signal-entry Close anchor and no entry-day exit; all13 original numerical coordinates active; H8/H4 original signal-session units unchanged'],
        'comparison':'Original C2132 and every new four-gate-qualified mechanism using identical declared domains and method. No performance-based point replacement. These are diagnostics, not new economic gates.',
        'difference_from_historical':'S013 EX011 metadata preserves historical domain references/hashes, without accessing adjacent-batch bytes. Same complete domains as EX015; reuse exactly verified original bullH8/bearH4 TIME EX015 parameter accounts. Qualified new MEAN/BODY fixed-risk centers and original C2132 share all13 numeric centers and all32 point coordinates exactly; old unqualified0/1-risk background centers receive no extra parameters; each qualified new center alone receives32 new points/33actual, including one per-center serial/spawn duplicate. Historical 9.5670/11.3476pp is a different-domain diagnosis and must not be substituted as same-domain baseline.',
        'reason':'Use complete source business-valid domains and existing S013 ACF search domain rather than invent outcome-sensitive narrower bounds; normalize both centers with the same domain.',
        'helper_source_files':{name:file_hash(SRC/name) for name in (
            'run_parameters.py','parameter_analysis.py','pair_parameters.py','declare_geometry.py',
            'common.py','account_reference.py','ledger_reference.py','analysis_reference.py')},
        'implementation_parent_authentication':'Exact native MEAN(EX028/N1) and BODY(EX029/N1) identity/source/parameters/dependencies/runtime-binding/formal full ledgers are intermediate background evidence only. Original registered C2132 identity/source/parameters/dependencies/runtime-binding/formal full ledgers are independently authenticated as the IMPLEMENTATION registration anchor. No registry parent claim or promotion for unqualified backgrounds. Parameter children derive authenticated new EX038 centers via PARAMETERS.'}
    write(PROTOCOLS/'geometry.json',geometry)
    ref=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'prospective-common-parameter-geometry',(PROTOCOLS/'geometry.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'geometry_reference.json',ref.to_dict())
    print({'geometry':'PUBLISHED','coordinates':13,'radius':.05,'points':32})

if __name__=='__main__':
    main()
