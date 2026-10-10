"""Prospective full-path diagnostics; no new account prepare or evaluation."""
from common import ROOT,SRC,PROTOCOLS,EXPERIMENT,context,read,write,file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    assert not (PROTOCOLS/'method_references.json').exists()
    assert not (PROTOCOLS/'plan.json').exists()
    prior=read(ROOT/'research/S013/experiments/EX035_20261011/protocols/plan.json')
    external={str(p.relative_to(ROOT).as_posix()):file_hash(p) for p in (
        *(ROOT/'research/S013/experiments/EX035_20261011/src'/name for name in
          ('common.py','account_reference.py','ledger_reference.py','analysis_reference.py','run_parameters.py')),
        ROOT/'research/S013/experiments/EX033_20261011/src/diagnose.py')}
    inputs={'original33':read(ROOT/'research/S013/experiments/EX033_20261011/protocols/diagnosis_reference.json'),
            'mean_center':read(ROOT/'research/S013/assets/runs/EX028_20261011/account_references.json')['N1']}
    for value in inputs.values():
        ref=EvidenceRef.from_dict(value)
        assert ref.experiment.strategy_id=='S013' and file_hash(ref.resolve(ROOT))==ref.sha256
    methods={
        'confirmation':{
            'name':'Full original33 native confirmation-boundary and fixed-weight predicate diagnosis',
            'method':'Authenticate all33 original complete-domain accounts and reconstruct causal original ACF/turnover/volume ranks. Keep all native base-eligible opportunities, route and natural-year counts. On common native flat pre-state compare original and point base eligibility and confirmation score/threshold predicates, including cross feature/threshold gates. Compare original(.5,.25,.25), equal component(1/3 each), and amount/volume-only(0,.5,.5) scores at the same native opportunity and each existing threshold. Quantiles/counts are descriptive; no propagated state or cash counterfactual.',
            'accounts':'Original C2132 plus exactly32 original EX015 full13-domain points, no point exclusion/replacement.',
            'inputs':{'original33':inputs['original33']}},
        'drawdown':{
            'name':'All-year native equity drawdown-route and adverse-excursion diagnosis',
            'method':'Authenticate original C2132 and EX028 N1 C8701. For every natural-year continuous-account maximum drawdown use carried opening equity, exact peak/trough/equity and daily log returns. Decompose peak-to-trough returns by executed invested state mapped to preceding valid signal active route and reason, with exact telescope verification. Describe all holding-signal adverse HFQ close displacement from signal entry anchor relative to strictly past20 mean TrueRange, and consecutive closes below entry. No recreated account or intervention profits.',
            'accounts':'Original C2132 and unqualified mean-centered bear ACF C8701; latter remains diagnostic only.',
            'inputs':inputs}}
    refs={}
    for name,value in methods.items():
        value.update(source_files={name+'_diagnosis.py':file_hash(SRC/(name+'_diagnosis.py')),'common.py':file_hash(SRC/'common.py')},
                     external_source_files=external,new_account_evaluations=0,
                     limits='Repeatedly seen S013 development pool and posthoc mechanism choice. All years/opportunities kept. Joint parameter comparisons are not isolated-parameter causality; predicate alternatives and route attribution are not propagated profits. No new gate, data, phase advancement or performance claim.')
        path=PROTOCOLS/(name+'_method.json')
        write(path,value)
        refs[name]=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'prospective-'+name+'-method',path.read_bytes(),'application/json','json')).to_dict()
    write(PROTOCOLS/'method_references.json',refs)
    plan={'name':'S013-EX036-complete-path-confirmation-drawdown-diagnosis','new_account_evaluations':0,
          'unique_native_accounts_reused':34,'method_references':refs,'input_references':inputs,
          'authorization':prior['authorization'],'mandate':prior['mandate'],
          'previous_delivery':read(ROOT/'research/S013/experiments/EX035_20261011/protocols/delivery_reference.json'),
          'source_files':{str(p.relative_to(SRC)):file_hash(p) for p in SRC.glob('*.py')},
          'external_source_files':external,
          'economic_targets':'Four unchanged original economic gates; all13 domains/units retained. No hard diagnostic veto added.',
          'selection_history':'Stop repeated-entry waiting after EX034/35 negative full-account evidence. Diagnose original confirmation and previously near-qualified C8701 on entire existing authorized pool before choosing next structural test.',
          'boundaries':'RSCH S013 stage3 only; zero new prepare/eval/data/dependency/platform/prod/PTE/merge/tag/push; no adjacent batch bytes.',
          'objective_achieved':False}
    write(PROTOCOLS/'plan.json',plan)
    ref=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'prospective-full-path-plan',(PROTOCOLS/'plan.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'plan_reference.json',ref.to_dict())
    print({'declared':EXPERIMENT.experiment_id,'new_accounts':0,'unique_reused':34},flush=True)


if __name__=='__main__':
    main()
