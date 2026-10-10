"""Fix a common complete coordinate domain before viewing mechanism results."""
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import EXPERIMENT,PROTOCOLS,context,write

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
            'null stops/trail/momentum','zero cooldown','execution limit premium .01','fixed component ACF20; strict positive new-bull-transition entry close-to-close or close-to-open condition with known bound signal prices; no searched length or new tunable numeric coordinate'],
        'comparison':'Original C2132 and every new four-gate-qualified mechanism using identical declared domains and method. No performance-based point replacement. These are diagnostics, not new economic gates.',
        'difference_from_historical':'S013 EX011 snapshot preserves historical S007-native domain references/hashes but not actual domain bytes. This new prospective domain is explicitly declared before viewing EX020 results; same domains as EX015 and reuse exactly verified original H4 EX015 and H3 EX017 parameter accounts. Historical 9.5670/11.3476pp must not be substituted as same-domain baseline.',
        'reason':'Use complete source business-valid domains and existing S013 ACF search domain rather than invent outcome-sensitive narrower bounds; normalize both centers with the same domain.'}
    write(PROTOCOLS/'geometry.json',geometry)
    ref=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'prospective-common-parameter-geometry',(PROTOCOLS/'geometry.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'geometry_reference.json',ref.to_dict())
    print({'geometry':'PUBLISHED','coordinates':13,'radius':.05,'points':32})

if __name__=='__main__':
    main()
