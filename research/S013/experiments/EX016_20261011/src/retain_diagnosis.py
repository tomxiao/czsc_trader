"""Retain prior-account descriptive evidence and exact source with immutable inputs."""
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT,RUNS,PROTOCOLS,EXPERIMENT,read,write,context,cache_read


def main():
    assert not (RUNS/'previous_account_diagnosis.json').exists()
    ctx=context(1)
    diagnosis=read(ROOT/'.tmp/s013-anchor-exit-diagnostic.json')
    assert diagnosis['status']=='DESCRIPTIVE_COMPLETE'
    prior=ROOT/'research/S013/experiments/EX015_20261011/protocols'
    matrix=read(ROOT/'research/S013/assets/runs/EX015_20261011/parameter_matrix.json')
    refs={row['label']:row['reference'] for row in matrix['rows']}
    refs['C2132-center']=read(ROOT/'research/S013/assets/runs/EX015_20261011/account_references.json')['B0-TIME']
    assert len(refs)==65
    for label,value in refs.items():
        ref=EvidenceRef.from_dict(value)
        assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
        if label=='C2132-center':
            continue
        _,result=cache_read(ROOT/'.tmp/s013-mechanism-EX015/parameters'/(label+'.pkl.gz'))
        row=next(row for row in matrix['rows'] if row['label']==label)
        assert result.result_hash==row['result_hash'] and result.request_hash==row['request_hash']
    script=(ROOT/'.tmp/s013-anchor-exit-diagnostic.py').read_bytes()
    ref=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'prior-account-descriptive-source',script,'text/plain','txt'))
    output={'status':'DESCRIPTIVE_COMPLETE','diagnosis':diagnosis,'source':ref.to_dict(),
        'input_delivery':read(prior/'delivery_reference.json'),'input_accounts':refs,
        'identity_check':'All 65 full-account reference bytes hashed; all 64 parameter cache request/result hashes match the immutable matrix.',
        'technical_correction':'An unpublished first draft mixed signal and execution price units for future-window labels; final actual source uses one decision-close unit for anchors and future labels. Actual calendar-year cash/fee attribution was reconciled independently and unaffected.',
        'limits':'Post-hoc labels, repeated events and repeatedly seen development pool; no causal policy claim, no added threshold, horizon choice or account replay.'}
    write(RUNS/'previous_account_diagnosis.json',output)
    write(PROTOCOLS/'previous_account_diagnosis_reference.json',publish_evidence(ctx,MaterialEvidenceWrite(
        EXPERIMENT,'prior-account-descriptive-diagnosis',(RUNS/'previous_account_diagnosis.json').read_bytes(),'application/json','json')).to_dict())
    print({'retained':'DESCRIPTIVE_COMPLETE','immutable_account_inputs':65})


if __name__=='__main__':
    main()
