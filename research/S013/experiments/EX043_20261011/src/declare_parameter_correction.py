"""Freeze retained execution failure and exact-prefix recovery before continuation."""
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, read, write, file_hash, context
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def main():
    assert not (PROTOCOLS/'parameter_execution_correction_reference.json').exists()
    checkpoint=read(RUNS/'parameter_matrix.json')
    assert len(checkpoint['rows'])==32 and checkpoint['actual_run_evaluations']==7
    failure={'status':'FAILED','phase':'parameter_fixed_queue_trial_registration','error_type':'ValueError',
        'message':'Cannot tell a COMPLETE trial.',
        'cause':'state.rows aliases manifest.reused_rows. Appending point0 mutates reused count32->33, point1 again calls tell0. Original checkpoint/study on disk remained pre-loop, all first8 exact native results cached and formally published.',
        'checkpoint':checkpoint,'runtime_changed':False,'lost_accounts':0,'completed_native_evaluations':7,
        'precheck_evaluations':2,'native_results_retained':'P00serial/spawn and P01..P07; all eight unique points formal evidence retained.'}
    write(PROTOCOLS/'parameter_execution_failure.json',failure)
    proof=read(ROOT/'.tmp/ex043-parameter-v3/focused.json')
    assert proof['status']=='PURE_PASS' and proof['new_account_evaluations']==0
    preserved=['research/S013/assets/runs/EX043_20261011/parameter_matrix.json',
        '.tmp/s013-mechanism-EX043/parameters/study.pkl.gz',
        'research/S013/experiments/EX043_20261011/src/run_parameters_v2.py',
        'research/S013/experiments/EX043_20261011/protocols/parameter_plans.json',
        'research/S013/experiments/EX043_20261011/protocols/parameter_execution_failure.json']
    preserved += [f'.tmp/s013-mechanism-EX043/parameters/N0-P{i:02d}.pkl.gz' for i in range(8)]
    preserved += ['.tmp/s013-mechanism-EX043/parameters/N0-P00-spawn.pkl.gz']
    names=('run_parameters_v3.py','parameter_analysis_v3.py','pair_parameters_v3.py',
        'parameter_execution_validation.py','recover_parameters.py','declare_parameter_correction.py')
    formal={p.relative_to(ROOT).as_posix():file_hash(p) for p in (ROOT/'research/S013/assets/evidence/EX043_20261011').glob('*.json')}
    correction={'status':'EXPLICIT_PARAMETER_EXECUTION_CORRECTION','runtime_changed':False,
        'new_account_evaluations_for_recovery':0,'remaining_new_native_points':24,'original_parameter_plan_unchanged':True,
        'preserved_files':{name:file_hash(ROOT/name) for name in preserved},'existing_formal_evidence':formal,
        'successor_source_files':{name:file_hash(SRC/name) for name in names},
        'changes':'Constant reused_count32 for trial mapping and deep-copied rows. New v3 checkpoint/study use explicit eight-result recovery; original checkpoint/study/code/plan immutable. Remaining24points executed once;7bulk+24bulk+2precheck=33actual/32business, no replay or substitute.',
        'failure':failure,'pure_proof':proof,
        'pure_source':(ROOT/'.tmp/ex043-parameter-v3/focused_checks.py').read_text(encoding='utf-8'),
        'pure_source_sha256':file_hash(ROOT/'.tmp/ex043-parameter-v3/focused_checks.py')}
    write(PROTOCOLS/'parameter_execution_correction.json',correction)
    refs=read(PROTOCOLS/'technical_proof_references.json')
    for name,path in (('parameter-execution-failure',PROTOCOLS/'parameter_execution_failure.json'),
                      ('explicit-parameter-execution-correction',PROTOCOLS/'parameter_execution_correction.json')):
        ref=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
        refs[name]=ref.to_dict()
        if name=='explicit-parameter-execution-correction':
            write(PROTOCOLS/'parameter_execution_correction_reference.json',ref.to_dict())
    write(PROTOCOLS/'technical_proof_references.json',refs)
    print({'parameter_execution_correction':'FROZEN','remaining_points':24,'account_replays':0},flush=True)


if __name__=='__main__':
    main()
