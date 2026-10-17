"""Preserve v1; add its missing public SRT calendar declaration under new IDs."""
from pathlib import Path
from hashlib import sha256
import json
import ast
from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256

EX=Path(__file__).resolve().parents[1];PACKAGE=EX/'src/strategy_runtime'
def main():
    original=PACKAGE/'strategies/repair.py';target=PACKAGE/'strategies/repair_v2.py'
    if target.exists():raise RuntimeError('Preserve corrected source')
    source=original.read_text(encoding='utf-8')
    old="inputs=InputContract(tuple(InputRequirement"
    new="inputs=InputContract((InputRequirement('calendar',Dataset.TRADING_CALENDAR.value,'SSE','daily',0,CutoffRule.SIGNAL_SESSION),)+tuple(InputRequirement"
    assert old in source;source=source.replace(old,new)
    source=source.replace("capabilities=RequiredCapabilities((Dataset.STOCK_OHLCV.value", "capabilities=RequiredCapabilities((Dataset.TRADING_CALENDAR.value,Dataset.STOCK_OHLCV.value")
    source=source.replace("for requirement in self.definition.inputs.requirements:\n", "for requirement in self.definition.inputs.requirements:\n            if requirement.name=='calendar':continue\n")
    # Economic functions are AST-identical; only input-contract declarations change.
    def functions(text):return {n.name:ast.dump(n) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
    assert functions(source)==functions(original.read_text(encoding='utf-8'))
    target.write_text(source,encoding='utf-8',newline='\n')
    files=('strategies/repair_v2.py','strategies/calibration_samples.csv')
    digest=implementation_sha256(files,source_root=PACKAGE);rows=[]
    for i,variant in enumerate(('parent_H1','parent_H3','high_H3','high_H3_low_H1'),5):
        payload={'runtime':{'module':'strategy_runtime.strategies.repair_v2','qualname':'RepairStrategy','contract_version':1,
                  'source_files':list(files),'source_sha256':digest},'parameters':{'variant':variant}}
        c=StrategyCandidate('S014',f'C{i:04}',payload,PACKAGE);StrategyRuntime().describe(c)
        (EX/f'protocols/payload_v2_{variant}.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
        rows.append({'variant':variant,'candidate':c.reference_id})
    pre=(EX/'src/precheck.py').read_text(encoding='utf-8').replace("others/precheck.json","others/precheck_v2.json").replace("strategies/repair.py","strategies/repair_v2.py")
    (EX/'src/precheck_v2.py').write_text(pre,encoding='utf-8')
    correction={'reason':'SRT preparation requires exactly one calendar InputRequirement; v1 declared calendar_request but omitted requirement',
        'first_attempt':'PREPARATION_FAILED_BEFORE_ACCOUNT_COMPUTATION','account_runs_before_fix':0,
        'original_sha256':sha256(original.read_bytes()).hexdigest(),'corrected_sha256':sha256(target.read_bytes()).hexdigest(),
        'economic_function_ast_identical':True,'fee_execution_variants_unchanged':True,'new_candidates':rows}
    (EX/'protocols/calendar_contract_correction.json').write_text(json.dumps(correction,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
