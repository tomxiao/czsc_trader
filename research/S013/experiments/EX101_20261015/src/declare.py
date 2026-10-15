"""Freeze exactly two business configurations before real history evaluation."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import ROOT, SOURCE, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, candidate, context, read, write, file_hash

def main():
    assert not (PROTOCOLS/'configurations.json').exists()
    original=read(PROTOCOLS/'original_payload.json')
    source=deepcopy(original['runtime'])
    source['module']='strategy_runtime.strategies.trend_participation'
    source['qualname']='TrendParticipation'
    source['source_files'].append('strategies/trend_participation.py')
    source['source_sha256']=implementation_sha256(source['source_files'],source_root=SOURCE)
    configs=[]
    identifiers=[f'C{i:04d}' for i in range(9200,10000)
        if not (ROOT/f'research/registrations/S013/candidates/C{i:04d}.json').exists()][:2]
    assert len(identifiers)==2
    for identifier,mode in zip(identifiers,('TREND_ONLY','COMBINED'),strict=True):
        payload=dict(parameters=dict(base=original['parameters'],trend=dict(mode=mode,entry_sessions=20,exit_sessions=10)),runtime=source)
        config=dict(mode=mode,candidate_id=identifier,payload=payload)
        identity=StrategyRuntime().identify(candidate(config),dependencies=DEPENDENCIES)
        config['content_sha256']=identity.content_sha256
        configs.append(config)
    declaration=dict(configurations=configs,source_files={p.relative_to(SRC).as_posix():file_hash(p)
        for p in SRC.rglob('*.py')},business_configurations=2,maximum_full_accounts=4,
        evaluation_order=['TREND_ONLY_SERIAL','TREND_ONLY_SPAWN_EQUIVALENCE','COMBINED_SPAWN'],
        planned_full_evaluations=3,remaining_contingency=1,baseline_full_evaluations=0,
        data='Only existing S013 development assets; providers explicitly forbidden',
        search='None: fixed 20/10, no trial or window search',
        mandate=read(PROTOCOLS/'mandate_reference.json'))
    write(PROTOCOLS/'configurations.json',declaration)
    refs=read(PROTOCOLS/'method_references.json')
    refs['configurations.json']=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,
        'trend-prospective-configurations',(PROTOCOLS/'configurations.json').read_bytes(),'application/json','json')).to_dict()
    write(PROTOCOLS/'method_references.json',refs)
    print({'declaration':'PASS','configurations':[(x['mode'],x['candidate_id']) for x in configs]})
if __name__=='__main__': main()
