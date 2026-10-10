"""Publish prospective static-contract correction; no complete account run."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def main():
    assert not (PROTOCOLS/'technical_correction_reference.json').exists()
    geometry=read(PROTOCOLS/'geometry.json')
    original=dict(geometry['helper_source_files'])
    original.update(read(PROTOCOLS/'plan.json')['source_files'])
    for name,digest in original.items():
        assert file_hash(SRC/name)==digest
    proof_path=ROOT/'.tmp/ex043-analysis-v2/focused.json'
    proof=read(proof_path)
    assert proof['status']=='PURE_PASS' and proof['new_account_evaluations']==0
    names=('analysis_reference_v2.py','analyze_v2.py','run_parameters_v2.py',
        'parameter_analysis_v2.py','pair_parameters_v2.py','technical_validation.py','declare_correction.py')
    value={'status':'PROSPECTIVE_TECHNICAL_CORRECTION','finding':'Frozen original43 summary only recognises old41 two mechanisms and rejects new classified direction refusals. Detected by static review and synthetic reproduction before native analysis; not a native economic/account failure.',
        'changes':'Only summarize receives four explicit selected category formulas and metadata domain checks; all other analysis_reference functions AST identical. v2 entry imports repaired summary; parameter helper keeps original source/geometry checks and adds successor hashes. Supplementary serialized structure describes all3 retained exit fields and selected strict BELOW/ABOVE category; public existing-control resolver now admits authorized EX041 origin. All runtime/13coordinates/gates/data/evaluations unchanged.',
        'runtime_changed':False,'new_account_evaluations':0,
        'original_geometry_sha256':file_hash(PROTOCOLS/'geometry.json'),'original_plan_sha256':file_hash(PROTOCOLS/'plan.json'),
        'original_source_files':original,'successor_source_files':{n:file_hash(SRC/n) for n in names},
        'helper_AST_check_source':(ROOT/'.tmp/ex043_helpers_ast.py').read_text(encoding='utf-8'),
        'helper_AST_check_sha256':file_hash(ROOT/'.tmp/ex043_helpers_ast.py'),
        'helper_AST_check':'PASS: parameter_analysis/pair functions unchanged; run_parameters changes only source_check/resolve_center/declare descriptive record; analyze only adds technical validation call.',
        'pure_proof':proof,'pure_proof_sha256':file_hash(proof_path),
        'pure_source':(ROOT/'.tmp/ex043-analysis-v2/focused_checks.py').read_text(encoding='utf-8'),
        'pure_source_sha256':file_hash(ROOT/'.tmp/ex043-analysis-v2/focused_checks.py'),
        'preservation':'Original frozen source and geometry remain unchanged; no replay/re-run of complete accounts. Original geometry all13 full32points unchanged, additive successor implementation frozen before any parameter preparation.'}
    write(PROTOCOLS/'technical_correction.json',value)
    ref=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'explicit-summary-technical-correction',
        (PROTOCOLS/'technical_correction.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'technical_correction_reference.json',ref.to_dict())
    write(PROTOCOLS/'technical_proof_references.json',{'summary-technical-correction':ref.to_dict()})
    print({'summary_helper_correction':'FROZEN','new_account_evaluations':0},flush=True)


if __name__=='__main__':
    main()
