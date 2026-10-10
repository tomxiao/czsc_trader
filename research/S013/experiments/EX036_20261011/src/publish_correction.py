"""Declare identity-type and absent-cycle serialization corrections before recomputation."""
from copy import deepcopy
from common import ROOT,SRC,PROTOCOLS,EXPERIMENT,context,read,write,file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    assert not (PROTOCOLS/'correction_plan.json').exists()
    originals=read(PROTOCOLS/'method_references.json')
    ctx=context(1)
    proofs={}
    for name,path in (
        ('execution-failures',PROTOCOLS/'execution_failures.json'),
        ('confirmation-failure',ROOT/'.tmp/ex036-diagnosis/confirmation.json'),
        ('identity-type-difference',ROOT/'.tmp/ex036-diagnosis/identity_difference.json'),
        ('absent-cycle-nonfinite-paths',ROOT/'.tmp/ex036-diagnosis/nonfinite_paths.json')):
        proofs[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json')).to_dict()
    refs={}
    for name in ('confirmation','drawdown'):
        original=EvidenceRef.from_dict(originals[name])
        assert file_hash(original.resolve(ROOT))==original.sha256
        document=deepcopy(read(original.resolve(ROOT)))
        original_source=name+'_diagnosis.py'
        assert document['source_files'][original_source]==file_hash(SRC/original_source)
        document.update(name=document['name']+' technical-v2',
            source_files={name+'_diagnosis_v2.py':file_hash(SRC/(name+'_diagnosis_v2.py')),'common.py':file_hash(SRC/'common.py')},
            failed_method_reference=original.to_dict(),failed_source_sha256=file_hash(SRC/original_source),
            correction_proofs=proofs,
            correction=('Compare shared content hash between EvaluationIdentity and CandidateContentIdentity; separately authenticate source/dependency/parameters and native input/protocol/environment via exact full formal evidence. Serialize EvaluationLineage by public derivation and parameter_binding serializers.'
                        if name=='confirmation' else
                        'Preserve absent native cycle ids as explicit None using object dtype from original records, rather than pandas-coerced numeric NaN. Only cycle-id representation changes; every other nonfinite value remains an error. Original14 annual DD/log checks and all calculations unchanged.'),
            unchanged='Same native accounts/data/state/rules/weights/points/years/geometry/economic requirements. No account evaluation, fallback, partial PASS, candidate change or result-driven selection.')
        path=PROTOCOLS/(name+'_v2_method.json')
        write(path,document)
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'prospective-'+name+'-method-v2',path.read_bytes(),'application/json','json')).to_dict()
        write(PROTOCOLS/(name+'_v2_method_reference.json'),refs[name])
    correction={'status':'DECLARED','method_references':refs,'original_method_references':originals,'proof_references':proofs,
                'source_files':{name+'_diagnosis_v2.py':file_hash(SRC/(name+'_diagnosis_v2.py')) for name in refs},
                'new_account_evaluations':0,'economic_targets':'UNCHANGED','objective_achieved':False}
    write(PROTOCOLS/'correction_plan.json',correction)
    reference=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'declared-technical-correction',(PROTOCOLS/'correction_plan.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'correction_plan_reference.json',reference.to_dict())
    print({'technical_correction':'DECLARED','new_accounts':0},flush=True)


if __name__=='__main__':
    main()
