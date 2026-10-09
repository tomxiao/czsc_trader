"""Recover the already published controls after metadata-only extraction failure."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from hashlib import sha256
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from binding_control import compare_module
from common import ROOT, RUNS, PROTOCOLS, EXPERIMENT, read, write, center_cache, cache_read

FILES=('ad3aece40150f09f6c0ee238e73dd791e94184bf7444813024f7f69ac34440eb.json',
    'd09a23caab08f2f2b7d9c652e6f9c497b7700fbeefe6f30ab08068ca387877a7.json',
    '288aae68724cd55f7dcbb2005c17532ca9da596178cf17b9f4dccbb2eb8ac3f8.json',
    '8677fca2963e71a00b29ddef60e6a545b725b843f53f1f8138a3ee4544abec57.json',
    'b3dd2151890bb1e62e3207a341a21d98e2435decc8fd3f9a096ff114eb3a2e51.json',
    '7a2be2b2b01221f1ad78203dcb0732480dded0d926d983bef95a7916299172c6.json',
    'b5d558a55d16a9f308720b9d57ee51f33c57ffa76040f1267e13629fd256450c.json',
    '4d67d596cb0dbda064b8436dc7597b1587f42882c3a306ae1bf4386cf2fdf860.json')

def recover(filename):
    path=ROOT/'research/S013/assets/evidence'/EXPERIMENT.experiment_id/filename
    assert sha256(path.read_bytes()).hexdigest()==path.stem
    after=read(path)
    validate_evaluation_evidence(after)
    assert len(after['runs'])==1 and after['runs'][0]['scenario_id']=='baseline'
    identifier=after['runs'][0]['candidate_id']
    case=next(c for c in read(PROTOCOLS/'binding_control_plan.json')['cases'] if c['candidate_id']==identifier)
    assert after['assessment_evidence'][0]['candidate']['content_sha256']==case['child_content_sha256']
    old,previous=cache_read(center_cache(identifier))
    before=serialize_evaluation_evidence(old,previous)
    ref=EvidenceRef(EXPERIMENT,filename,path.stem,'application/json','stage4-rebound-baseline-'+identifier.lower(),'account_evaluation',5)
    ref.resolve(ROOT)
    try:
        comparison=compare_module().compare_evidence(before,after)
    except AssertionError as exc:
        comparison={'status':'FAIL','error':str(exc)}
    row={'candidate_id':identifier,'status':'SUCCEEDED','reference':ref.to_dict(),
        'old_request_hash':previous.request_hash,'new_request_hash':after['request_hash'],
        'old_result_hash':previous.result_hash,'new_result_hash':after['result_hash'],
        'old_cagr':previous.runs[0].observation.net_cagr,
        'new_cagr':after['runs'][0]['observation']['net_cagr'],
        'comparison':comparison,'old_input_bindings':before['input_bindings'],'new_input_bindings':after['input_bindings']}
    write(RUNS/'binding_controls'/(identifier+'.json'),row)
    return row

def main():
    with ProcessPoolExecutor(max_workers=4,mp_context=get_context('spawn')) as pool:
        rows=list(pool.map(recover,FILES))
    passed=all(r['comparison']['status']=='PASS' for r in rows)
    write(RUNS/'binding_controls.json',{'status':'PASS' if passed else 'FAIL',
        'scope':'8 unchanged-parameter controls across five implementations; recovered original published accounts without replay',
        'plan':read(PROTOCOLS/'binding_control_reference.json'),'rows':rows,
        'metadata_failure':{'exception':'KeyError: input_bindings','cause':'input_bindings is a top-level serialized field, not within request_identity',
            'effect':'All8 accounts had succeeded and were published; only proof metadata extraction failed. Original economic facts preserved.',
            'repair':'Use top-level bindings, authenticate the exact eight published files and rerun comparison only.'},
        'trial_count':'unchanged; repeated points are technical controls'})
    print({'binding_controls':'PASS' if passed else 'FAIL','rows':[{'candidate_id':r['candidate_id'],
        'comparison':r['comparison']['status'],'error':r['comparison'].get('error'),'old_cagr':r['old_cagr'],'new_cagr':r['new_cagr']} for r in rows]},flush=True)
    assert passed,'Input rebinding changes economic facts; preserve initial experiment and correct through a successor protocol'

if __name__=='__main__':
    main()
